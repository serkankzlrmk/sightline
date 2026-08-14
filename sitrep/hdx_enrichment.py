"""
sitrep/hdx_enrichment.py
========================
HDX data enrichment for SITREP pipeline and weekly bulletin.

Fetches quantitative humanitarian data from HDX HAPI API
and formats it for injection into LLM prompts.

Used by:
- pipeline.py (Stage 1.5: fetch HDX context)
- weekly_bulletin.py (crisis summaries + key figures)
- rag_answers.py (quantitative context in RAG answers)
- executive_summary.py (key figures in executive summary)
- narrative_report.py (key figures in narrative)
"""

import logging
from typing import Any

logger = logging.getLogger("hdx_enrichment")


# ---------------------------------------------------------------------------
# Country name → ISO code
# ---------------------------------------------------------------------------

from reliefweb_api.country_codes import get_iso_code

# ---------------------------------------------------------------------------
# HDX data fetching
# ---------------------------------------------------------------------------


def fetch_hdx_context(country: str) -> dict[str, Any] | None:
    """
    Fetch HDX context data for a country.

    Uses the HDXClient singleton initialized in server.py.
    Falls back gracefully if HDX is not available.

    Args:
        country: Country name (e.g., "Sudan", "Syria")

    Returns:
        HDX context dict with 'summary' and 'data_sources' keys,
        or None if HDX is unavailable or country not found.
    """
    iso_code = get_iso_code(country)
    if not iso_code:
        logger.warning("HDX: No ISO code found for country '%s'", country)
        return None

    try:
        from reliefweb_api.hdx_tools import get_hdx_client

        client = get_hdx_client()
        if not client:
            logger.info("HDX: Client not initialized, skipping enrichment")
            return None

        context = client.get_sitrep_context_sync(iso_code)

        # Check if we got any useful data
        has_summary = bool(context.get("summary"))
        has_data = bool(context.get("data_sources"))

        if not has_summary and not has_data:
            logger.info("HDX: No data available for %s (%s)", country, iso_code)
            return None

        # Add country metadata
        context["country"] = country
        context["country_code"] = iso_code

        logger.info(
            "HDX: Enrichment data fetched for %s (%s) — summary keys: %s, data categories: %s",
            country,
            iso_code,
            list(context.get("summary", {}).keys()),
            list(context.get("data_sources", {}).keys()),
        )
        return context

    except Exception as exc:
        logger.warning("HDX: Failed to fetch context for %s: %s", country, exc)
        return None


# ---------------------------------------------------------------------------
# HDX data formatting for LLM prompts
# ---------------------------------------------------------------------------


def format_hdx_summary_for_prompt(hdx_context: dict[str, Any] | None) -> str:
    """
    Format HDX summary data for injection into an LLM prompt.

    Produces a concise, human-readable summary of key humanitarian figures
    that can be prepended to any SITREP/bulletin prompt.

    Args:
        hdx_context: Output from fetch_hdx_context(), or None

    Returns:
        Formatted string for LLM prompt, or empty string if no data.
    """
    if not hdx_context:
        return ""

    summary = hdx_context.get("summary", {})
    if not summary:
        return ""

    lines = []
    lines.append("## Quantitative Humanitarian Data (HDX)")
    lines.append(
        f"Source: Humanitarian Data Exchange (HDX) — country: {hdx_context.get('country', 'Unknown')} ({hdx_context.get('country_code', '??')})"
    )
    lines.append("")

    # Refugees
    if "refugees_total" in summary:
        val = summary["refugees_total"]
        if val and val > 0:
            lines.append(f"- **Total Refugees**: {val:,.0f}")

    # IDPs
    if "idps_total" in summary:
        val = summary["idps_total"]
        if val and val > 0:
            lines.append(f"- **Total IDPs (Internally Displaced)**: {val:,.0f}")

    # Funding
    if "funding_required_usd" in summary or "funding_funded_usd" in summary:
        required = summary.get("funding_required_usd", 0) or 0
        funded = summary.get("funding_funded_usd", 0) or 0
        if required > 0:
            pct = (funded / required * 100) if required > 0 else 0
            lines.append(f"- **Funding**: ${funded:,.0f} funded of ${required:,.0f} required ({pct:.1f}% funded)")

    # Risk
    if "risk_class" in summary:
        risk = summary["risk_class"]
        rank = summary.get("global_rank", "?")
        lines.append(f"- **INFORM Risk Class**: {risk} (Global Rank: {rank})")

    lines.append("")
    lines.append(
        "Use these figures to support your analysis. Always cite HDX as the source when referencing these numbers."
    )
    lines.append("")

    return "\n".join(lines)


def format_hdx_for_rag_context(hdx_context: dict[str, Any] | None) -> str:
    """
    Format HDX data as a numbered source for RAG answer context.

    This creates a "Source N" entry that can be appended to the
    retrieved context in rag_answers.py.

    Args:
        hdx_context: Output from fetch_hdx_context(), or None

    Returns:
        Formatted source text, or empty string if no data.
    """
    if not hdx_context:
        return ""

    data_sources = hdx_context.get("data_sources", {})
    if not data_sources:
        return ""

    lines = []
    lines.append("[HDX Quantitative Data]")
    lines.append(f"Country: {hdx_context.get('country', 'Unknown')} ({hdx_context.get('country_code', '??')})")
    lines.append("")

    for category, data in data_sources.items():
        if not data or not isinstance(data, dict):
            continue

        data.get("source", "HDX")
        record_count = data.get("record_count", 0)
        preview = data.get("data_preview", [])

        if record_count == 0:
            continue

        # Category label mapping
        category_labels = {
            "availability": "Data Availability",
            "refugees": "Refugees & Persons of Concern",
            "idps": "Internally Displaced Persons",
            "funding": "Humanitarian Funding",
            "conflict": "Conflict Events",
            "national_risk": "INFORM Risk Index",
            "population": "Baseline Population",
            "food_security": "Food Security (IPC)",
            "operational_presence": "Operational Presence",
        }

        label = category_labels.get(category, category.replace("_", " ").title())
        lines.append(f"### {label} ({record_count} records)")

        # Add preview data (first 3 records)
        for _i, record in enumerate(preview[:3]):
            if isinstance(record, dict):
                # Extract key fields based on category
                if category == "refugees":
                    pop = record.get("population", 0)
                    year = record.get("year", "?")
                    origin = record.get("origin_country_name", "?")
                    asylum = record.get("asylum_country_name", "?")
                    lines.append(f"  - {origin} → {asylum}: {pop:,.0f} persons ({year})")
                elif category == "idps":
                    pop = record.get("population", 0)
                    year = record.get("year", "?")
                    admin1 = record.get("admin1_name", "Unknown region")
                    lines.append(f"  - {admin1}: {pop:,.0f} IDPs ({year})")
                elif category == "funding":
                    req = record.get("requirements_usd", 0) or 0
                    fund = record.get("funding_usd", 0) or 0
                    plan = record.get("plan_name", "?")
                    lines.append(f"  - {plan}: ${fund:,.0f} funded / ${req:,.0f} required")
                elif category == "conflict":
                    events = record.get("events", 0)
                    fatalities = record.get("fatalities", 0)
                    year = record.get("year", "?")
                    admin1 = record.get("admin1_name", "?")
                    lines.append(f"  - {admin1}: {events} events, {fatalities} fatalities ({year})")
                elif category == "national_risk":
                    risk_class = record.get("risk_class", "?")
                    rank = record.get("global_rank", "?")
                    overall = record.get("overall_risk", "?")
                    lines.append(f"  - Risk class: {risk_class}, Global rank: {rank}, Overall risk: {overall}")
                else:
                    # Generic: show first 3 key-value pairs
                    kv_pairs = list(record.items())[:3]
                    kv_str = ", ".join(f"{k}: {v}" for k, v in kv_pairs)
                    lines.append(f"  - {kv_str}")

        lines.append("")

    lines.append("Source: Humanitarian Data Exchange (HDX) — https://data.humdata.org/")
    return "\n".join(lines)


def format_hdx_for_bulletin(hdx_context: dict[str, Any] | None) -> dict[str, Any]:
    """
    Format HDX data for inclusion in a weekly bulletin crisis entry.

    Returns a dict with:
    - key_figures: list of {label, value, icon} dicts for the bulletin
    - context_text: short text for the LLM crisis summary prompt
    - data_sources: raw data_sources dict for detailed view

    Args:
        hdx_context: Output from fetch_hdx_context(), or None

    Returns:
        Dict with key_figures, context_text, data_sources keys.
    """
    empty_result = {"key_figures": [], "context_text": "", "data_sources": {}}

    if not hdx_context:
        return empty_result

    summary = hdx_context.get("summary", {})
    data_sources = hdx_context.get("data_sources", {})

    if not summary and not data_sources:
        return empty_result

    key_figures = []
    context_parts = []

    # Refugees
    if "refugees_total" in summary:
        val = summary["refugees_total"]
        if val and val > 0:
            key_figures.append(
                {
                    "label": "Refugees",
                    "value": f"{val:,.0f}",
                    "icon": "people",
                }
            )
            context_parts.append(f"{val:,.0f} refugees")

    # IDPs
    if "idps_total" in summary:
        val = summary["idps_total"]
        if val and val > 0:
            key_figures.append(
                {
                    "label": "IDPs",
                    "value": f"{val:,.0f}",
                    "icon": "home",
                }
            )
            context_parts.append(f"{val:,.0f} internally displaced persons")

    # Funding
    required = summary.get("funding_required_usd", 0) or 0
    funded = summary.get("funding_funded_usd", 0) or 0
    if required > 0:
        pct = (funded / required * 100) if required > 0 else 0
        key_figures.append(
            {
                "label": "Funding",
                "value": f"{pct:.0f}% funded",
                "icon": "attach_money",
            }
        )
        context_parts.append(
            f"Humanitarian funding: ${funded / 1e6:.1f}M funded of ${required / 1e6:.1f}M required ({pct:.0f}%)"
        )

    # Risk
    if "risk_class" in summary:
        risk = summary["risk_class"]
        rank = summary.get("global_rank", "?")
        key_figures.append(
            {
                "label": "Risk Level",
                "value": f"{risk} (#{rank})",
                "icon": "warning",
            }
        )
        context_parts.append(f"INFORM risk class: {risk}, global rank: {rank}")

    # Operational presence — active organizations working in the country.
    # This is HDX's most widely-available dataset (present for far more
    # countries than refugees/funding), so it fills the gap on cards where
    # the quantitative figures above are missing.
    op_presence = (data_sources or {}).get("operational_presence", {})
    if isinstance(op_presence, dict) and op_presence.get("record_count", 0):
        org_names = set()
        for rec in op_presence.get("data_preview", []) or []:
            if not isinstance(rec, dict):
                continue
            org = rec.get("org_name") or rec.get("organization") or rec.get("name") or rec.get("org_acronym")
            if org:
                org_names.add(str(org))
        if org_names:
            org_list = sorted(org_names)[:6]
            key_figures.append(
                {
                    "label": "Active Orgs",
                    "value": f"{len(org_names)}",
                    "icon": "groups",
                    "orgs": org_list,
                }
            )
            context_parts.append(f"active organizations: {', '.join(org_list[:4])}")

    context_text = ""
    if context_parts:
        context_text = "HDX data: " + "; ".join(context_parts) + "."

    return {
        "key_figures": key_figures,
        "context_text": context_text,
        "data_sources": data_sources,
    }


def format_hdx_for_narrative(hdx_context: dict[str, Any] | None) -> str:
    """
    Format HDX data for injection into the narrative report prompt.

    Produces a "Key Quantitative Data" section that can be added
    between the executive summary and cluster summaries.

    Args:
        hdx_context: Output from fetch_hdx_context(), or None

    Returns:
        Formatted string for narrative prompt, or empty string.
    """
    if not hdx_context:
        return ""

    summary = hdx_context.get("summary", {})
    if not summary:
        return ""

    lines = []
    lines.append("## Key Quantitative Data (HDX)")
    lines.append(f"Country: {hdx_context.get('country', 'Unknown')} ({hdx_context.get('country_code', '??')})")
    lines.append("")

    # Build a structured data section
    data_items = []

    if "refugees_total" in summary:
        val = summary["refugees_total"]
        if val and val > 0:
            data_items.append(f"- **Total Refugees**: {val:,.0f}")

    if "idps_total" in summary:
        val = summary["idps_total"]
        if val and val > 0:
            data_items.append(f"- **Total IDPs**: {val:,.0f}")

    required = summary.get("funding_required_usd", 0) or 0
    funded = summary.get("funding_funded_usd", 0) or 0
    if required > 0:
        pct = (funded / required * 100) if required > 0 else 0
        data_items.append(f"- **Funding**: ${funded:,.0f} of ${required:,.0f} ({pct:.1f}%)")

    if "risk_class" in summary:
        risk = summary["risk_class"]
        rank = summary.get("global_rank", "?")
        data_items.append(f"- **INFORM Risk**: {risk} class, global rank #{rank}")

    if not data_items:
        return ""

    lines.extend(data_items)
    lines.append("")
    lines.append("Incorporate these figures into the report where relevant. Cite HDX as the source.")
    lines.append("")

    return "\n".join(lines)
