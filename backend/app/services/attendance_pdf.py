"""Render private A4 promotion rosters without a browser or persistent document storage."""

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Literal
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
from reportlab.platypus import (
    BaseDocTemplate,
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

AttendanceVariant = Literal["roster", "halves", "thirds", "kholles", "custom", "global"]

FONT = "AttendanceVera"
# The font ships with the toolkit and is embedded, including accented names, in every PDF.
pdfmetrics.registerFont(TTFont(FONT, str(Path(reportlab.__file__).parent / "fonts" / "Vera.ttf")))

GROUP_COLORS = {"A": "#2456A6", "B": "#9B3D79", "X": "#22735A", "Y": "#A45B12", "Z": "#6845A3"}


class StatusParagraph(Paragraph):
    """Draw an actual vector circle beside a name, independent of font glyph coverage."""

    def __init__(self, text: str, style: ParagraphStyle, active: bool) -> None:
        """Keep the status color alongside escaped identity markup."""
        super().__init__(text, style)
        self.badge_color = colors.HexColor("#16803C" if active else "#C62828")

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        """Reserve horizontal badge space and return the complete cell size."""
        width, height = super().wrap(max(1, availWidth - 10), availHeight)
        return width + 10, height

    def draw(self) -> None:
        """Paint a filled circle and the name without Unicode status symbols."""
        self.canv.saveState()
        self.canv.setFillColor(self.badge_color)
        self.canv.circle(3, self.height - self.style.fontSize * 0.6, 2.5, stroke=0, fill=1)
        self.canv.translate(10, 0)
        super().draw()
        self.canv.restoreState()


@dataclass(frozen=True)
class AttendanceStudent:
    """Carry only the identity and archive flag required by an attendance sheet."""

    last_name: str
    first_name: str
    archived: bool = False
    active: bool = False
    assignments: tuple[str, str, str] = ("", "", "")


@dataclass(frozen=True)
class AttendanceGroup:
    """Hold an authorized group title and its current roster."""

    title: str
    students: list[AttendanceStudent]


def group_label(kind: str, number: int) -> str:
    """Return the saved group's display label: A/B, X/Y/Z or a padded number."""
    if kind == "halves":
        return chr(64 + number)
    if kind == "thirds":
        return chr(87 + number)
    return f"{number:02}"


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
    variant: AttendanceVariant = "roster",
    groups: list[AttendanceGroup] | None = None,
    defined_partitions: list[str] | None = None,
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
        rows.append(
            [
                StatusParagraph(cells[0], style, pupil.active and not pupil.archived),
                Paragraph(cells[1], style),
                "",
            ]
        )
    identity_rows = [row[:2] for row in rows[1:]]
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
    story = [table]
    if variant == "global":
        kinds = ("halves", "thirds", "kholles")
        selected = [
            index
            for index, kind in enumerate(kinds)
            if (
                kind in defined_partitions
                if defined_partitions is not None
                else any(pupil.assignments[index] for pupil in students)
            )
        ]
        headings = ("Demi", "Tiers", "Khôlle")
        rows = [
            [
                Paragraph(heading, style)
                for heading in (
                    "NOM",
                    "Prénom",
                    *[headings[index] for index in selected],
                    "Remarque",
                )
            ]
        ]
        for pupil, original in zip(ordered, identity_rows, strict=True):
            rows.append(
                [
                    *original[:2],
                    *[
                        Paragraph(
                            '<font color="'
                            f'{GROUP_COLORS.get(pupil.assignments[index], "#222222")}">'
                            f"{escape(pupil.assignments[index])}</font>",
                            style,
                        )
                        for index in selected
                    ],
                    "",
                ]
            )
        table = LongTable(
            rows,
            colWidths=[
                width * 0.27,
                width * 0.21,
                *[width * 0.09 for _ in selected],
                width * (0.52 - 0.09 * len(selected)),
            ],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAEAEA")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#F6F6F6")],
                    ),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D6D6D6")),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ]
            )
        )
        story = [table]
    elif variant != "roster":
        count = len(groups or [])
        columns = max(1, count) if variant == "custom" else 2 if variant == "halves" else 3
        story = grouped_tables(groups or [], columns, width)
    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return output.getvalue()


def grouped_tables(groups: list[AttendanceGroup], columns: int, width: float) -> list:
    """Build parallel tables with aligned rows that can paginate without clipping names.

    Parameters
    ----------
    groups, columns, width
        Authorized compositions, number of parallel tables and available page width.

    Returns
    -------
    list
        Splittable tables with repeated group headings, or an explicit empty state.
    """
    style = ParagraphStyle("GroupRoster", fontName=FONT, fontSize=8, leading=10)
    if not groups:
        return [Paragraph("Aucun groupe enregistré.", style)]
    story = []
    for start in range(0, len(groups), columns):
        batch = groups[start : start + columns]
        rosters = [
            sorted(
                group.students,
                key=lambda pupil: (
                    pupil.archived,
                    sort_name(pupil.last_name),
                    sort_name(pupil.first_name),
                ),
            )
            for group in batch
        ]
        headings = [Paragraph(escape(group.title), style) for group in batch]
        rows = [headings + [""] * (columns - len(batch))]
        for index in range(max(1, *(len(roster) for roster in rosters))):
            cells = []
            for roster in rosters:
                if index >= len(roster):
                    cells.append("")
                    continue
                pupil = roster[index]
                name = escape(f"{pupil.last_name.upper()} {pupil.first_name.title()}")
                if pupil.archived:
                    name = f'<font color="#666666"><strike>{name}</strike></font>'
                cells.append(StatusParagraph(name, style, pupil.active and not pupil.archived))
            rows.append(cells + [""] * (columns - len(batch)))
        gap = 12
        cell_width = (width - gap * (columns - 1)) / columns
        spaced_rows = [
            [
                cell
                for index, value in enumerate(row)
                for cell in (["", value] if index else [value])
            ]
            for row in rows
        ]
        widths = [
            cell
            for index in range(columns)
            for cell in ([gap, cell_width] if index else [cell_width])
        ]
        table = Table(spaced_rows, colWidths=widths, repeatRows=1)
        commands = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        for index, roster in enumerate(rosters):
            column = index * 2
            last = max(1, len(roster))
            commands.extend(
                [
                    ("BACKGROUND", (column, 0), (column, 0), colors.HexColor("#EAEAEA")),
                    (
                        "ROWBACKGROUNDS",
                        (column, 1),
                        (column, last),
                        [colors.white, colors.HexColor("#F6F6F6")],
                    ),
                    ("GRID", (column, 0), (column, last), 0.3, colors.HexColor("#D6D6D6")),
                ]
            )
        table.setStyle(TableStyle(commands))
        story.append(table)
        story.append(Spacer(1, 12))
    return story
