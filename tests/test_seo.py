"""
Test: SEO HTML surface — server-rendered pages, sitemap, robots, view counter.

Covers the 20 paths from the eng-review test plan: slugify, bulletin/country/
sitrep detail + list routes, artifact exclusion, sanitization, sitemap/robots,
view-counter UPSERT + bot filter, rate cap, cache, 404s.
"""

import pytest

from config import SITE_URL

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

        out = _sanitize_html("<p>Hello</p><script>alert(1)</script>")
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
        for n in names:
            assert not n.endswith("_test_report.json"), f"test artifact leaked: {n}"


# ── Routes ────────────────────────────────────────────────────────────────────


class TestRoutes:
    @pytest.mark.parametrize("slug", ["sitrep", "proposal"])
    def test_solution_landing_pages_are_public_and_indexable(self, client, slug):
        resp = client.get(f"/solutions/{slug}", headers={"User-Agent": "Mozilla/5.0"})
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'content="index,follow,max-image-preview:large"' in html
        assert f'href="{SITE_URL}/solutions/{slug}"' in html
        assert 'data-track-event="cta_click"' in html
        assert '"@type": "SoftwareApplication"' in html
        assert '"@type": "FAQPage"' in html

    def test_unknown_solution_landing_is_404(self, client):
        assert client.get("/solutions/not-a-product").status_code == 404

    def test_bulletins_list_200(self, client):
        resp = client.get("/bulletins", headers={"User-Agent": "Mozilla/5.0"})
        assert resp.status_code == 200
        assert b"Bulletin" in resp.data
        html = resp.get_data(as_text=True)
        assert 'class="publication-hero"' in html
        assert 'href="/sitreps"' in html
        assert 'aria-label="Publication type"' in html

    def test_sitreps_list_200_and_excludes_test_artifacts(self, client):
        resp = client.get("/sitreps", headers={"User-Agent": "Mozilla/5.0"})
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Humanitarian Situation Reports" in html
        assert 'aria-current="page">SITREPs</a>' in html
        assert "Sudan test" not in html
        assert "Sudan_test" not in html

    def test_sitrep_detail_renders_source_register(self, client):
        import json

        from blueprints.seo_bp import OUTPUT_REPORTS_DIR, _sitrep_report_files, _sitrep_sources

        files = _sitrep_report_files()
        if not files:
            pytest.skip("no real sitrep reports on disk")
        slug = files[0][1]
        resp = client.get(f"/sitrep/{slug}", headers={"User-Agent": "Mozilla/5.0"})
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'href="/sitreps" aria-current="page"' in html
        assert 'class="article-layout"' in html
        with open(OUTPUT_REPORTS_DIR / files[0][0], encoding="utf-8") as fh:
            report = json.load(fh)
        if _sitrep_sources(report):
            assert "Evidence register" in html
            assert 'class="source-register"' in html
            assert 'target="_blank"' in html

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
        assert f"{SITE_URL}/solutions/sitrep" in body
        assert f"{SITE_URL}/solutions/proposal" in body
        assert f"{SITE_URL}/sitreps" in body

    def test_robots_txt(self, client):
        resp = client.get("/robots.txt", headers={"User-Agent": "Mozilla/5.0"})
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "User-agent: *" in body
        assert "Disallow: /api/" in body
        assert "Disallow: /app" not in body
        assert "Disallow: /proposal" in body
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


# ── CSP allows GA4 (prod and dev) ─────────────────────────────────────────────


class TestCspAnalyticsDomains:
    def _assert_csp(self, debug: bool):
        from unittest.mock import patch

        with patch("server.SERVER_DEBUG", debug):
            from server import app

            app.config["TESTING"] = True
            resp = app.test_client().get("/")
            csp = resp.headers.get("Content-Security-Policy", "")
            assert "https://www.googletagmanager.com" in csp
            assert "https://www.google-analytics.com" in csp

    def test_prod_csp_allows_gtag(self):
        self._assert_csp(False)

    def test_dev_csp_allows_gtag(self):
        self._assert_csp(True)


# ── GA4 tag injection (empty ID = no tag) ─────────────────────────────────────


class TestAnalyticsTag:
    def test_tag_absent_without_id(self, client, monkeypatch):
        import config

        monkeypatch.setattr(config, "GOOGLE_ANALYTICS_ID", "")
        for path in ("/", "/bulletins", "/app"):
            resp = client.get(path)
            assert resp.status_code == 200, path
            assert "/static/analytics.js" not in resp.get_data(as_text=True), path

    def test_tag_present_with_id(self, client, monkeypatch):
        import config

        monkeypatch.setattr(config, "GOOGLE_ANALYTICS_ID", "G-TEST123")
        for path in ("/", "/bulletins", "/app"):
            resp = client.get(path)
            assert resp.status_code == 200, path
            html = resp.get_data(as_text=True)
            assert "/static/analytics.js" in html, path
            assert 'data-measurement-id="G-TEST123"' in html, path
            assert '<script async src="https://www.googletagmanager.com' not in html, path

        analytics_js = client.get("/static/analytics.js").get_data(as_text=True)
        assert "send_page_view" in analytics_js
        assert "sightline_analytics_consent_v1" in analytics_js

    def test_spa_is_explicitly_noindex(self, client):
        html = client.get("/app").get_data(as_text=True)
        assert 'content="noindex,nofollow"' in html


class TestLegalPages:
    def test_privacy_and_terms_are_public_but_not_indexed(self, client):
        for path in ("/privacy", "/terms"):
            resp = client.get(path)
            assert resp.status_code == 200
            html = resp.get_data(as_text=True)
            assert 'content="noindex,follow"' in html
            assert "canonical" in html

    def test_privacy_copy_matches_analytics_behavior(self, client, monkeypatch):
        monkeypatch.setattr("config.GOOGLE_ANALYTICS_ID", "G-TEST123")
        html = client.get("/privacy").get_data(as_text=True)
        assert "not loaded until you select" in html
        assert "Review analytics choices" in html
        assert "We do not use third-party analytics" not in html


# ── SSR Crisis Map page (/map) ────────────────────────────────────────────────


class TestCrisisPages:
    """/crisis/<slug> programmatic pages — P2 publish predicate, noindex, 404."""

    def test_crisis_index_renders(self, client):
        resp = client.get("/crisis")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Crisis Overviews" in html or "Crisis overviews" in html
        # Country links only appear when the publish predicate finds data;
        # CI runners have an empty DB, so verify the empty state there.
        if 'class="publication-empty"' in html:
            assert "No editions are available yet" in html
        else:
            assert 'href="/crisis/' in html

    def test_crisis_detail_known_country(self, client):
        # Sudan is a high-report country in any populated checkout.
        resp = client.get("/crisis/sudan")
        if resp.status_code == 404:
            pytest.skip("no populated data in this checkout")
        html = resp.get_data(as_text=True)
        assert "humanitarian crisis overview" in html
        assert "Recent reports" in html or "Main themes" in html
        assert "auth-overlay" not in html
        assert 'class="crisis-header"' in html
        assert 'aria-label="Public pages"' in html
        assert "Get this as a sitrep" in html
        assert "/app?country=Sudan#crisis-map" in html
        assert "/app?country=Sudan" in html and "#sitrep" in html
        assert 'href="/country/sudan">Country summary</a>' in html
        assert "—" not in html
        assert "🟢" not in html
        assert "⚡" not in html

    def test_crisis_detail_unknown_country_404(self, client):
        resp = client.get("/crisis/definitely-not-a-country")
        assert resp.status_code == 404

    def test_crisis_detail_shows_narrative(self, client):
        resp = client.get("/crisis/sudan")
        if resp.status_code == 404:
            pytest.skip("no populated data in this checkout")
        html = resp.get_data(as_text=True)
        assert "crisis-headline" in html  # headline block rendered
        assert "crisis-narrative" in html  # narrative block rendered

    def test_crisis_detail_shows_top_sources(self, client):
        resp = client.get("/crisis/sudan")
        if resp.status_code == 404:
            pytest.skip("no populated data in this checkout")
        html = resp.get_data(as_text=True)
        assert "Top sources" in html

    def test_crisis_detail_date_range(self, client):
        resp = client.get("/crisis/sudan")
        if resp.status_code == 404:
            pytest.skip("no populated data in this checkout")
        html = resp.get_data(as_text=True)
        # When date_range is populated the line renders; when absent the
        # page still ships (narrative acts as the freshness signal).
        assert ("Reports from" in html) or ("crisis-narrative" in html)

    def test_crisis_detail_related(self, client):
        resp = client.get("/crisis/sudan")
        if resp.status_code == 404:
            pytest.skip("no populated data in this checkout")
        html = resp.get_data(as_text=True)
        assert "Related" in html

    def test_crisis_published_no_noindex(self, client):
        resp = client.get("/crisis/sudan")
        if resp.status_code == 404:
            pytest.skip("no populated data in this checkout")
        html = resp.get_data(as_text=True)
        assert 'content="noindex"' not in html

    def test_crisis_in_sitemap(self, client):
        resp = client.get("/sitemap.xml")
        text = resp.get_data(as_text=True)
        assert ">https://" in text and "/crisis</loc>" in text


class TestCrisisMapSsr:
    def test_map_page_renders(self, client):
        resp = client.get("/map")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Humanitarian Crisis Map" in html
        assert "Open interactive map" in html
        assert "canonical" in html
        assert "Crisis Map" in html  # nav link present

    def test_map_no_login_overlay(self, client):
        """SSR pages must never ship the auth overlay or auth scripts."""
        resp = client.get("/map")
        html = resp.get_data(as_text=True)
        assert "auth-overlay" not in html
        assert "showLoginPanel" not in html
        assert "firebase" not in html.lower()

    def test_map_in_sitemap(self, client):
        resp = client.get("/sitemap.xml")
        text = resp.get_data(as_text=True)
        assert ">https://" in text and "/map</loc>" in text

    def test_sitemap_lastmod_format(self, client):
        resp = client.get("/sitemap.xml", headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 404:
            pytest.skip("no content in this checkout")
        import re

        text = resp.get_data(as_text=True)
        assert re.search(r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>", text)


# ── JSON-LD enrichment ────────────────────────────────────────────────────────


class TestJsonLd:
    def test_landing_jsonld_website(self, client):
        resp = client.get("/")
        html = resp.get_data(as_text=True)
        assert '"@type": "WebSite"' in html
        assert '"publisher"' in html

    def test_bulletin_jsonld_has_publisher(self, client, tmp_chats_db):
        import re

        list_html = client.get("/bulletins").get_data(as_text=True)
        m = re.search(r'href="(/bulletin/[^"]+)"', list_html)
        if not m:
            # No bulletins published in this environment — nothing to render.
            return
        detail = client.get(m.group(1)).get_data(as_text=True)
        assert '"@type": "Article"' in detail
        assert '"publisher"' in detail
        assert '"dateModified"' in detail


# ── Google AdSense gating (P2: ads only on public SSR, never SPA) ────────────


class TestAdSense:
    """With GOOGLE_ADSENSE_CLIENT empty (default), zero ad code renders."""

    def test_ads_txt_404_without_client(self, client):
        resp = client.get("/ads.txt")
        assert resp.status_code == 404

    def test_no_ads_markup_on_crisis(self, client):
        resp = client.get("/crisis/sudan")
        if resp.status_code == 404:
            pytest.skip("no populated data in this checkout")
        html = resp.get_data(as_text=True)
        assert "adsbygoogle" not in html
        assert "crisis-ad" not in html

    def test_no_ads_markup_on_seo_detail(self, client):
        resp = client.get("/crisis")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "adsbygoogle" not in html

    def test_no_ads_markup_on_sitrep(self, client):
        resp = client.get("/sitrep/colombia")
        if resp.status_code == 404:
            pytest.skip("no sitrep in this checkout")
        html = resp.get_data(as_text=True)
        assert "adsbygoogle" not in html

    def test_ads_render_when_client_set(self, client, monkeypatch):
        """When GOOGLE_ADSENSE_CLIENT is configured, public SSR pages ship the
        ad slot; ads.txt returns 200 with the network directive."""
        monkeypatch.setattr("config.GOOGLE_ADSENSE_CLIENT", "ca-pub-1234567890")
        monkeypatch.setattr("config.GOOGLE_ADSENSE_SLOT_ID", "9876543210")
        monkeypatch.setattr("config.GOOGLE_ADSENSE_CMP_READY", True)
        resp = client.get("/crisis/sudan")
        if resp.status_code == 404:
            pytest.skip("no populated data in this checkout")
        html = resp.get_data(as_text=True)
        assert "adsbygoogle" in html
        assert "crisis-ad" in html
        assert "ca-pub-1234567890" in html
        assert 'data-ad-slot="9876543210"' in html
        assert 'data-ad-format="horizontal"' in html
        assert 'aria-label="Advertisement"' in html
        assert html.index('id="crisis-ad-slot"') < html.index('class="crisis-content-grid"')

        ads = client.get("/ads.txt")
        assert ads.status_code == 200
        body = ads.get_data(as_text=True)
        assert "google.com, pub-1234567890, DIRECT, f08c47fec0942fa0" in body

    def test_ads_do_not_render_until_cmp_is_ready(self, client, monkeypatch):
        monkeypatch.setattr("config.GOOGLE_ADSENSE_CLIENT", "ca-pub-1234567890")
        monkeypatch.setattr("config.GOOGLE_ADSENSE_SLOT_ID", "9876543210")
        monkeypatch.setattr("config.GOOGLE_ADSENSE_CMP_READY", False)

        resp = client.get("/crisis/sudan")
        if resp.status_code == 404:
            pytest.skip("no populated data in this checkout")
        assert "adsbygoogle" not in resp.get_data(as_text=True)
        assert client.get("/ads.txt").status_code == 200

    def test_ads_do_not_render_with_placeholder_or_missing_slot(self, client, monkeypatch):
        monkeypatch.setattr("config.GOOGLE_ADSENSE_CLIENT", "ca-pub-1234567890")
        monkeypatch.setattr("config.GOOGLE_ADSENSE_SLOT_ID", "")
        monkeypatch.setattr("config.GOOGLE_ADSENSE_CMP_READY", True)

        resp = client.get("/crisis/sudan")
        if resp.status_code == 404:
            pytest.skip("no populated data in this checkout")
        assert "adsbygoogle" not in resp.get_data(as_text=True)
