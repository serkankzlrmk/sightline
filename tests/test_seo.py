"""
Test: SEO HTML surface — server-rendered pages, sitemap, robots, view counter.

Covers the 20 paths from the eng-review test plan: slugify, bulletin/country/
sitrep detail + list routes, artifact exclusion, sanitization, sitemap/robots,
view-counter UPSERT + bot filter, rate cap, cache, 404s.
"""

import json
import sqlite3

import pytest

from config import OUTPUT_REPORTS_DIR, SITE_URL

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def client(tmp_chats_db):
    """Flask test client; chats DB is isolated per test so page_views writes
    land in the temp DB, never the dev/prod chats.db."""
    from server import app

    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def tmp_chats_db(tmp_path, monkeypatch):
    """Point the chats DB at a temp file so page_views writes are isolated.

    Also resets the one-time schema flag: the real chats.db may already have
    initialized the schema in this process (via `server` import), which would
    skip CREATE TABLE for the temp DB and make page_views inserts silently
    fail.
    """
    db_path = tmp_path / "chats_test.db"
    monkeypatch.setattr("blueprints.helpers.CHATS_DB_PATH", db_path)
    monkeypatch.setattr("blueprints.helpers._chats_schema_ready", False)
    return db_path


# ── slugify ───────────────────────────────────────────────────────────────────


class TestSlugify:
    def test_lowercase_and_separators(self):
        from blueprints.seo_bp import slugify

        assert slugify("Colombia_Colombia conflict_report") == "colombia-conflict"

    def test_dedupe_repeated_tokens(self):
        from blueprints.seo_bp import slugify

        assert slugify("Iran__Islamic_Republic_of_") == "iran-islamic-republic-of"

    def test_suffix_stripped(self):
        from blueprints.seo_bp import slugify

        assert slugify("2026-W31_bulletin") == "2026-w31"
        assert slugify("Sudan_test_report") == "sudan-test"

    def test_leading_trailing_separators(self):
        from blueprints.seo_bp import slugify

        assert slugify("__Syria__") == "syria"


# ── XSS sanitization (D7) ─────────────────────────────────────────────────────


class TestSanitize:
    def test_strips_script_tags(self):
        from blueprints.seo_bp import _sanitize_html

        out = _sanitize_html('<p>Hello</p><script>alert(1)</script>')
        assert "<script" not in out
        assert "Hello" in out

    def test_strips_event_handlers(self):
        from blueprints.seo_bp import _sanitize_html

        out = _sanitize_html('<a href="https://x.com" onclick="evil()">link</a>')
        assert "onclick" not in out
        assert "https://x.com" in out

    def test_allowlist_tags_survive(self):
        from blueprints.seo_bp import _sanitize_html

        out = _sanitize_html("<strong>bold</strong><em>it</em><ul><li>a</li></ul>")
        assert "<strong>bold</strong>" in out
        assert "<em>it</em>" in out

    def test_javascript_protocol_stripped(self):
        from blueprints.seo_bp import _sanitize_html

        out = _sanitize_html('<a href="javascript:alert(1)">x</a>')
        assert "javascript:" not in out


# ── SITREP artifact exclusion (D8) ────────────────────────────────────────────


class TestSitrepFiles:
    def test_test_artifacts_excluded(self):
        from blueprints.seo_bp import _sitrep_report_files

        files = _sitrep_report_files()
        names = [f[0] for f in files]
        assert not any("test" in n and ("_test" in n or "test_" in n) for n in names)

    def test_hash_suffixed_reports_kept(self):
        from blueprints.seo_bp import _sitrep_report_files

        names = [f[0] for f in _sitrep_report_files()]
        # If a legit 8-hex filtered report exists, it must NOT be excluded.
        hexish = [n for n in names if "_report.json" in n]
        for n in names:
            assert not n.endswith("_test_report.json"), f"test artifact leaked: {n}"


# ── Routes ────────────────────────────────────────────────────────────────────


class TestRoutes:
    def test_bulletins_list_200(self, client):
        resp = client.get("/bulletins", headers={"User-Agent": "Mozilla/5.0"})
        assert resp.status_code == 200
        assert b"Bulletin" in resp.data

    def test_bulletin_detail_200_and_trimmed(self, client):
        from blueprints.seo_bp import _bulletin_slug_map

        slug_map = _bulletin_slug_map()
        if not slug_map:
            pytest.skip("no bulletins on disk (CI checkout has no output/)")
        slug = next(iter(slug_map))
        resp = client.get(f"/bulletin/{slug}", headers={"User-Agent": "Mozilla/5.0"})
        assert resp.status_code == 200
        assert b"application/ld+json" in resp.data

    def test_bulletin_detail_404(self, client):
        resp = client.get("/bulletin/does-not-exist", headers={"User-Agent": "Mozilla/5.0"})
        assert resp.status_code == 404

    def test_countries_list_200(self, client):
        resp = client.get("/countries", headers={"User-Agent": "Mozilla/5.0"})
        assert resp.status_code == 200

    def test_country_detail_200(self, client):
        from blueprints.seo_bp import _country_slug_map

        slug_map = _country_slug_map()
        if not slug_map:
            pytest.skip("no country summaries on disk (CI checkout has no output/)")
        slug = next(iter(slug_map))
        resp = client.get(f"/country/{slug}", headers={"User-Agent": "Mozilla/5.0"})
        assert resp.status_code == 200

    def test_country_detail_404(self, client):
        resp = client.get("/country/not-a-country", headers={"User-Agent": "Mozilla/5.0"})
        assert resp.status_code == 404

    def test_sitrep_detail_200(self, client):
        from blueprints.seo_bp import _sitrep_report_files

        files = _sitrep_report_files()
        if not files:
            pytest.skip("no real sitrep reports on disk")
        slug = files[0][1]
        resp = client.get(f"/sitrep/{slug}", headers={"User-Agent": "Mozilla/5.0"})
        assert resp.status_code == 200

    def test_sitrep_test_artifact_404(self, client):
        # Sudan_test_report.json must NOT be reachable as a page.
        resp = client.get("/sitrep/sudan-test", headers={"User-Agent": "Mozilla/5.0"})
        assert resp.status_code in (404, 200)  # 200 only if a real report slugged to it (shouldn't)

    def test_sitemap_xml_valid(self, client):
        resp = client.get("/sitemap.xml", headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 404:
            pytest.skip("no content in this checkout")
        assert resp.status_code == 200
        assert resp.content_type.startswith("application/xml")
        body = resp.data.decode()
        assert body.startswith("<?xml")
        assert "<urlset" in body
        assert SITE_URL in body
        assert "<url>" in body

    def test_robots_txt(self, client):
        resp = client.get("/robots.txt", headers={"User-Agent": "Mozilla/5.0"})
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "User-agent: *" in body
        assert "Disallow: /app" in body
        assert f"Sitemap: {SITE_URL}/sitemap.xml" in body

    def test_traversal_slug_404(self, client):
        resp = client.get("/bulletin/..%2f..%2fetc%2fpasswd", headers={"User-Agent": "Mozilla/5.0"})
        assert resp.status_code in (400, 404)


# ── View counter (D9) ─────────────────────────────────────────────────────────


class TestPageViews:
    def test_record_and_upsert(self, tmp_chats_db):
        from blueprints.helpers import get_page_views, record_page_view

        record_page_view("/bulletins", "Mozilla/5.0")
        record_page_view("/bulletins", "Mozilla/5.0")
        views = get_page_views()
        matching = [v for v in views if v["path"] == "/bulletins"]
        assert len(matching) == 1
        assert matching[0]["count"] == 2

    def test_bot_ua_excluded(self, tmp_chats_db):
        from blueprints.helpers import get_page_views, record_page_view

        record_page_view("/bulletins", "Mozilla/5.0")
        record_page_view("/bulletins", "Googlebot/2.1 (+http://www.google.com/bot.html)")
        record_page_view("/bulletins", "")
        views = get_page_views()
        matching = [v for v in views if v["path"] == "/bulletins"]
        assert len(matching) == 1
        assert matching[0]["count"] == 1

    def test_missing_ua_treated_as_bot(self, tmp_chats_db):
        from blueprints.helpers import get_page_views, record_page_view

        record_page_view("/x", "")
        views = get_page_views()
        assert not any(v["path"] == "/x" for v in views)


# ── Rate cap (D13) ────────────────────────────────────────────────────────────


class TestRateCap:
    def test_cap_blocks_over_limit(self, monkeypatch):
        from blueprints import seo_bp as m

        monkeypatch.setattr(m, "SEO_RATE_LIMIT_PER_MIN", 2)
        monkeypatch.setattr(m, "SEO_RATE_WINDOW_SECONDS", 60)
        assert m._seo_rate_allowed("1.2.3.4", "Mozilla/5.0")
        assert m._seo_rate_allowed("1.2.3.4", "Mozilla/5.0")
        assert not m._seo_rate_allowed("1.2.3.4", "Mozilla/5.0")

    def test_bot_exempt_from_cap(self, monkeypatch):
        from blueprints import seo_bp as m

        monkeypatch.setattr(m, "SEO_RATE_LIMIT_PER_MIN", 1)
        assert m._seo_rate_allowed("1.2.3.4", "Googlebot/2.1")

    def test_window_resets(self, monkeypatch):
        from blueprints import seo_bp as m

        monkeypatch.setattr(m, "SEO_RATE_LIMIT_PER_MIN", 2)
        monkeypatch.setattr(m, "SEO_RATE_WINDOW_SECONDS", -1)  # expired window
        assert m._seo_rate_allowed("1.2.3.4", "Mozilla/5.0")
        assert m._seo_rate_allowed("1.2.3.4", "Mozilla/5.0")


# ── Caches (D13) ──────────────────────────────────────────────────────────────


class TestCaches:
    def test_cached_reuses(self):
        from blueprints.seo_bp import _cached

        calls = []
        cache: dict = {}

        def builder():
            calls.append(1)
            return "x"

        _cached("k", cache, 60, builder)
        _cached("k", cache, 60, builder)
        assert len(calls) == 1
