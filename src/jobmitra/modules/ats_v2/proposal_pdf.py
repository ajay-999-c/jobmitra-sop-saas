"""Existing ReportLab renderer, matching the approved single-page terms reference."""

import io
import json
from datetime import date
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import Paragraph

from .common import AtsError

TERMS = json.loads(Path(__file__).with_name("proposal_terms.json").read_text())
# Retain the existing Email API subject; this change applies to PDF presentation only.
TITLE = "Recruitment Services Proposal & Terms of Engagement"
CONSULTANT = "e - Friend Solutions India (Jobmitra.com)"
ASSETS = Path(__file__).parents[2] / "static" / "ats_v2" / "proposal-assets"
LOGO = ASSETS / "terms-logo.png"
RENDERER_VERSION = 3
DAYS = {"6": 21, "8.33": 30}
MARGIN, TEXT_X, ACCEPT_X = 51.1, 70.95, 295.85
WIDTH = A4[0] - 2 * MARGIN
INK = colors.HexColor("#202020")

# The Word reference specifies Arial; its approved PDF embeds Liberation Sans.
# These unchanged OFL font files need neither system fonts nor runtime downloads.
pdfmetrics.registerFont(TTFont("Terms", str(ASSETS / "LiberationSans-Regular.ttf")))
pdfmetrics.registerFont(TTFont("Terms-Bold", str(ASSETS / "LiberationSans-Bold.ttf")))
pdfmetrics.registerFontFamily("Terms", normal="Terms", bold="Terms-Bold")


def clauses(percent):
    if percent not in DAYS:
        raise AtsError("Choose the approved 6% or 8.33% proposal.")
    return [c.format(percent=percent, days=DAYS[percent]) for c in TERMS["clauses"]]


def render(snapshot):
    s = snapshot
    supported = pdfmetrics.getFont("Terms").face.charWidths
    if any(ord(c) not in supported for c in json.dumps(s, ensure_ascii=False) if ord(c) > 127):
        raise AtsError("These document details need an additional font. No PDF was saved.", 422)
    output = io.BytesIO()
    canvas = pdfcanvas.Canvas(output, pagesize=A4, title=TERMS["heading"], author=s["consultant"])
    body = ParagraphStyle(
        "TermsBody",
        fontName="Terms",
        fontSize=11.5,
        leading=15.2,
        textColor=INK,
        alignment=TA_LEFT,
        spaceShrinkage=0,
    )
    heading = ParagraphStyle(
        "Acceptance",
        parent=body,
        fontName="Terms-Bold",
        leading=15,
    )
    meta = ParagraphStyle(
        "Reference",
        parent=body,
        fontSize=8.5,
        leading=10.95,
        textColor=colors.HexColor("#606060"),
        alignment=TA_RIGHT,
    )

    def safe(value):
        return escape(str(value or ""))

    def paragraph(value, width, style=body):
        p = Paragraph(value, style)
        _, height = p.wrap(width, A4[1])
        return p, height

    def draw(p, x, top, height):
        p.drawOn(canvas, x, A4[1] - top - height)

    def header():
        canvas.drawImage(str(LOGO), 60.05, A4[1] - 82.1, 116.2, 36.8, mask="auto")
        issued = date.fromisoformat(s["issue_date"])
        metadata, height = paragraph(
            "Ref: " + safe(s["reference"]) + "<br/>" + f"{issued.day} {issued:%B %Y}",
            A4[0] - MARGIN - ACCEPT_X,
            meta,
        )
        draw(metadata, ACCEPT_X, 53.05, height)
        canvas.setFillColor(INK)
        canvas.setFont("Terms-Bold", 18)
        canvas.drawCentredString(A4[0] / 2, A4[1] - 111, TERMS["heading"])

    def next_page():
        canvas.showPage()
        header()
        return 126.2

    header()
    intro, height = paragraph(
        TERMS["introduction"].format(
            consultant=safe(s["consultant"]), company_name=safe(s["company_name"])
        ),
        WIDTH,
    )
    top = 126.2
    draw(intro, MARGIN, top, height)
    top += height + 9
    acceptance, acceptance_height = paragraph(
        "Accepted by " + safe(s["company_name"]),
        A4[0] - MARGIN - ACCEPT_X,
        heading,
    )
    extra_heading = max(0, acceptance_height - 15)
    bottom = A4[1] - 42.5
    for i, clause in enumerate(s["clauses"], 1):
        # Word's twip-rounded line fit leaves the final "extra." on line three.
        p, height = paragraph(clause, A4[0] - MARGIN - TEXT_X - 0.2)
        # Keep the final clause with the entire signature block for extreme names.
        needed = height + (45.2 + 130.2 + extra_heading if i == 10 else 0)
        if top + needed > bottom:
            top = next_page()
        canvas.setFillColor(INK)
        canvas.setFont("Terms", 11.5)
        canvas.drawString(MARGIN, A4[1] - top - 11.5, f"{i}.")
        draw(p, TEXT_X, top, height)
        top += height + (7 if i < 10 else 0)
    baseline = top + 45.2
    canvas.setFillColor(INK)
    for offset, text, font in [
        (0, "With regards,", "Terms-Bold"),
        (15, "Vishal Agrawal", "Terms-Bold"),
        (30, "CEO", "Terms"),
        (45, "e - Friend Solutions India", "Terms"),
    ]:
        canvas.setFont(font, 11.5)
        canvas.drawString(MARGIN, A4[1] - baseline - offset, text)
    draw(acceptance, ACCEPT_X, baseline - 11.5, acceptance_height)
    canvas.setFont("Terms", 10.5)
    for offset, label, blanks in [
        (23, "Authorized Person Name:  ", 19),
        (46, "Designation:  ", 29),
    ]:
        y = A4[1] - baseline - extra_heading - offset
        canvas.setFillColor(INK)
        canvas.drawString(ACCEPT_X, y, label)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawString(
            ACCEPT_X + pdfmetrics.stringWidth(label, "Terms", 10.5),
            y,
            "_" * blanks,
        )
    box_top = baseline + extra_heading + 57.4
    box_width, box_height = A4[0] - MARGIN - 5.3 - (ACCEPT_X + 5.35), 72.8
    canvas.setLineWidth(0.75)
    canvas.setStrokeColor(colors.HexColor("#777777"))
    canvas.rect(ACCEPT_X + 5.35, A4[1] - box_top - box_height, box_width, box_height)
    canvas.setFont("Terms", 10)
    canvas.setFillColor(colors.HexColor("#555555"))
    canvas.drawCentredString(
        ACCEPT_X + 5.35 + box_width / 2,
        A4[1] - box_top - box_height + 9.5,
        "Signature",
    )
    canvas.save()
    return output.getvalue()
