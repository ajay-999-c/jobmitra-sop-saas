"""PDF rendering only. No email delivery or database access."""

import io
import json
from decimal import Decimal
from html import escape
from pathlib import Path

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .common import AtsError

TERMS = json.loads(Path(__file__).with_name("proposal_terms.json").read_text())
TITLE = "Recruitment Services Proposal & Terms of Engagement"
CONSULTANT = "e - Friend Solutions India (Jobmitra.com)"
LOGO = Path(__file__).parents[2] / "static" / "stage2" / "jobmitra-logo.jpeg"

# ReportLab's bundled, redistributable TrueType faces give deterministic embedding.
font_dir = Path(reportlab.__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("Proposal", str(font_dir / "Vera.ttf")))
pdfmetrics.registerFont(TTFont("Proposal-Bold", str(font_dir / "VeraBd.ttf")))
pdfmetrics.registerFontFamily("Proposal", normal="Proposal", bold="Proposal-Bold")


def clauses(percent):
    days = int(Decimal(percent) * 365 / 100)
    return [c.format(percent=percent, days=days) for c in TERMS["clauses"]]


def render(snapshot):
    s = snapshot
    # Fail explicitly instead of silently painting missing glyphs in a legal document.
    supported = pdfmetrics.getFont("Proposal").face.charWidths
    if any(ord(c) not in supported for c in json.dumps(s, ensure_ascii=False) if ord(c) > 127):
        raise AtsError("These document details need an additional font. No PDF was saved.", 422)
    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=19 * mm,
        leftMargin=19 * mm,
        topMargin=27 * mm,
        bottomMargin=19 * mm,
        title=TITLE,
        author=s["consultant"],
    )
    styles = getSampleStyleSheet()
    for name, size, leading, color in [
        ("Body", 9, 14, "#344256"),
        ("Small", 8, 12, "#627084"),
        ("TitleP", 21, 27, "#172a40"),
        ("Section", 12, 18, "#172a40"),
    ]:
        styles.add(
            ParagraphStyle(
                name=name,
                fontName="Proposal",
                fontSize=size,
                leading=leading,
                textColor=colors.HexColor(color),
                spaceAfter=7,
                alignment=TA_LEFT,
            )
        )

    def p(value, style="Body"):
        return Paragraph(value, styles[style])

    def safe(value):
        return escape(str(value or ""))

    def page(canvas, document):
        canvas.saveState()
        canvas.drawImage(
            str(LOGO),
            19 * mm,
            A4[1] - 20 * mm,
            width=32 * mm,
            height=10 * mm,
            preserveAspectRatio=True,
            mask="auto",
        )
        canvas.setFont("Proposal", 8)
        canvas.setFillColor(colors.HexColor("#657387"))
        canvas.drawRightString(A4[0] - 19 * mm, A4[1] - 16 * mm, "RECRUITMENT SERVICES")
        canvas.setStrokeColor(colors.HexColor("#dfe4eb"))
        canvas.line(19 * mm, 15 * mm, A4[0] - 19 * mm, 15 * mm)
        footer = "Unsigned proposal | " + s["reference"]
        # Full reference stays in the document body; constrain the running footer.
        if pdfmetrics.stringWidth(footer, "Proposal", 8) > 140 * mm:
            while pdfmetrics.stringWidth(footer + "...", "Proposal", 8) > 140 * mm:
                footer = footer[:-1]
            footer += "..."
        canvas.drawString(19 * mm, 10 * mm, footer)
        canvas.drawRightString(A4[0] - 19 * mm, 10 * mm, f"Page {document.page}")
        canvas.restoreState()

    story = [
        p(safe(TITLE), "TitleP"),
        p("COMMERCIAL PROPOSAL", "Small"),
        p("Prepared for <b>" + safe(s["company_name"]) + "</b>"),
        p(
            "Reference: <b>"
            + safe(s["reference"])
            + "</b> &nbsp; | &nbsp; Issued: "
            + safe(s["issue_date"]),
            "Small",
        ),
        Spacer(1, 3 * mm),
    ]
    days = int(Decimal(s["fee_percent"]) * 365 / 100)
    rows = [
        ("Consultant", s["consultant"]),
        ("Client", s["company_name"]),
        ("Recruitment service fee", s["fee_percent"] + "% of Annual CTC"),
        ("Fee calculation basis", "Candidate Annual CTC (basic salary + allowances)"),
        ("Salary-days illustration", str(days) + " whole days (rounded down; illustrative only)"),
        ("Payment terms", "Within 7 days of candidate joining, against invoice"),
        ("Applicable taxes", "Additional, if applicable"),
    ]
    if s.get("annual_ctc"):
        rows.extend(
            [
                ("Illustrative Annual CTC (INR)", s["annual_ctc"]),
                ("Fee before applicable taxes (INR)", s["fee_amount"]),
            ]
        )
    table = Table(
        [[p(safe(a), "Small"), p("<b>" + safe(b) + "</b>")] for a, b in rows],
        colWidths=[53 * mm, 119 * mm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f8fb")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e0e5ed")),
            ]
        )
    )
    story.extend(
        [
            table,
            Spacer(1, 4 * mm),
            p(
                "The contractual fee is calculated from the exact percentage of Annual CTC. "
                "The salary-days illustration does not determine the contractual amount.",
                "Small",
            ),
            p("Terms &amp; Conditions", "Section"),
            p(
                "These terms are between <b>"
                + safe(s["consultant"])
                + "</b> (the Consultant) and <b>"
                + safe(s["company_name"])
                + "</b> (the Client)."
            ),
        ]
    )
    for i, clause in enumerate(s["clauses"], 1):
        if i == 5:
            # Start page two for a normal proposal, but do not force an almost
            # empty third page if a long legal company name already flowed over.
            story.extend(
                [CondPageBreak(140 * mm), p("Terms &amp; Conditions - continued", "Section")]
            )
        story.append(p(f"<b>{i}.</b> &nbsp; {clause}"))
    story.extend(
        [
            Spacer(1, 3 * mm),
            p(
                "Please review these terms and share your confirmation or any questions. "
                "We look forward "
                "to a successful recruitment partnership with your team."
            ),
            p(
                "<b>Vishal Agrawal</b><br/>Director<br/>"
                + safe(s["consultant"])
                + "<br/>www.jobmitra.com"
            ),
            Spacer(1, 4 * mm),
        ]
    )
    acknowledgement = [
        p("Company acknowledgement", "Section"),
        p(
            "To be completed by the Client after review. "
            "This unsigned document does not record acceptance.",
            "Small",
        ),
    ]
    for label, value in [
        ("Authorized representative name", ""),
        ("Designation", ""),
        ("Company name", s["company_name"]),
        ("Signature", ""),
        ("Date", ""),
        ("Company seal (optional)", ""),
    ]:
        acknowledgement.append(p("<b>" + label + ":</b> " + (safe(value) if value else "_" * 45)))
    story.append(KeepTogether(acknowledgement))
    doc.build(story, onFirstPage=page, onLaterPages=page)
    return output.getvalue()
