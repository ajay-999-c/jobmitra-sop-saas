"""Existing ReportLab proposal renderer, following the finalized Word reference."""

import io
import json
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    CondPageBreak,
    Flowable,
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
ASSETS = Path(__file__).parents[2] / "static" / "ats_v2" / "proposal-assets"
LOGO = ASSETS / "jobmitra-logo.jpg"
RENDERER_VERSION = 2
DAYS = {"6": 21, "8.33": 30}
INK, MUTED, SUBTLE, RED, LINE = [
    colors.HexColor(value) for value in ["#1D2C43", "#53647B", "#7B899D", "#D7192A", "#E1E7EF"]
]
MARGIN, WIDTH = 56.15, A4[0] - 112.3

# The reference uses Inter. These licensed static instances retain its exact
# outlines and use a renamed family to respect the reserved font name.
pdfmetrics.registerFont(TTFont("Proposal", str(ASSETS / "JobmitraProposal-Regular.ttf")))
pdfmetrics.registerFont(TTFont("Proposal-Bold", str(ASSETS / "JobmitraProposal-Bold.ttf")))
pdfmetrics.registerFontFamily("Proposal", normal="Proposal", bold="Proposal-Bold")


def clauses(percent):
    if percent not in DAYS:
        raise AtsError("Choose the approved 6% or 8.33% proposal.")
    return [c.format(percent=percent, days=DAYS[percent]) for c in TERMS["clauses"]]


class Section(Flowable):
    """The source's heading and bottom rule; keep it with the following text."""

    def __init__(self, heading, style, rule=RED):
        super().__init__()
        self.paragraph, self.rule = Paragraph(heading, style), rule
        self.keepWithNext = True

    def wrap(self, width, height):
        self.width = width
        _, self.text_height = self.paragraph.wrap(width, height)
        self.height = self.text_height + 10
        return width, self.height

    def draw(self):
        self.paragraph.drawOn(self.canv, 0, 10)
        self.canv.setStrokeColor(self.rule)
        self.canv.setLineWidth(1.25 if self.rule == RED else 0.75)
        self.canv.line(0, 2, self.width, 2)


class NumberedCanvas(pdfcanvas.Canvas):
    def __init__(self, *args, footer, **kwargs):
        super().__init__(*args, **kwargs)
        self._page_states, self._footer = [], footer

    def showPage(self):
        self._page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._page_states)
        for state in self._page_states:
            self.__dict__.update(state)
            self._footer(self, total)
            super().showPage()
        super().save()


def render(snapshot):
    s = snapshot
    supported = pdfmetrics.getFont("Proposal").face.charWidths
    if any(ord(c) not in supported for c in json.dumps(s, ensure_ascii=False) if ord(c) > 127):
        raise AtsError("These document details need an additional font. No PDF was saved.", 422)
    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=MARGIN,
        leftMargin=MARGIN,
        topMargin=98,
        bottomMargin=73,
        title=TITLE,
        author=s["consultant"],
    )
    # Remove the default frame's extra inset; Word's table/text edges align.
    doc.leftMargin -= 6
    doc.rightMargin -= 6
    doc.topMargin -= 6
    doc.bottomMargin -= 6
    styles = {
        name: ParagraphStyle(
            name,
            fontName="Proposal-Bold" if bold else "Proposal",
            fontSize=size,
            leading=leading,
            textColor=color,
            alignment=TA_LEFT,
            spaceAfter=after,
        )
        for name, size, leading, color, bold, after in [
            ("Body", 10, 14.9, INK, False, 0),
            ("Label", 9, 13.45, MUTED, False, 0),
            ("Value", 9.5, 13.45, INK, True, 0),
            ("Meta", 9, 12.2, SUBTLE, False, 0),
            ("Title", 20.5, 27.8, INK, True, 0),
            ("Section", 13, 18, INK, True, 0),
            ("Intro", 9.5, 12.9, MUTED, False, 0),
            ("Number", 10, 14.9, RED, True, 0),
            ("Name", 11, 14.9, INK, True, 0),
            ("Signoff", 9.5, 12.9, MUTED, False, 0),
            ("Website", 9, 12.2, RED, False, 0),
            ("Footer", 8, 10, SUBTLE, False, 0),
        ]
    }

    def p(value, style="Body"):
        return Paragraph(value, styles[style])

    def safe(value):
        return escape(str(value or ""))

    def header(canvas, document):
        canvas.saveState()
        canvas.drawImage(str(LOGO), 65.2, A4[1] - 83.15, width=112.3, height=45.9, mask="auto")
        canvas.setFont("Proposal-Bold", 8.5)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(A4[0] - MARGIN, A4[1] - 45.5, "RECRUITMENT SERVICES")
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.6)
        canvas.line(MARGIN, A4[1] - 97.05, A4[0] - MARGIN, A4[1] - 97.05)
        canvas.restoreState()

    def footer(canvas, total):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.6)
        canvas.line(MARGIN, 62.4, A4[0] - MARGIN, 62.4)
        # Wrap long references, retaining every character and the page-number area.
        reference = p(safe(s["reference"]), "Footer")
        _, height = reference.wrap(WIDTH - 85, 35)
        reference.drawOn(canvas, MARGIN, 41 - height)
        canvas.setFont("Proposal", 8)
        canvas.setFillColor(SUBTLE)
        canvas.drawRightString(A4[0] - MARGIN, 33, f"Page {canvas.getPageNumber()} of {total}")
        canvas.restoreState()

    story = [
        p("Recruitment Services Proposal", "Title"),
        Spacer(1, 8),
        p("&amp; Terms of Engagement", "Title"),
        Spacer(1, 11),
        p(
            "Reference: <b>"
            + safe(s["reference"])
            + "</b> &nbsp; | &nbsp; Issued: "
            + safe(s["issue_date"]),
            "Meta",
        ),
        Spacer(1, 19),
    ]
    rows = [
        ("Consultant", s["consultant"]),
        ("Client", s["company_name"]),
        ("Recruitment service fee", s["fee_percent"] + "% of Annual CTC"),
        ("Fee calculation basis", "Candidate Annual CTC"),
        ("Salary-days", str(DAYS[s["fee_percent"]]) + " whole days"),
        ("Payment terms", "Within 7 days of candidate joining, against invoice"),
    ]
    table = Table(
        [[p(safe(a), "Label"), p(safe(b), "Value")] for a, b in rows],
        colWidths=[147.6, WIDTH - 147.6],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#F5F7FA"), colors.white]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4.75),
                ("TOPPADDING", (0, 0), (-1, -1), 5.9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5.9),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
            ]
        )
    )
    story.extend(
        [
            table,
            Spacer(1, 21),
            Section("Terms &amp; Conditions", styles["Section"]),
            Spacer(1, 8),
            p(
                "These terms are between "
                + safe(s["consultant"])
                + " (the Consultant) and "
                + safe(s["company_name"])
                + " (the Client).",
                "Intro",
            ),
            Spacer(1, 9),
        ]
    )
    for i, clause in enumerate(s["clauses"], 1):
        if i == 6:
            story.extend(
                [
                    CondPageBreak(510),
                    Section(
                        'Terms &amp; Conditions <font name="Proposal" '
                        'color="#53647B"> - continued</font>',
                        styles["Section"],
                    ),
                    Spacer(1, 10),
                ]
            )
        # Dedicated number column gives 1-10 identical hanging alignment. The
        # source has plain clauses; remove only markup, never change their words.
        plain = clause.replace("<b>", "").replace("</b>", "")
        row = Table(
            [[p(str(i) + ".", "Number"), p(plain)]], colWidths=[28.8, WIDTH - 28.8], hAlign="LEFT"
        )
        row.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
                ]
            )
        )
        story.append(row)
    story.extend(
        [
            Spacer(1, 17),
            p(
                "Please review these terms and share your confirmation or any questions. "
                "We look forward to a successful recruitment partnership with your team.",
                "Intro",
            ),
            Spacer(1, 14),
            p("Vishal Agrawal", "Name"),
            Spacer(1, 3),
            p("Chief Executive Officer", "Signoff"),
            Spacer(1, 2),
            p(safe(s["consultant"]), "Signoff"),
            Spacer(1, 2),
            p("www.jobmitra.com", "Website"),
            Spacer(1, 17),
        ]
    )
    acknowledgement = [Section("Company acknowledgement", styles["Section"], LINE), Spacer(1, 12)]
    labels = [
        "Authorized representative name",
        "Designation",
        "Company name",
        "Signature",
        "Date",
        "Company seal (optional)",
    ]
    entries = [
        [
            p(safe(label) + ":", "Label"),
            p(safe(s["company_name"]), "Value")
            if label == "Company name"
            else p("_" * 40, "Label"),
        ]
        for label in labels
    ]
    signatures = Table(entries, colWidths=[184.3, WIDTH - 184.3], hAlign="LEFT")
    signatures.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4.65),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4.65),
            ]
        )
    )
    acknowledgement.append(signatures)
    story.append(KeepTogether(acknowledgement))
    doc.build(
        story,
        onFirstPage=header,
        onLaterPages=header,
        canvasmaker=lambda *a, **kw: NumberedCanvas(*a, footer=footer, **kw),
    )
    return output.getvalue()
