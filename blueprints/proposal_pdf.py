"""Server-side proposal PDF renderer.

Structured proposal data is rendered directly into ReportLab tables instead of
passing through Markdown and the browser print engine. This keeps financial and
logical-framework tables readable and allows headers to repeat across pages.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_NAVY = colors.HexColor("#0f172a")
_RED = colors.HexColor("#e8364e")
_MUTED = colors.HexColor("#64748b")
_LIGHT = colors.HexColor("#f8fafc")
_BORDER = colors.HexColor("#cbd5e1")


def _load(value: Any, default: Any) -> Any:
    if value in (None, "", "{}", "[]", "null"):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _text(value: Any, fallback: str = "-") -> str:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    value = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"\s+", " ", value).strip() or fallback


def _markdown_blocks(value: Any) -> list[str]:
    """Return readable paragraphs from narrative text or {content, sources}."""
    data = _load(value, "")
    if isinstance(data, dict) and "content" in data:
        data = data["content"]
    elif isinstance(data, str) and data.lstrip().startswith("{"):
        # Older LLM generations occasionally saved a JSON-shaped response
        # with literal newlines inside its content string, making strict JSON
        # parsing impossible. Extract its document body instead of printing
        # that transport wrapper in the PDF.
        match = re.search(
            r'"content"\s*:\s*"(.*?)(?="\s*,\s*"sources"|"\s*}\s*$)',
            data,
            flags=re.DOTALL,
        )
        if match:
            data = match.group(1).replace("\\n", "\n").replace('\\"', '"')
    if not isinstance(data, str):
        return []
    cleaned = re.sub(r"^#{1,6}\s*", "", data, flags=re.MULTILINE)
    cleaned = cleaned.replace("**", "").replace("`", "")
    return [_text(part, "") for part in re.split(r"\n\s*\n", cleaned) if part.strip()]


def _register_fonts() -> tuple[str, str]:
    regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if Path(regular).exists() and Path(bold).exists():
        if "ProposalSans" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("ProposalSans", regular))
            pdfmetrics.registerFont(TTFont("ProposalSans-Bold", bold))
        return "ProposalSans", "ProposalSans-Bold"
    return "Helvetica", "Helvetica-Bold"


def _table(rows: list[list[Any]], widths: list[float], styles: dict[str, ParagraphStyle]) -> Table:
    prepared = []
    for index, row in enumerate(rows):
        style = styles["table_head"] if index == 0 else styles["table_cell"]
        prepared.append([Paragraph(_text(cell), style) for cell in row])
    table = Table(prepared, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, _BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row_index in range(1, len(rows)):
        if row_index % 2 == 0:
            commands.append(("BACKGROUND", (0, row_index), (-1, row_index), _LIGHT))
    table.setStyle(TableStyle(commands))
    return table


def _page_header_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(_RED)
    canvas.setLineWidth(1.1)
    canvas.line(doc.leftMargin, A4[1] - 12 * mm, A4[0] - doc.rightMargin, A4[1] - 12 * mm)
    canvas.setFont("ProposalSans" if "ProposalSans" in pdfmetrics.getRegisteredFontNames() else "Helvetica", 7)
    canvas.setFillColor(_MUTED)
    canvas.drawString(doc.leftMargin, 9 * mm, "Sightline Advisor Studio - Confidential operational proposal")
    canvas.drawRightString(A4[0] - doc.rightMargin, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_proposal_pdf(proposal: dict[str, Any]) -> io.BytesIO:
    """Build a donor-ready PDF in memory and return its bytes buffer."""
    regular, bold = _register_fonts()
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "cover_title",
            parent=styles["Title"],
            fontName=bold,
            fontSize=25,
            leading=31,
            textColor=_NAVY,
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            "cover_label",
            parent=styles["Normal"],
            fontName=bold,
            fontSize=8,
            leading=10,
            textColor=_RED,
            uppercase=True,
            spaceAfter=7,
        )
    )
    styles.add(
        ParagraphStyle(
            "section",
            parent=styles["Heading2"],
            fontName=bold,
            fontSize=13,
            leading=17,
            textColor=_NAVY,
            spaceBefore=14,
            spaceAfter=8,
        )
    )
    # Proposal narratives use full justification for a conventional donor
    # document rhythm. Tables intentionally stay left aligned for scanability.
    styles.add(
        ParagraphStyle(
            "body",
            parent=styles["BodyText"],
            fontName=regular,
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#334155"),
            alignment=TA_JUSTIFY,
            spaceAfter=7,
        )
    )
    styles.add(
        ParagraphStyle(
            "table_head",
            parent=styles["Normal"],
            fontName=bold,
            fontSize=6.8,
            leading=8,
            textColor=colors.white,
            alignment=TA_LEFT,
        )
    )
    styles.add(
        ParagraphStyle(
            "table_cell",
            parent=styles["Normal"],
            fontName=regular,
            fontSize=7.2,
            leading=9,
            textColor=colors.HexColor("#1e293b"),
        )
    )
    styles.add(
        ParagraphStyle("meta", parent=styles["Normal"], fontName=regular, fontSize=9, leading=13, textColor=_NAVY)
    )
    styles.add(
        ParagraphStyle(
            "source",
            parent=styles["Normal"],
            fontName=regular,
            fontSize=7.5,
            leading=10,
            textColor=_MUTED,
            leftIndent=4 * mm,
            spaceAfter=3,
        )
    )

    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=19 * mm,
        bottomMargin=17 * mm,
        title=_text(proposal.get("title"), "Proposal"),
    )
    story: list[Any] = []

    # Cover page
    story.append(Spacer(1, 30 * mm))
    story.append(Paragraph("HUMANITARIAN ACTION PROPOSAL", styles["cover_label"]))
    story.append(Paragraph(_text(proposal.get("title"), "Untitled proposal"), styles["cover_title"]))
    cover_rows = [
        [
            Paragraph("COUNTRY OF OPERATION", styles["cover_label"]),
            Paragraph(_text(proposal.get("country")), styles["meta"]),
        ],
        [Paragraph("TARGET DONOR", styles["cover_label"]), Paragraph(_text(proposal.get("donor")), styles["meta"])],
        [Paragraph("CRISIS / FOCUS", styles["cover_label"]), Paragraph(_text(proposal.get("event")), styles["meta"])],
    ]
    cover = Table(cover_rows, colWidths=[45 * mm, 120 * mm], hAlign="LEFT")
    cover.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.5, _BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, _BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.extend([Spacer(1, 18 * mm), cover, PageBreak()])

    def heading(label: str):
        story.append(Paragraph(label, styles["section"]))

    section_sources = _load(proposal.get("section_sources"), {})
    if not isinstance(section_sources, dict):
        section_sources = {}

    def append_sources(step: str):
        sources = section_sources.get(step, [])
        if not isinstance(sources, list) or not sources:
            return
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("Sources", styles["cover_label"]))
        for number, source in enumerate(sources[:12], 1):
            if not isinstance(source, dict):
                continue
            url = str(source.get("url") or "").strip()
            title = xml_escape(str(source.get("title") or url or f"Source {number}"))
            if url.startswith(("https://", "http://")):
                story.append(
                    Paragraph(
                        f'<link href="{xml_escape(url, {'"': "&quot;"})}" color="#1d4ed8">[{number}] {title}</link>',
                        styles["source"],
                    )
                )
            else:
                story.append(Paragraph(f"[{number}] {title}", styles["source"]))

    for title, field in [
        ("Context & Background", "background"),
        ("Needs Assessment", "needs_assessment"),
        ("Strategic Justification", "strategic_justification"),
    ]:
        blocks = _markdown_blocks(proposal.get(field))
        if blocks:
            heading(title)
            story.extend(Paragraph(block, styles["body"]) for block in blocks)
            append_sources(field)

    toc = _load(proposal.get("toc"), []) or _load(proposal.get("toc_nodes"), [])
    if isinstance(toc, list) and toc:
        heading("Theory of Change")
        toc_rows = [["Level", "Intervention / Change Statement"]]
        toc_rows.extend(
            [
                [
                    _text(node.get("level", "Step")).title(),
                    _text(node.get("text") or node.get("intervention_logic") or node.get("label")),
                ]
                if isinstance(node, dict)
                else ["Step", _text(node)]
                for node in toc
            ]
        )
        story.append(_table(toc_rows, [34 * mm, 131 * mm], styles))

    # V2 logframe_rows (list of dicts with level, intervention_logic, indicators)
    logframe_rows = proposal.get("logframe_rows", [])
    if isinstance(logframe_rows, list) and logframe_rows:
        heading("Logical Framework")
        frame_rows = [["Level", "Intervention Logic", "Means of Verification", "Assumptions"]]
        for row in logframe_rows:
            if not isinstance(row, dict):
                continue
            level = _text(row.get("level", "")).title()
            logic = _text(row.get("intervention_logic", ""))
            mov = _text(row.get("means_of_verification", ""))
            assumptions = _text(row.get("assumptions", ""))
            frame_rows.append([level, logic, mov, assumptions])
        if len(frame_rows) > 1:
            story.append(_table(frame_rows, [22 * mm, 65 * mm, 40 * mm, 38 * mm], styles))
    else:
        logframe = _load(proposal.get("logframe"), {}) or _load(proposal.get("logframe_data"), {})
        if isinstance(logframe, dict) and logframe:
            heading("Logical Framework")
            frame_rows = [["Level", "Objective / Result", "Indicator"]]
            for key, label in [
                ("goal", "Goal / Impact"),
                ("outcomes", "Outcome"),
                ("outputs", "Output"),
                ("activities", "Activity"),
            ]:
                value = logframe.get(key)
                indicator = logframe.get(f"{key.rstrip('s')}_indicator", "-")
                values = value if isinstance(value, list) else [value]
                for item in values:
                    if not item:
                        continue
                if isinstance(item, dict):
                    frame_rows.append(
                        [label, item.get("text") or item.get("description"), item.get("indicators", indicator)]
                    )
                else:
                    frame_rows.append([label, item, indicator])
        if len(frame_rows) > 1:
            story.append(_table(frame_rows, [28 * mm, 80 * mm, 57 * mm], styles))

    for title, field in [("Implementation Methodology", "methodology")]:
        blocks = _markdown_blocks(proposal.get(field))
        if blocks:
            heading(title)
            story.extend(Paragraph(block, styles["body"]) for block in blocks)
            append_sources(field)

    budget = _load(proposal.get("budget"), {}) or _load(proposal.get("budget_details"), {})
    if isinstance(budget, (dict, list)) and budget:
        heading("Budget Summary")
        lines = budget.get("lines", []) if isinstance(budget, dict) else budget
        budget_rows = [["Category", "Line item / description", "Amount", "Share"]]
        for line in lines:
            if isinstance(line, dict):
                budget_rows.append(
                    [
                        line.get("category", "General"),
                        line.get("description") or line.get("item"),
                        line.get("amount", "-"),
                        line.get("percentage", "-"),
                    ]
                )
        if len(budget_rows) > 1:
            budget_rows.append(
                ["TOTAL PROJECT BUDGET", "", budget.get("total", "-") if isinstance(budget, dict) else "-", "100%"]
            )
            table = _table(budget_rows, [31 * mm, 88 * mm, 27 * mm, 19 * mm], styles)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e2e8f0")),
                        ("FONTNAME", (0, -1), (-1, -1), bold),
                        ("LINEABOVE", (0, -1), (-1, -1), 1, _NAVY),
                        ("ALIGN", (2, 1), (3, -1), "RIGHT"),
                    ]
                )
            )
            story.append(table)

    mne = _load(proposal.get("mne_framework"), [])
    indicators = mne.get("indicators", []) if isinstance(mne, dict) else mne
    if isinstance(indicators, list) and indicators:
        heading("Monitoring & Evaluation Framework")
        rows = [["Indicator", "Baseline", "Target", "Verification"]]
        rows.extend(
            [
                [
                    item.get("name") or item.get("indicator"),
                    item.get("baseline", "-"),
                    item.get("target", "-"),
                    item.get("source") or item.get("verification", "-"),
                ]
                for item in indicators
                if isinstance(item, dict)
            ]
        )
        if len(rows) > 1:
            story.append(_table(rows, [65 * mm, 25 * mm, 25 * mm, 50 * mm], styles))

    risks = _load(proposal.get("risk_matrix"), []) or _load(proposal.get("risk_details"), [])
    if isinstance(risks, list) and risks:
        heading("Risk Matrix & Mitigation")
        rows = [["Risk Category", "Description", "Likelihood", "Impact", "Mitigation"]]
        rows.extend(
            [
                [
                    item.get("category", "-"),
                    item.get("risk_description") or item.get("risk") or item.get("name", "-"),
                    str(item.get("likelihood", "-")),
                    str(item.get("impact", "-")),
                    item.get("mitigation_strategy") or item.get("mitigation", "-"),
                ]
                for item in risks
                if isinstance(item, dict)
            ]
        )
        if len(rows) > 1:
            story.append(_table(rows, [28 * mm, 40 * mm, 20 * mm, 18 * mm, 55 * mm], styles))

    for title, field in [("Sustainability & Exit Strategy", "sustainability"), ("Coordination", "coordination")]:
        blocks = _markdown_blocks(proposal.get(field))
        if blocks:
            heading(title)
            story.extend(Paragraph(block, styles["body"]) for block in blocks)
            append_sources(field)

    # V2: PSEA & Sphere commitments
    if proposal.get("psea_signoff") or proposal.get("sphere_standards_narrative"):
        heading("Compliance & Commitments")
        if proposal.get("psea_signoff"):
            story.append(
                Paragraph(
                    "PSEA Code of Conduct: The organization signs off on the six IASC core principles on Protection from Sexual Exploitation and Abuse.",
                    styles["body"],
                )
            )
        sphere = proposal.get("sphere_standards_narrative", "")
        if sphere:
            story.append(Paragraph(f"<b>Sphere Standards:</b> {sphere}", styles["body"]))

    # V2: Quality assessment summary
    me_score = proposal.get("me_overall_score")
    if me_score is not None:
        heading("Quality Assessment")
        story.append(Paragraph(f"<b>M&E Overall Score:</b> {me_score}/100", styles["body"]))
        me_suggestions = proposal.get("me_suggestions", [])
        if me_suggestions:
            for s in me_suggestions[:10]:
                story.append(Paragraph(f"- {s}", styles["body"]))
        csv = proposal.get("cross_section_validation")
        if csv and isinstance(csv, dict):
            story.append(Paragraph(f"<b>Cross-Section Validation:</b> {csv.get('summary', '')}", styles["body"]))

    doc.build(story, onFirstPage=_page_header_footer, onLaterPages=_page_header_footer)
    output.seek(0)
    return output
