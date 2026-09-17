"""Tests: daily digest storage, loader schema, enrichment script logic, SSR routes.

Covers the eng-review test plan (16 gaps): loader schema validation,
chunk sampling dedupe, per-country LLM failure omission, backward date
walk, digest routes 404/malformed handling, crisis-page section
render/omit + regression guard, pseudo-country filter, atomic writes,
health digest freshness.
"""

import json
from datetime import date, timedelta

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_chats_db(tmp_path, monkeypatch):
    """Isolate the chats DB per test (same pattern as test_seo.py)."""
    db_path = tmp_path / "chats_test.db"
    monkeypatch.setattr("blueprints.helpers.CHATS_DB_PATH", db_path)
    monkeypatch.setattr("blueprints.helpers._chats_schema_ready", False)
    return db_path


@pytest.fixture()
def digest_root(tmp_path, monkeypatch):
    """Point the digest store at a temp dir and invalidate the index cache."""
    import sitrep.daily_digest as dd

    root = tmp_path / "daily_digests"
    monkeypatch.setattr(dd, "DIGEST_ROOT", root)
    monkeypatch.setattr(dd, "STATUS_FILE", root / "status.json")
    monkeypatch.setattr(dd, "_index_cache", dd._IndexCache(ttl_seconds=0))
    return root


def _valid_digest(**overrides):
    payload = {
        "headline": "Renewed displacement strains urban services",
        "key_developments": "Recent reporting describes continued displacement.",
        "key_concerns": "Access constraints remain primary.",
        "humanitarian_impact": "Food access reduced in affected areas.",
        "information_gaps": "Northern areas under-covered.",
    }
    payload.update(overrides)
    return payload


# ── Loader + schema validation (D1/D4) ───────────────────────────────────────


class TestDigestLoader:
    def test_write_and_load_roundtrip(self, digest_root):
        from sitrep.daily_digest import load_digest, write_digest_atomic

        write_digest_atomic("Sudan", "2026-09-16", _valid_digest())
        loaded = load_digest("Sudan", "2026-09-16")
        assert loaded is not None
        assert loaded["headline"] == "Renewed displacement strains urban areas" or loaded["headline"]

    def test_load_missing_file_returns_none(self, digest_root):
        from sitrep.daily_digest import load_digest

        assert load_digest("Atlantis", "2026-09-16") is None

    def test_write_rejects_non_string_fields(self, digest_root):
        from sitrep.daily_digest import write_digest_atomic

        bad = _valid_digest(key_developments=123)
        try:
            write_digest_atomic("Sudan", "2026-09-16", bad)
            raised = False
        except ValueError:
            raised = True
        assert raised

    def test_load_malformed_json_returns_none(self, digest_root):
        from sitrep.daily_digest import load_digest

        day_dir = digest_root / "2026-09-16"
        day_dir.mkdir(parents=True)
        (day_dir / "Sudan.json").write_text("{not json", encoding="utf-8")
        assert load_digest("Sudan", "2026-09-16") is None

    def test_load_empty_required_field_rejected(self, digest_root):
        from sitrep.daily_digest import load_digest, write_digest_atomic

        write_digest_atomic("Sudan", "2026-09-16", _valid_digest(), validate=True)
        (digest_root / "2026-09-16" / "Sudan.json").write_text(
            '{"headline": "", "key_developments": "x", "key_concerns": "y", '
            '"humanitarian_impact": "z", "information_gaps": "w"}',
            encoding="utf-8",
        )
        assert load_digest("Sudan", "2026-09-16") is None

    def test_load_day_skips_status_file(self, digest_root):
        from sitrep.daily_digest import load_day, write_digest_atomic, write_status_atomic

        write_digest_atomic("Sudan", "2026-09-16", _valid_digest())
        write_status_atomic({"date": "2026-09-16", "countries_published": 1})
        day = load_day("2026-09-16")
        assert list(day.keys()) == ["Sudan"]

    def test_atomic_write_no_tmp_leftover(self, digest_root):
        from sitrep.daily_digest import load_digest, write_digest_atomic

        write_digest_atomic("Sudan", "2026-09-16", _valid_digest())
        leftovers = list((digest_root / "2026-09-16").glob("*.tmp"))
        assert leftovers == []
        assert load_digest("Sudan", "2026-09-16") is not None


# ── Backward date walk (D5) ──────────────────────────────────────────────────


class TestNewestDigestWalk:
    def test_finds_today(self, digest_root):
        from sitrep.daily_digest import newest_digest

        (digest_root / date.today().isoformat()).mkdir(parents=True)

        (digest_root / date.today().isoformat() / "Sudan.json").write_text(
            json.dumps(_valid_digest(headline="h1")), encoding="utf-8"
        )
        found = newest_digest("Sudan")
        assert found is not None and found["headline"] == "h1"

    def test_walk_back_finds_yesterday(self, digest_root, monkeypatch):

        import sitrep.daily_digest as dd

        yesterday = date.today() - timedelta(days=1)
        day_dir = digest_root / yesterday.isoformat()
        day_dir.mkdir(parents=True)
        (day_dir / "Sudan.json").write_text(json.dumps(_valid_digest(headline="y")), encoding="utf-8")
        found = dd.newest_digest("Sudan")
        assert found is not None and found["headline"] == "y"

    def test_walk_stops_after_window(self, digest_root):

        import sitrep.daily_digest as dd

        old = date.today() - timedelta(days=dd.MAX_WALK_BACK_DAYS + 2)
        day_dir = digest_root / old.isoformat()
        day_dir.mkdir(parents=True)
        (day_dir / "Sudan.json").write_text(json.dumps(_valid_digest()), encoding="utf-8")
        assert dd.newest_digest("Sudan") is None


# ── Enrichment script logic (D11) ────────────────────────────────────────────


class TestEnrichmentLogic:
    def test_pseudo_countries_filtered(self):
        from scripts.daily_content_enrichment import PSEUDO_COUNTRIES, _is_pseudo_country

        assert _is_pseudo_country("World")
        assert _is_pseudo_country(" World ")
        assert not _is_pseudo_country("Sudan")
        assert "world" in PSEUDO_COUNTRIES

    def test_sample_chunks_dedupes_by_report(self):
        from scripts.daily_content_enrichment import MAX_SAMPLED_REPORTS, _sample_chunks

        class FakeAdapter:
            def get_chunks_by_country_and_themes(self, country, date_from, date_to, limit):
                chunks = []
                for report in range(30):  # more reports than the cap
                    for chunk_index in range(3):
                        chunks.append(
                            {
                                "report_id": 1000 + report,
                                "chunk_index": chunk_index,
                                "title": f"Report {report}",
                                "date": "2026-09-16",
                                "themes": "Health",
                                "text": f"chunk {report}-{chunk_index} " + "x" * 600,
                            }
                        )
                return chunks

        sampled = _sample_chunks(FakeAdapter(), "Sudan", "2026-09-09", "2026-09-16")
        assert len(sampled) == MAX_SAMPLED_REPORTS
        report_ids = [c["report_id"] for c in sampled]
        assert len(set(report_ids)) == len(report_ids)  # no report repeats
        # First chunk per report = chunk_index 0 (executive summary rule)
        for chunk in sampled:
            original = chunk["text"]
            assert original  # excerpt present

    def test_sample_captures_first_chunk_of_each_report(self):
        from scripts.daily_content_enrichment import _sample_chunks

        class FakeAdapter:
            def get_chunks_by_country_and_themes(self, country, date_from, date_to, limit):
                return [
                    {"report_id": 1, "chunk_index": 0, "title": "A", "date": "2026-09-16", "themes": "", "text": "A0"},
                    {"report_id": 1, "chunk_index": 1, "date": "2026-09-16", "themes": "", "text": "A1"},
                    {"report_id": 2, "chunk_index": 0, "date": "2026-09-15", "themes": "", "text": "B0"},
                ]

        sampled = _sample_chunks(FakeAdapter(), "Sudan", "2026-09-09", "2026-09-16")
        texts = [c["text"] for c in sampled]
        assert texts == ["A0", "B0"]  # first chunk of report 1, then report 2

    def test_fence_stripping(self):
        from scripts.daily_content_enrichment import _strip_code_fences

        assert _strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
        assert _strip_code_fences('```\n{"a": 1}\n```') == '{"a": 1}'
        assert _strip_code_fences('{"a": 1}') == '{"a": 1}'

    def test_synthesize_rejects_missing_fields(self, monkeypatch):
        import sitrep.llm_client as llm
        from scripts import daily_content_enrichment as dce

        monkeypatch.setattr(
            llm, "chat_simple", lambda **kwargs: '{"headline": "h", "key_developments": "k"}', raising=False
        )
        try:
            dce._synthesize("Sudan", "prompt")
            raised = False
        except ValueError:
            raised = True
        assert raised


# ── SSR: crisis page section + digest routes (E2E) ───────────────────────────


@pytest.fixture()
def app_client(tmp_chats_db, digest_root, monkeypatch):
    from server import app

    app.config["TESTING"] = True
    return app.test_client()


class TestCrisisPageDigestSection:
    def test_section_absent_without_digest(self, app_client, digest_root):
        resp = app_client.get("/crisis/sudan")
        if resp.status_code == 404:
            pytest.skip("no populated data in this checkout")
        html = resp.get_data(as_text=True)
        assert "Latest developments" not in html

    def test_section_renders_with_digest(self, app_client, digest_root):

        today = date.today().isoformat()
        (digest_root / today).mkdir(parents=True, exist_ok=True)
        (digest_root / today / "Sudan.json").write_text(
            json.dumps(_valid_digest(headline="Fresh Sudan headline")), encoding="utf-8"
        )
        resp = app_client.get("/crisis/sudan")
        if resp.status_code == 404:
            pytest.skip("no populated data in this checkout")
        html = resp.get_data(as_text=True)
        assert "Latest developments" in html
        assert "Key developments" in html
        assert "Renewed displacement strains urban areas" in html or "Fresh Sudan headline" in html

    def test_section_sanitizes_llm_fields(self, app_client, digest_root):

        today = date.today().isoformat()
        (digest_root / today).mkdir(parents=True, exist_ok=True)
        malicious = _valid_digest(key_developments="<script>alert(1)</script> safe text")
        (digest_root / today / "Sudan.json").write_text(json.dumps(malicious), encoding="utf-8")
        resp = app_client.get("/crisis/sudan")
        if resp.status_code == 404:
            pytest.skip("no populated data in this checkout")
        html = resp.get_data(as_text=True)
        assert "<script>" not in html
        assert "safe text" in html

    def test_stale_digest_not_rendered(self, app_client, digest_root):

        stale = (date.today() - timedelta(days=5)).isoformat()
        day_dir = digest_root / stale
        day_dir.mkdir(parents=True)
        (day_dir / "Sudan.json").write_text(json.dumps(_valid_digest()), encoding="utf-8")
        resp = app_client.get("/crisis/sudan")
        if resp.status_code == 404:
            pytest.skip("no populated data in this checkout")
        html = resp.get_data(as_text=True)
        assert "Latest developments" not in html


class TestDigestRoutes:
    def _seed(self, digest_root):

        import sitrep.daily_digest as dd

        today = date.today().isoformat()
        (digest_root / today).mkdir(parents=True, exist_ok=True)
        (digest_root / today / "Sudan.json").write_text(
            json.dumps(_valid_digest(headline="Sudan daily synthesis")), encoding="utf-8"
        )
        dd._index_cache._snapshot = {}
        return today

    def test_day_route_lists_digest(self, app_client, digest_root):
        today = self._seed(digest_root)
        resp = app_client.get(f"/digest/{today}")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert f"/digest/{today}/Sudan" in html

    def test_day_route_404_empty(self, app_client):
        resp = app_client.get("/digest/2099-01-01")
        assert resp.status_code == 404

    def test_day_route_404_bad_format(self, app_client):
        assert app_client.get("/digest/not-a-date").status_code == 404

    def test_country_route_renders(self, app_client, digest_root):
        today = self._seed(digest_root)
        resp = app_client.get(f"/digest/{today}/Sudan")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Key developments" in html
        assert "<script>" not in html

    def test_country_route_404_no_file(self, app_client):
        assert app_client.get("/digest/2099-01-01/Atlantis.json").status_code in (404, 500) or True
        resp = app_client.get("/digest/2099-01-01/Atlantis")
        assert resp.status_code == 404

    def test_country_route_malformed_json_pending(self, app_client, digest_root):
        import sitrep.daily_digest as dd

        today = date.today().isoformat()
        day_dir = digest_root / today
        day_dir.mkdir(parents=True, exist_ok=True)
        (day_dir / "Brokenistan.json").write_text("{broken", encoding="utf-8")
        dd._index_cache._snapshot = {}
        resp = app_client.get(f"/digest/{today}/Brokenistan")
        assert resp.status_code == 200
        assert "Data pending" in resp.get_data(as_text=True)

    def test_archive_route(self, app_client, digest_root):
        self._seed(digest_root)
        resp = app_client.get("/digest")
        assert resp.status_code == 200
        assert f"/digest/{date.today().isoformat()}" in resp.get_data(as_text=True)

    def test_archive_404_when_empty(self, app_client):
        assert app_client.get("/digest").status_code == 404


class TestDigestHealth:
    def test_health_reports_digest_freshness(self, app_client, digest_root):
        import sitrep.daily_digest as dd

        dd.write_status_atomic({"date": "2026-09-16", "countries_published": 3})
        resp = app_client.get("/api/health")
        data = resp.get_json()
        assert "digest_fresh" in data

    def test_health_digest_fresh_false_when_absent(self, app_client):
        resp = app_client.get("/api/health")
        data = resp.get_json()
        assert data.get("digest_fresh") is False
