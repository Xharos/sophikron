"""Render private A4 promotion rosters without a browser or persistent document storage."""

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import BaseDocTemplate, LongTable, Paragraph, SimpleDocTemplate, TableStyle

FONT = "AttendanceVera"
# The font ships with the toolkit and is embedded, including accented names, in every PDF.
pdfmetrics.registerFont(TTFont(FONT, str(Path(reportlab.__file__).parent / "fonts" / "Vera.ttf")))


@dataclass(frozen=True)
class AttendanceStudent:
    """Carry only the identity and archive flag required by an attendance sheet."""

    last_name: str
    first_name: str
    archived: bool = False
    active: bool = False


def sort_name(value: str) -> str:
    """Return an accent-insensitive alphabetical key for a display name."""
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )


def render_attendance_pdf(
    promotion_name: str,
    promotion_color: str,
    students: list[AttendanceStudent],
    requested_by: str,
    generated_at: datetime,
) -> bytes:
    """Build a compact roster with repeating headings and an authenticated generation footer.

    Parameters
    ----------
    promotion_name, promotion_color
        Authorized promotion title and its validated hexadecimal color.
    students
        Complete current roster, including archived pupils.
    requested_by
        Requester's display name obtained server-side.
    generated_at
        Aware generation timestamp, displayed in Europe/Paris.

    Returns
    -------
    bytes
        An A4 PDF suitable for inline viewing, printing and saving.
    """
    output = BytesIO()
    page_width, page_height = A4
    margin = 32
    width = page_width - 2 * margin
    ordered = sorted(
        students,
        key=lambda pupil: (pupil.archived, sort_name(pupil.last_name), sort_name(pupil.first_name)),
    )
    names = [(pupil.last_name.upper(), pupil.first_name.title()) for pupil in ordered]
    last_width = min(
        width * 0.38,
        max(pdfmetrics.stringWidth(name, FONT, 10) for name in ["NOM", *[n[0] for n in names]])
        + 24,
    )
    first_width = min(
        width * 0.28,
        max(pdfmetrics.stringWidth(name, FONT, 10) for name in ["Prénom", *[n[1] for n in names]])
        + 12,
    )
    style = ParagraphStyle(
        "Attendance",
        fontName=FONT,
        fontSize=10,
        leading=12,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#222222"),
        splitLongWords=True,
    )
    rows = [[Paragraph(heading, style) for heading in ("NOM", "Prénom", "Remarque")]]
    for pupil, (last_name, first_name) in zip(ordered, names, strict=True):
        cells = [escape(last_name), escape(first_name)]
        if pupil.archived:
            cells = [f'<font color="#666666"><strike>{cell}</strike></font>' for cell in cells]
        badge_color = "#16803C" if pupil.active and not pupil.archived else "#C62828"
        cells[0] = f'<font color="{badge_color}">●</font>  {cells[0]}'
        rows.append([*[Paragraph(cell, style) for cell in cells], ""])
    table = LongTable(
        rows,
        colWidths=[last_width, first_width, width - last_width - first_width],
        repeatRows=1,
        hAlign="LEFT",
        splitByRow=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAEAEA")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F6F6")]),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D6D6D6")),
            ]
        )
    )
    timestamp = generated_at.astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H:%M:%S")
    author = Paragraph(
        escape(requested_by),
        ParagraphStyle(
            "AttendanceFooter",
            fontName=FONT,
            fontSize=7,
            leading=8,
        ),
    )

    def decorate(canvas: Canvas, document: BaseDocTemplate) -> None:
        """Draw the promotion-colored title and fixed generation details on every page."""
        canvas.saveState()
        title_size = min(16, width / max(pdfmetrics.stringWidth(promotion_name, FONT, 1), 1))
        canvas.setFont(FONT, title_size)
        canvas.setFillColor(colors.HexColor(promotion_color))
        canvas.drawCentredString(page_width / 2, page_height - 38, promotion_name)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.setFont(FONT, 7)
        canvas.drawRightString(page_width - margin, 20, timestamp)
        _, author_height = author.wrap(width * 0.58, 30)
        author.drawOn(canvas, margin, 20 - author_height + 7)
        canvas.restoreState()

    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=56,
        bottomMargin=42,
        title=promotion_name,
        author=requested_by,
    )
    document.build([table], onFirstPage=decorate, onLaterPages=decorate)
    return output.getvalue()
