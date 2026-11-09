"""Landscape, private annual colloscopes with one page per promotion and subject."""

from collections import defaultdict
from colorsys import hls_to_rgb
from datetime import date, datetime, timedelta
from io import BytesIO
from math import ceil
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas

from app.services.attendance_pdf import FONT


def group_palette(numbers: list[int]) -> dict[int, colors.Color]:
    """Assign a distinct pastel to every group, resetting the hue wheel per promotion."""
    ordered = sorted(set(numbers))
    return {
        number: colors.Color(*hls_to_rgb(index / max(1, len(ordered)), 0.86, 0.62))
        for index, number in enumerate(ordered)
    }


def render_kholloscope_pdf(
    calendars: list[dict],
    sessions: list[dict],
    catalog: dict,
    requested_by: str,
    generated_at: datetime,
) -> bytes:
    """Render trusted assigned sessions with consistent colors and authenticated attribution.

    Parameters
    ----------
    calendars, sessions, catalog
        Authorized annual bounds, saved group assignments and server-resolved display names.
    requested_by, generated_at
        Current account's display name and aware export timestamp.

    Returns
    -------
    bytes
        A private landscape PDF with roster pages and one page per promotion/subject.
    """
    output = BytesIO()
    width, height = landscape(A3)
    canvas = Canvas(output, pagesize=(width, height))
    canvas.setTitle("Kholloscope annuel")
    canvas.setAuthor(requested_by)
    subjects = {s["id"]: s for s in catalog["subjects"]}
    teachers = {t["id"]: t["name"] for t in catalog["teachers"]}
    rooms = {r["id"]: r["name"] for r in catalog["rooms"]}
    pages, palettes = [], {}
    for calendar in calendars:
        roster = {g["number"]: g for g in calendar.get("groups", [])}
        for s in sessions:
            if s["calendar_id"] == calendar["id"]:
                roster.setdefault(s["group"], {"number": s["group"], "students": []})
        ordered = [roster[n] for n in sorted(roster)]
        palettes[calendar["id"]] = group_palette(list(roster))
        for start in range(0, len(ordered), 12):
            pages.append((calendar, None, ordered[start : start + 12]))
        for subject in sorted(
            {s["subject_id"] for s in sessions if s["calendar_id"] == calendar["id"]},
            key=lambda identifier: subjects.get(identifier, {}).get("name", str(identifier)),
        ):
            pages.append((calendar, subject, None))
    timestamp = generated_at.astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H:%M:%S")
    margin, label_width = 32, 235
    available = width - 2 * margin

    def text(value: str, x: float, y: float, size: float, limit: float) -> None:
        """Draw bounded plain text without interpreting account or subject names as markup."""
        canvas.setFont(FONT, size)
        while value and pdfmetrics.stringWidth(value, FONT, size) > limit:
            value = value[:-2] + "…" if len(value) > 2 else ""
        canvas.drawString(x, y, value)

    def footer(page: int) -> None:
        """Repeat provenance and overall pagination on rosters and subject pages."""
        canvas.setFillColor(colors.HexColor("#475569"))
        text(f"Généré le {timestamp} · Compte : {requested_by}", margin, 24, 8, available - 90)
        canvas.setFont(FONT, 8)
        canvas.drawRightString(width - margin, 24, f"{page} / {len(pages)}")
        canvas.showPage()

    for page, (calendar, subject_id, roster) in enumerate(pages, 1):
        palette = palettes[calendar["id"]]
        if roster is not None:
            canvas.setFillColor(colors.HexColor("#244BC1"))
            canvas.rect(0, height - 12, width, 12, fill=1, stroke=0)
            canvas.setFillColor(colors.HexColor("#14213D"))
            text("COMPOSITION DES GROUPES", margin, height - 48, 20, available)
            text(calendar["name"], margin, height - 76, 15, available)
            text(
                "Les couleurs correspondent aux groupes dans les tableaux des matières.",
                margin,
                height - 99,
                10,
                available,
            )
            columns = 2 if len(roster) <= 10 else 3
            card_width = (available - 16 * (columns - 1)) / columns
            rows = ceil(len(roster) / columns)
            card_height = min(140, (height - 190) / max(1, rows) - 12)
            for index, group in enumerate(roster):
                x = margin + (index % columns) * (card_width + 16)
                y = height - 126 - (index // columns + 1) * (card_height + 12)
                canvas.setFillColor(colors.white)
                canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
                canvas.rect(x, y, card_width, card_height, fill=1, stroke=1)
                canvas.setFillColor(palette[group["number"]])
                canvas.rect(x, y + card_height - 29, card_width, 29, fill=1, stroke=0)
                canvas.setFillColor(colors.HexColor("#14213D"))
                text(
                    f"Groupe {group['number']:02d}",
                    x + 12,
                    y + card_height - 20,
                    12,
                    card_width - 24,
                )
                students = group.get("students", [])
                size = min(11, (card_height - 39) / max(1, len(students)) / 1.3)
                for pupil_index, pupil in enumerate(students):
                    name = f"{pupil['last_name'].upper()} {pupil['first_name']}".strip()
                    text(
                        name,
                        x + 12,
                        y + card_height - 47 - pupil_index * size * 1.3,
                        size,
                        card_width - 24,
                    )
                if not students:
                    text("Aucun élève affecté", x + 12, y + card_height - 50, 10, card_width - 24)
            footer(page)
            continue
        selected = [
            s
            for s in sessions
            if s["calendar_id"] == calendar["id"] and s["subject_id"] == subject_id
        ]
        cells = defaultdict(list)
        for s in selected:
            day = date.fromisoformat(s["day"])
            week = (day - timedelta(days=day.weekday())).isoformat()
            key = (day.weekday(), s["start"], s["teacher_id"], s["room_id"])
            cells[key, week].append(s)
        rows = sorted({key for key, _ in cells})
        weeks = sorted({w["start"] for w in calendar["weeks"]} | {week for _, week in cells})
        margin, label_width = 32, 235
        available = width - margin * 2
        column = (available - label_width) / max(1, len(weeks))
        row_height = min(42, (height - 185) / max(1, len(rows)))
        font = min(9, max(6, row_height / 3))
        accent = colors.HexColor(subjects.get(subject_id, {}).get("color", "#244BC1"))
        canvas.setFillColor(accent)
        canvas.rect(0, height - 12, width, 12, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#14213D"))
        text("KHOLLOSCOPE ANNUEL", margin, height - 46, 20, available)
        text(calendar["name"], margin, height - 72, 15, available)
        text(
            subjects.get(subject_id, {}).get("name", str(subject_id)),
            margin,
            height - 94,
            12,
            available,
        )
        text(
            "G = groupe · * = séance déplacée · dates en tête : lundis des semaines",
            margin,
            height - 114,
            8,
            available,
        )
        top = height - 132
        canvas.setFillColor(accent)
        canvas.rect(margin, top - 28, available, 28, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        text("INTERVENANT · CRÉNEAU · SALLE", margin + 8, top - 18, 9, label_width - 12)
        for index, week in enumerate(weeks):
            x = margin + label_width + index * column
            text(f"{week[8:10]}/{week[5:7]}", x + 2, top - 14, min(8, column / 3.6), column - 3)
            text(week[:4], x + 2, top - 24, 6, column - 3)
        for index, row in enumerate(rows):
            y = top - 28 - (index + 1) * row_height
            canvas.setFillColor(colors.HexColor("#F1F5F9") if index % 2 == 0 else colors.white)
            canvas.rect(margin, y, available, row_height, fill=1, stroke=0)
            canvas.setFillColor(colors.HexColor("#14213D"))
            weekday, start, teacher, room = row
            text(
                teachers.get(teacher, str(teacher)),
                margin + 6,
                y + row_height * 0.65,
                font,
                label_width - 12,
            )
            clock = f"{start // 3600:02d}:{start % 3600 // 60:02d}"
            weekday_label = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"][weekday]
            label = f"{weekday_label} {clock} · {rooms.get(room, str(room))}"
            text(label, margin + 6, y + row_height * 0.22, font - 0.5, label_width - 12)
            for col, week in enumerate(weeks):
                x = margin + label_width + col * column
                values = sorted(cells[row, week], key=lambda s: s["group"])
                if values:
                    canvas.setFillColor(palette[values[0]["group"]])
                    canvas.rect(x, y, column, row_height, fill=1, stroke=0)
                    canvas.setFillColor(colors.HexColor("#14213D"))
                    label = "/".join(
                        f"{s['group']:02d}"
                        + (
                            "*"
                            if s.get("original_day", s["day"]) != s["day"]
                            or s.get("original_start", s["start"]) != s["start"]
                            else ""
                        )
                        for s in values
                    )
                    text(label, x + 3, y + row_height * 0.4, font, column - 5)
                canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
                canvas.line(x, y, x, y + row_height)
            canvas.line(margin, y, width - margin, y)
        footer(page)
    canvas.save()
    return output.getvalue()
