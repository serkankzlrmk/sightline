"""
blueprints/seo_bp.py — Server-rendered SEO surface for public content.

Why this exists: the JSON APIs (/api/public/*) are invisible to search
engines. These routes render the same content as HTML pages with per-page
meta tags, canonical URLs, JSON-LD, and a sitemap — so Googlebot (and
humans without JS) can read Sightline's bulletins, country summaries, and
SITREP reports.

Security notes:
- All LLM-derived HTML is sanitized server-side with bleach (the SPA does
  client-side sanitization; SSR pages have no JS sanitizer, so this is the
  only defense).
- Per-IP rate cap for these routes (they are NOT under the /api/* limiter);
  known crawler user-agents are exempt.
- Slugs never touch the filesystem directly: lookups go through the listing
  helpers and a slug→filename map; traversal is impossible by construction.
"""

import json
import logging
import re
import threading
import time
from urllib.parse import urlencode

import bleach
from flask import Blueprint, abort, render_template, request

from blueprints.helpers import _is_bot_user_agent, record_page_view
from config import (
    OUTPUT_REPORTS_DIR,
    SEO_RATE_LIMIT_PER_MIN,
    SEO_RATE_WINDOW_SECONDS,
    SITE_URL,
)

logger = logging.getLogger(__name__)

seo_bp = Blueprint("seo", __name__)

# ── Sanitization (server-side XSS defense — D7) ───────────────────────────────
# Allowlist for LLM-derived HTML. Everything else is stripped.
_ALLOWED_TAGS = [
    "a",
    "p",
    "strong",
    "em",
    "b",
    "i",
    "ul",
    "ol",
    "li",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "blockquote",
    "code",
    "pre",
    "hr",
]
_ALLOWED_ATTRS = {"a": ["href", "title"]}


def _sanitize_html(raw: str) -> str:
    """Strip anything outside the allowlist from LLM-derived HTML."""
    if not raw:
        return ""
    return bleach.clean(
        raw,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=["http", "https", "mailto"],
        strip=True,
    )


# ── Slug helpers ───────────────────────────────────────────────────────────────
_SUFFIXES = {"report", "bulletin", "summary"}


def slugify(stem: str) -> str:
    """Convert a filename stem to a URL-safe slug.

    lowercase; all separators → '-'; duplicate tokens collapsed;
    trailing report/bulletin/summary suffix removed.
    Examples: "Colombia_Colombia conflict_report" → "colombia-conflict"
              "2026-W31_bulletin" → "2026-w31"
    """
    s = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    parts = [p for p in s.split("-") if p]
    if parts and parts[-1] in _SUFFIXES:
        parts.pop()
    out = []
    for p in parts:
        if not out or out[-1] != p:
            out.append(p)
    return "-".join(out)


def safe_country_filename(name: str) -> str:
    """Mirror of sitrep.utils.safe_filename — alphanumeric/_/- only."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", name)


def _slugify_bulletin_filename(filename: str) -> str:
    return slugify(filename.rsplit(".", 1)[0])


def _bulletin_slug_map() -> dict[str, str]:
    """slug → filename for all bulletins. First-wins on collision."""
    from sitrep.weekly_bulletin import list_bulletins

    m: dict[str, str] = {}
    for b in list_bulletins():
        slug = _slugify_bulletin_filename(b["filename"])
        m.setdefault(slug, b["filename"])
    return m


def _country_slug_map() -> dict[str, str]:
    """slug → filename for all country summaries.

    Collisions are NOT silently resolved: the route 404s on a collided slug
    instead of picking one (D12). The map keeps first-wins; ambiguity is
    detectable because list_country_summaries yields unique countries.
    """
    from sitrep.country_summary import list_country_summaries

    m: dict[str, str] = {}
    for c in list_country_summaries():
        country = c.get("country", "")
        if not country:
            continue
        slug = slugify(country.replace(" ", "_"))
        m.setdefault(slug, f"{safe_country_filename(country)}.json")
    return m


def _sitrep_report_files() -> list[tuple[str, str]]:
    """[(filename, slug)] for real report JSONs, test artifacts excluded.

    Rule (D8): exclude stems containing '_test' or 'test_' only.
    8-hex-filtered reports (e.g. Syria_..._654573c0) are legit filtered
    runs and stay — they are exactly the content this surface exists for.
    """
    out = []
    if not OUTPUT_REPORTS_DIR.exists():
        return out
    for f in sorted(
        OUTPUT_REPORTS_DIR.glob("*report.json"),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    ):
        stem = f.stem
        if "_test" in stem or "test_" in stem:
            continue
        out.append((f.name, slugify(stem)))
    return out


def _country_sitrep_filename(country: str) -> str:
    """Return the newest SITREP filename whose stable prefix is the country."""
    names = [country, _CRISIS_ALIASES.get(country, country)]
    prefixes = {
        safe_country_filename(name).strip("_").lower()
        for name in names
        if name
    }
    for filename, _slug in _sitrep_report_files():
        stem = filename.rsplit(".", 1)[0].lower()
        if any(stem == prefix or stem.startswith(f"{prefix}_") for prefix in prefixes):
            return filename
    return ""


# ── Per-IP rate cap (D13) ─────────────────────────────────────────────────────
_seo_rate_lock = threading.Lock()
_seo_rate_counts: dict[str, list[float]] = {}  # ip → [window_start, hits]


def _seo_rate_allowed(ip: str, user_agent: str) -> bool:
    """Per-IP cap for SEO routes; crawlers (and missing UA) are exempt."""
    if _is_bot_user_agent(user_agent):
        return True
    now = time.time()
    with _seo_rate_lock:
        entry = _seo_rate_counts.get(ip)
        if not entry or now - entry[0] > SEO_RATE_WINDOW_SECONDS:
            entry = [now, 0]
            _seo_rate_counts[ip] = entry
        entry[1] += 1
        if entry[1] > SEO_RATE_LIMIT_PER_MIN:
            return False
        if len(_seo_rate_counts) > 5000:
            stale = [k for k, v in _seo_rate_counts.items() if now - v[0] > SEO_RATE_WINDOW_SECONDS]
            for k in stale:
                del _seo_rate_counts[k]
        return True


def _seo_rate_guard():
    """before_request for SEO routes: 429 when a real visitor exceeds the cap."""
    if not _seo_rate_allowed(request.remote_addr or "", request.headers.get("User-Agent", "")):
        abort(429)


seo_bp.before_request(_seo_rate_guard)


# ── Render caches (D13) ───────────────────────────────────────────────────────
_bulletin_cache: dict[str, tuple[float, str]] = {}
_sitemap_cache: dict[str, tuple[float, str]] = {}
_BULLETIN_CACHE_TTL = 300
_SITEMAP_CACHE_TTL = 3600


def _cached(key: str, cache: dict, ttl: int, builder) -> str:
    now = time.time()
    hit = cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    rendered = builder()
    cache[key] = (now, rendered)
    return rendered


# ── Render helpers ─────────────────────────────────────────────────────────────
def _render_detail(title: str, description: str, path: str, body_html: str, json_ld: dict) -> str:
    from config import GOOGLE_ADSENSE_CLIENT, GOOGLE_ANALYTICS_ID

    return render_template(
        "seo_detail.html",
        page_title=title,
        page_description=description,
        canonical=f"{SITE_URL}/{path}",
        body_html=body_html,
        json_ld=json.dumps(json_ld, ensure_ascii=False),
        analytics_id=GOOGLE_ANALYTICS_ID,
        adsense_client=GOOGLE_ADSENSE_CLIENT,
    )


def _render_list(title: str, description: str, items: list[dict], path: str) -> str:
    from config import GOOGLE_ADSENSE_CLIENT, GOOGLE_ANALYTICS_ID

    return render_template(
        "seo_list.html",
        page_title=title,
        page_description=description,
        canonical=f"{SITE_URL}/{path}",
        items=items,
        analytics_id=GOOGLE_ANALYTICS_ID,
        adsense_client=GOOGLE_ADSENSE_CLIENT,
    )


# =============================================================================
# ROUTES — Bulletins
# =============================================================================


@seo_bp.route("/bulletins")
def bulletin_list():
    """List of all weekly bulletins (HTML)."""
    from sitrep.weekly_bulletin import list_bulletins

    record_page_view("/bulletins", request.headers.get("User-Agent", ""))
    items = [
        {
            "url": f"/bulletin/{_slugify_bulletin_filename(b['filename'])}",
            "title": b.get("week_label") or b["filename"],
            "subtitle": (f"{b.get('week_start', '')} — {b.get('week_end', '')} · {b.get('total_reports', 0)} reports"),
        }
        for b in list_bulletins()
    ]
    return _render_list(
        "Weekly Humanitarian Bulletins",
        "Weekly humanitarian situation bulletins generated by Sightline from ReliefWeb, HDX and GDACS.",
        items,
        "bulletins",
    )


@seo_bp.route("/bulletin/<slug>")
def bulletin_detail(slug: str):
    from blueprints.public_bp import _trim_bulletin_for_preview
    from sitrep.weekly_bulletin import get_bulletin

    def _render() -> str:
        filename = _bulletin_slug_map().get(slug)
        if not filename:
            abort(404)
        bulletin = get_bulletin(filename)
        if bulletin is None:
            abort(404)
        trimmed = _trim_bulletin_for_preview(bulletin)
        title = trimmed.get("week_label") or filename
        sections = []
        if trimmed.get("global_overview"):
            sections.append(f"<h2>Global Overview</h2><p>{_sanitize_html(trimmed['global_overview'])}</p>")
        for crisis in trimmed.get("crises", []):
            c_title = _sanitize_html(crisis.get("headline", "Crisis"))
            c_summary = _sanitize_html(crisis.get("summary", ""))
            sections.append(f"<h3>{c_title}</h3><p>{c_summary}</p>")
        json_ld = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": title,
            "datePublished": trimmed.get("generated_at", ""),
            "dateModified": trimmed.get("generated_at", ""),
            "description": f"Weekly humanitarian bulletin: {trimmed.get('week_label') or title}.",
            "mainEntityOfPage": f"{SITE_URL}/bulletin/{slug}",
            "author": {"@type": "Organization", "name": "Sightline"},
            "publisher": {"@type": "Organization", "name": "Sightline"},
            "image": f"{SITE_URL}/static/logo-signal-horizon.png",
        }
        return _render_detail(
            title,
            f"Weekly humanitarian bulletin: {trimmed.get('week_label') or title}.",
            f"bulletin/{slug}",
            "".join(sections),
            json_ld,
        )

    return _cached(f"bulletin:{slug}", _bulletin_cache, _BULLETIN_CACHE_TTL, _render)


# =============================================================================
# ROUTES — Countries
# =============================================================================


@seo_bp.route("/countries")
def country_list():
    from sitrep.country_summary import list_country_summaries

    record_page_view("/countries", request.headers.get("User-Agent", ""))
    items = []
    for c in list_country_summaries():
        country = c.get("country", "")
        if not country:
            continue
        items.append(
            {
                "url": f"/country/{slugify(safe_country_filename(country))}",
                "title": country,
                "subtitle": f"{c.get('severity', '')} · {c.get('report_count', 0)} reports",
            }
        )
    return _render_list(
        "Country Intelligence Summaries",
        "Humanitarian intelligence cards per country: severity, reports, themes, HDX figures.",
        items,
        "countries",
    )


@seo_bp.route("/country/<slug>")
def country_detail(slug: str):
    """Full country card rendered server-side (D10: map endpoint already public)."""
    from sitrep.country_summary import get_country_summary

    filename = _country_slug_map().get(slug)
    if not filename:
        abort(404)
    summary = get_country_summary(filename[:-5])  # strip ".json"
    if summary is None:
        abort(404)
    record_page_view(f"/country/{slug}", request.headers.get("User-Agent", ""))
    country = summary.get("country", slug)
    sections = []
    headline = _sanitize_html(summary.get("headline", ""))
    if headline:
        sections.append(f"<h2>Headline</h2><p>{headline}</p>")
    narrative = _sanitize_html(summary.get("narrative") or "")
    if narrative:
        sections.append(f"<h2>Narrative</h2><p>{narrative}</p>")
    themes = summary.get("top_themes") or []
    if themes:
        chips = "".join(f"<li>{_sanitize_html(str(t))}</li>" for t in themes)
        sections.append(f"<h2>Top Themes</h2><ul>{chips}</ul>")
    alerts = summary.get("gdacs_alerts") or []
    for alert in alerts:
        alert_title = _sanitize_html(str(alert.get("title", "Alert")))
        sections.append(f"<h3>{alert_title}</h3>")
    json_ld = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": f"{country} — Humanitarian Intelligence Summary",
        "description": f"Aggregated humanitarian indicators for {country}",
        "url": f"{SITE_URL}/country/{slug}",
    }
    return _render_detail(
        f"{country} — Country Intelligence",
        f"Humanitarian situation summary for {country}: severity, reports, themes.",
        f"country/{slug}",
        "".join(sections),
        json_ld,
    )


# =============================================================================
# ROUTES — SITREP reports
# =============================================================================


@seo_bp.route("/sitrep/<slug>")
def sitrep_detail(slug: str):
    """JSON-rendered SITREP page (no markdown dependency — D2)."""
    files = _sitrep_report_files()
    match = [f for f in files if f[1] == slug]
    if not match:
        abort(404)
    filename = match[0][0]
    try:
        with open(OUTPUT_REPORTS_DIR / filename, encoding="utf-8") as fh:
            report = json.load(fh)
    except Exception:
        abort(404)
    record_page_view(f"/sitrep/{slug}", request.headers.get("User-Agent", ""))
    title = report.get("title") or filename
    narrative = _sanitize_html(report.get("narrative_html") or report.get("narrative") or "")
    sections = f"<h2>Report</h2>{narrative}" if narrative else "<p>No narrative available.</p>"
    generated_at = report.get("generated_at") or report.get("date", "")
    json_ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "datePublished": generated_at if generated_at else None,
        "description": f"Humanitarian situation report: {title}.",
        "mainEntityOfPage": f"{SITE_URL}/sitrep/{slug}",
        "author": {"@type": "Organization", "name": "Sightline"},
        "publisher": {"@type": "Organization", "name": "Sightline"},
        "image": f"{SITE_URL}/static/logo-signal-horizon.png",
    }
    json_ld = {k: v for k, v in json_ld.items() if v is not None}
    return _render_detail(
        title,
        f"Humanitarian situation report: {title}.",
        f"sitrep/{slug}",
        sections,
        json_ld,
    )


# =============================================================================
# ROUTES — Crisis (Programmatic per-country pages, P2 real-data gate)
# =============================================================================

_CRISIS_PUBLISH_MIN_REPORTS = 3  # P2 publish predicate: report_count >= N OR live GDACS alert

# Country name variants → canonical English name for slug consistency
# (mirrors the alias table in public_bp.api_map_countries).
_CRISIS_ALIASES = {
    "Syrian Arab Republic": "Syria",
    "Türkiye": "Turkey",
    "Iran (Islamic Republic of)": "Iran",
    "Democratic Republic of the Congo": "DR Congo",
    "occupied Palestinian territory": "Palestine",
}


def _crisis_slug(country: str) -> str:
    """Stable URL slug for a country (English canonical name → hyphenated)."""
    name = _CRISIS_ALIASES.get(country, country)
    return slugify(name.replace(" ", "_"))


def _crisis_country_data() -> list[dict]:
    """Country data for /crisis pages — reuses the public map endpoint so the
    data shape and caching stay in one place (no ChromaDB access here)."""
    from blueprints.public_bp import api_map_countries

    try:
        result = api_map_countries()
        resp = result[0] if isinstance(result, tuple) else result
        data = resp.get_json()
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _crisis_page(slug: str, allow_noindex: bool = False):
    """Build a /crisis/<slug> SSR page. Returns (html, status) — 404 when the
    country is unknown; noindex only when below the publish predicate (and the
    route explicitly opts in, so crawlers only see the meta tag on thin pages,
    never on the real ones)."""
    from sitrep.country_summary import _country_to_iso3

    data = _crisis_country_data()
    entry = next((c for c in data if _crisis_slug(c.get("country", "")) == slug), None)
    if entry is None:
        abort(404)
    country = entry.get("country", "")
    iso3 = _country_to_iso3(country) or entry.get("iso3") or ""
    count = entry.get("report_count", 0) or 0

    # Live GDACS alerts for this country (from the same cached payload)
    gdacs = entry.get("gdacs_alerts") or []
    by_level = {
        str(a.get("alert_level", "")).lower(): a
        for a in gdacs if isinstance(a, dict)
    }
    alert_levels = sorted(by_level, key=lambda lv: ["green", "orange", "red"].index(lv) if lv in ("green", "orange", "red") else 99)
    has_live_alert = any(lv in ("orange", "red") for lv in by_level)

    published = count >= _CRISIS_PUBLISH_MIN_REPORTS or has_live_alert
    noindex = allow_noindex and not published

    map_url = f"/app?{urlencode({'country': country})}#crisis-map"
    sitrep_filename = _country_sitrep_filename(country) if entry.get("has_sitrep") else ""
    sitrep_params = {"country": country}
    if sitrep_filename:
        sitrep_params["report"] = sitrep_filename
    sitrep_url = f"/app?{urlencode(sitrep_params)}#sitrep"
    summary_url = f"/country/{slugify(safe_country_filename(country))}"

    # Hero badges: real data only (P2). Availability badges link directly
    # to the matching country context instead of a generic destination.
    badges = []
    if by_level:
        for lv in alert_levels:
            badge_cls = {"green": "crisis-badge-green", "orange": "crisis-badge-orange", "red": "crisis-badge-red"}.get(lv, "crisis-badge-neutral")
            evt = by_level[lv].get("event_type", "")
            suffix = f" ({_sanitize_html(str(evt))})" if evt else ""
            badges.append(f'<span class="crisis-badge {badge_cls}">{lv.title()} alert{suffix}</span>')
    elif has_live_alert:
        badges.append('<span class="crisis-badge crisis-badge-red">Live alert</span>')
    if count:
        reports_target = "#recent-reports" if entry.get("recent_reports") else map_url
        badges.append(f'<a class="crisis-badge crisis-badge-blue" href="{reports_target}">{count} reports</a>')
    if entry.get("has_summary"):
        badges.append(f'<a class="crisis-badge crisis-badge-blue" href="{summary_url}">Country summary</a>')
    if entry.get("has_sitrep"):
        badges.append(f'<a class="crisis-badge crisis-badge-blue" href="{sitrep_url}">Sitrep available</a>')
    hero_badges = f'<div class="crisis-badges">{"".join(badges)}</div>' if badges else ""

    # Hero enrichment: headline + narrative (real data — P2). These are the
    # exact strings Google surfaces in snippets, so they stay factual.
    headline = _sanitize_html(str(entry.get("headline") or ""))
    narrative = _sanitize_html(str(entry.get("narrative") or ""))
    hero_extra = ""
    if headline:
        hero_extra += f'<p class="crisis-headline">{headline}</p>'
    if narrative:
        hero_extra += f'<p class="crisis-narrative">{narrative}</p>'

    # Sections (real data only — P2; per-source failure → "Data pending" card)
    headlines = entry.get("top_themes") or []
    recent = entry.get("recent_reports") or []
    figures = entry.get("hdx_key_figures") or []
    as_of = (entry.get("last_updated") or entry.get("generated_at") or time.strftime("%Y-%m-%d"))
    if isinstance(as_of, str) and len(as_of) > 10:
        as_of = as_of[:10]

    parts = []
    if gdacs:
        lis = []
        for a in gdacs[:5]:
            level = str(a.get("alert_level", "")).lower()
            level_class = level if level in ("green", "orange", "red") else "neutral"
            level_label = _sanitize_html(str(a.get("alert_level", "Alert")))
            lis.append(f'<li><span class="crisis-alert-level crisis-alert-level-{level_class}">{level_label}</span>{_sanitize_html(str(a.get("title", "")))}</li>')
        parts.append(f'<section class="crisis-card" aria-labelledby="current-alerts"><h2 id="current-alerts">Current alerts</h2><ul>{"".join(lis)}</ul></section>')
    if recent:
        lis = []
        for r in recent[:5]:
            src = str(r.get("source", ""))
            lis.append(f'<li class="crisis-reports"><a href="{_sanitize_html(str(r.get("url", "#")))}">{_sanitize_html(str(r.get("title", "")))}</a> <span class="crisis-report-source">({_sanitize_html(src)})</span></li>')
        parts.append(f'<section class="crisis-card" aria-labelledby="recent-reports"><h2 id="recent-reports">Recent reports</h2><ul>{"".join(lis)}</ul></section>')
    if figures:
        items = "".join(
            f'<div class="crisis-figure"><strong>{_sanitize_html(str(f.get("value", "")))}</strong><span>{_sanitize_html(str(f.get("label", "")))}</span></div>'
            for f in figures[:6]
        )
        parts.append(f'<section class="crisis-card" aria-labelledby="key-figures"><h2 id="key-figures">Key figures</h2><div class="crisis-figures">{items}</div></section>')
    if headlines:
        chips = "".join(f'<span class="crisis-theme">{_sanitize_html(str(h))}</span>' for h in headlines[:8])
        parts.append(f'<section class="crisis-card" aria-labelledby="themes"><h2 id="themes">Themes</h2><div class="crisis-themes">{chips}</div></section>')

    # Top sources: who reports on this country (real data — trust signal)
    sources = entry.get("top_sources") or []
    if sources:
        src_chips = "".join(
            f'<span class="crisis-theme">{_sanitize_html(str(s.get("name", "")))} · {_sanitize_html(str(s.get("count", "")))}</span>'
            for s in sources[:6]
        )
        parts.append(f'<section class="crisis-card" aria-labelledby="top-sources"><h2 id="top-sources">Top sources</h2><div class="crisis-themes">{src_chips}</div></section>')

    # Coverage window — factual freshness line (only when date_range exists)
    dr = entry.get("date_range") or {}
    lo, hi = dr.get("min_date"), dr.get("max_date")
    if lo and hi:
        hero_extra += f'<p class="crisis-asof">Reports from {_sanitize_html(str(lo))} to {_sanitize_html(str(hi))}</p>'

    # Related: country summary + bulletins (internal linking for Google crawl)
    rel = []
    if entry.get("has_summary") and _country_slug_map().get(slug):
        rel.append(f'<li><a href="/country/{slug}">Country summary for {_sanitize_html(country)}</a></li>')
    for bs in list(_bulletin_slug_map())[:3]:
        rel.append(f'<li><a href="/bulletin/{bs}">Weekly bulletin</a></li>')
    if rel:
        parts.append(f'<section class="crisis-card" aria-labelledby="related"><h2 id="related">Related</h2><ul>{"".join(rel)}</ul></section>')

    if not parts:
        parts.append('<section class="crisis-card"><p class="crisis-pending">Data pending. Latest information will appear here as sources update.</p></section>')
    body_html = "".join(parts)

    title = f"{country}: live crisis overview"
    description = f"Live humanitarian overview for {country}: latest reports, alerts and key figures from trusted sources."
    json_ld = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": f"Sightline: {country} crisis data",
        "description": description,
        "datePublished": time.strftime("%Y-%m-%d"),
        "mainEntityOfPage": f"{SITE_URL}/crisis/{slug}",
        "publisher": {"@type": "Organization", "name": "Sightline"},
    }
    if noindex:
        json_ld["url"] = f"{SITE_URL}/crisis/{slug}"

    from config import GOOGLE_ADSENSE_CLIENT, GOOGLE_ANALYTICS_ID

    html = render_template(
        "crisis_detail.html",
        page_title=title,
        page_description=description,
        canonical=f"{SITE_URL}/crisis/{slug}",
        body_html=body_html,
        hero_badges=hero_badges,
        hero_extra=hero_extra,
        map_url=map_url,
        sitrep_url=sitrep_url,
        as_of=as_of,
        json_ld=json.dumps(json_ld, ensure_ascii=False),
        analytics_id=GOOGLE_ANALYTICS_ID,
        adsense_client=GOOGLE_ADSENSE_CLIENT,
    )
    if noindex:
        html = html.replace("<head>", '<head><meta name="robots" content="noindex">', 1)
    return html


@seo_bp.route("/crisis/<slug>")
def crisis_detail(slug: str):
    """Programmatic per-country crisis page (P2: real data only)."""
    record_page_view(f"/crisis/{slug}", request.headers.get("User-Agent", ""))
    return _crisis_page(slug, allow_noindex=True)


@seo_bp.route("/crisis")
def crisis_index():
    """SSR index of all publishable /crisis pages — link hub for visitors and
    crawlers; links to each country page with its report count."""
    data = _crisis_country_data()
    items = []
    for c in data:
        country = c.get("country", "")
        c_slug = _crisis_slug(country)
        if not c_slug:
            continue
        count = c.get("report_count", 0) or 0
        gdacs = c.get("gdacs_alerts") or []
        has_alert = any(
            str(a.get("alert_level", "")).lower() in ("orange", "red")
            for a in gdacs if isinstance(a, dict)
        )
        if count < _CRISIS_PUBLISH_MIN_REPORTS and not has_alert:
            continue
        items.append({
            "url": f"/crisis/{c_slug}",
            "title": f"{country} — live crisis overview",
            "subtitle": f"{count} reports" + (" · live alert" if has_alert else ""),
        })
    items.sort(key=lambda x: x["subtitle"], reverse=True)
    record_page_view("/crisis", request.headers.get("User-Agent", ""))
    return _render_list(
        "Crisis overviews — live humanitarian country pages",
        "Per-country live crisis overviews: reports, alerts and key figures from trusted sources.",
        items,
        "crisis",
    )


# =============================================================================
# ROUTES — Crisis Map (SSR)
# =============================================================================


def _map_countries_ssr() -> list[dict]:
    """Top-60 country list for the SSR map page.

    Reuses the public /api/map/countries response so caching and data shape
    stay in one place (no ChromaDB access from this surface).
    """
    from blueprints.public_bp import api_map_countries

    try:
        result = api_map_countries()
        # Route funcs may return (Response, status) tuples — unwrap safely.
        resp = result[0] if isinstance(result, tuple) else result
        data = resp.get_json()
    except Exception:
        return []
    return data if isinstance(data, list) else []


@seo_bp.route("/map")
def crisis_map():
    """SSR crisis map page: country grid with severity + report counts."""
    record_page_view("/map", request.headers.get("User-Agent", ""))

    def _render() -> str:
        from config import GOOGLE_ANALYTICS_ID

        countries = _map_countries_ssr()
        cards = []
        for c in countries:
            name = c.get("country") or c.get("name", "")
            if not name:
                continue
            cards.append(
                {
                    "name": name,
                    "severity": c.get("severity", ""),
                    "count": c.get("report_count", 0),
                    "headline": (c.get("headline") or "")[:160],
                    "url": f"/country/{slugify(safe_country_filename(name))}",
                }
            )
        cards.sort(key=lambda x: x["count"], reverse=True)
        return render_template(
            "map_ssr.html",
            page_title="Humanitarian Crisis Map — Sightline",
            page_description=(
                "Live humanitarian crisis map: 60 countries ranked by ReliefWeb "
                "report volume, severity, and displacement data from HDX and GDACS."
            ),
            canonical=f"{SITE_URL}/map",
            countries=cards,
            analytics_id=GOOGLE_ANALYTICS_ID,
        )

    return _cached("map", _bulletin_cache, _BULLETIN_CACHE_TTL, _render)


# =============================================================================
# ROUTES — sitemap + robots
# =============================================================================


def _lastmod(path) -> str:
    """YYYY-MM-DD mtime of a content file; falls back to today on any error."""
    try:
        return time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime))
    except OSError:
        return time.strftime("%Y-%m-%d")


def _sitemap_builder() -> str:
    from sitrep.country_summary import COUNTRY_SUMMARY_DIR
    from sitrep.weekly_bulletin import BULLETINS_DIR

    today = time.strftime("%Y-%m-%d")
    # (url, lastmod) pairs — static roots use today, content pages use the
    # underlying file's mtime so Search Console doesn't see stale dates.
    urls: list[tuple[str, str]] = [
        (f"{SITE_URL}/", today),
        (f"{SITE_URL}/bulletins", today),
        (f"{SITE_URL}/countries", today),
        (f"{SITE_URL}/map", today),
        (f"{SITE_URL}/crisis", today),
    ]
    for slug, filename in _bulletin_slug_map().items():
        urls.append((f"{SITE_URL}/bulletin/{slug}", _lastmod(BULLETINS_DIR / filename)))
    for slug, filename in _country_slug_map().items():
        urls.append((f"{SITE_URL}/country/{slug}", _lastmod(COUNTRY_SUMMARY_DIR / filename)))
    for fname, slug in _sitrep_report_files():
        urls.append((f"{SITE_URL}/sitrep/{slug}", _lastmod(OUTPUT_REPORTS_DIR / fname)))
    # /crisis/<slug> — only countries passing the P2 publish predicate
    # (report_count >= 3 OR live orange/red alert) enter the sitemap;
    # below-threshold pages stay noindex and are excluded here.
    for c in _crisis_country_data():
        c_slug = _crisis_slug(c.get("country", ""))
        if not c_slug:
            continue
        count = c.get("report_count", 0) or 0
        gdacs = c.get("gdacs_alerts") or []
        has_alert = any(
            str(a.get("alert_level", "")).lower() in ("orange", "red")
            for a in gdacs if isinstance(a, dict)
        )
        if count >= _CRISIS_PUBLISH_MIN_REPORTS or has_alert:
            urls.append((f"{SITE_URL}/crisis/{c_slug}", today))
    if len(urls) <= 3:
        # An empty sitemap violates the protocol and triggers Search Console
        # errors — serve 404 instead (D16).
        abort(404)
    entries = "".join(f"<url><loc>{u}</loc><lastmod>{lm}</lastmod></url>" for u, lm in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</urlset>"
    )


@seo_bp.route("/sitemap.xml")
def sitemap_xml():
    record_page_view("/sitemap.xml", request.headers.get("User-Agent", ""))
    body = _cached("sitemap", _sitemap_cache, _SITEMAP_CACHE_TTL, _sitemap_builder)
    return body, 200, {"Content-Type": "application/xml; charset=utf-8"}


@seo_bp.route("/robots.txt")
def robots_txt():
    return (
        f"User-agent: *\nAllow: /\nDisallow: /app\nSitemap: {SITE_URL}/sitemap.xml\n",
        200,
        {"Content-Type": "text/plain; charset=utf-8"},
    )


@seo_bp.route("/ads.txt")
def ads_txt():
    """AdSense ownership verification file. 404 until a publisher ID is
    configured — empty env means no ads and no ads.txt (safe default)."""
    from config import GOOGLE_ADSENSE_CLIENT

    if not GOOGLE_ADSENSE_CLIENT:
        abort(404)
    pub_id = GOOGLE_ADSENSE_CLIENT.replace("ca-pub-", "")
    # Format: <ad-network>, <publisher-id>, DIRECT, <certification-id>
    return (
        f"google.com, {pub_id}, DIRECT, f08c47fec0942fa0\n",
        200,
        {"Content-Type": "text/plain; charset=utf-8"},
    )
