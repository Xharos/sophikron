"""Render a private, dateless weekly timetable as a single vector landscape A4 page."""

from datetime import date, datetime, timedelta
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

from app.services.attendance_pdf import FONT, group_label
from app.services.errors import AuthError
from app.services.timetable import student_receives


def select_view(board: dict, year_id: int, day: date, node: str) -> tuple[dict, str, list[dict]]:
    """Resolve an authorized tree selection and its week, excluding all khôlles.

    Parameters
    ----------
    board, year_id, day, node
        Authorized board, displayed annual grid, date and stable tree key.

    Returns
    -------
    tuple
        Year, selected audience suffix and filtered dated event segments.
    """
    year = next((item for item in board["years"] if item["id"] == year_id), None)
    if year is None:
        raise AuthError(404, "Année introuvable dans cet agenda.")
    members = board["members"]
    groups = [group for group in board["groups"] if group.get("is_active", True)]
    pupils = {member["id"]: member for member in members if "user" in member["roles"]}
    suffix, selected = "", set(pupils)
    if node == "unassigned":
        selected -= {pupil for group in groups for pupil in group["student_ids"]}
        suffix = "Élèves non affectés"
    elif node.startswith("student-"):
        identifier = int(node.split("-")[1])
        if identifier not in pupils:
            raise AuthError(404, "Élève introuvable dans cet agenda.")
        selected, suffix = {identifier}, pupils[identifier]["name"]
    elif node != "promotion":
        kind, number = node.split("-")
        group = next(
            (item for item in groups if item["kind"] == kind and item["number"] == int(number)),
            None,
        )
        if group is None:
            raise AuthError(404, "Groupe introuvable dans cet agenda.")
        selected = set(group["student_ids"])
        labels = {"halves": "Demi-groupe", "thirds": "Tiers de groupe", "kholles": "Khôlle"}
        suffix = (
            group.get("name", "Groupe personnalisé")
            if kind == "custom"
            else f"{labels[kind]} {group_label(kind, int(number))}"
        )
        if kind == "kholles":
            suffix = f"Khôlle {int(number):03d}"
    monday = day - timedelta(days=day.weekday())
    events = []
    for event in board["events"]:
        if (
            event["year_id"] != year_id
            or event["kind"] == "kholle"
            or event.get("target_kind") == "kholles"
        ):
            continue
        event_day = datetime.fromisoformat(event["start"]).date()
        if not monday <= event_day < monday + timedelta(days=7):
            continue
        if (
            node == "promotion"
            or event.get("target_kind", "promotion") == "promotion"
            or any(
                student_receives(
                    event,
                    identifier,
                    {
                        (assignment["kind"], assignment["number"])
                        for assignment in pupils[identifier].get("assignments", [])
                        if assignment["promotion_id"] == event["promotion_id"]
                    },
                )
                for identifier in selected
                if identifier in pupils
            )
        ):
            events.append(event)
    return year, suffix, events


def audience_label(event: dict) -> str:
    """Return a compact audience label without disclosing individual student names."""
    kind = event.get("target_kind", "promotion")
    if kind in {"halves", "thirds"}:
        return f"Groupe {group_label(kind, event['target_number'])}"
    return {
        "promotion": "Classe entière",
        "custom": event.get("audience_label", "Groupe"),
        "student": "Séance individuelle",
    }.get(kind, "Groupe")


def fitted_text(
    canvas: Canvas,
    lines: list[str],
    x: float,
    y: float,
    width: float,
    height: float,
    maximum: float = 9,
) -> None:
    """Fit escaped text in a block by shrinking both line spacing and font size.

    Parameters
    ----------
    canvas, lines, x, y, width, height, maximum
        Drawing surface, text lines, bottom-left bounds and preferred font size.

    Returns
    -------
    None
        Text is drawn inside the supplied rectangle without truncation.
    """
    longest = max(
        (pdfmetrics.stringWidth(word, FONT, 1) for line in lines for word in line.split()),
        default=1,
    )
    size = min(maximum, width / max(1, longest))
    while True:
        paragraph = Paragraph(
            "<br/>".join(escape(line).replace("\n", "<br/>") for line in lines if line),
            ParagraphStyle(
                "Timetable",
                fontName=FONT,
                fontSize=size,
                leading=size * 1.15,
                textColor=colors.HexColor("#263445"),
            ),
        )
        _, used = paragraph.wrap(max(1, width), 10000)
        if used <= height or size < 0.1:
            break
        size *= 0.9
    paragraph.drawOn(canvas, x, y + height - used)


def event_columns(events: list[dict]) -> list[tuple[dict, int, int]]:
    """Assign simultaneous events to separate columns in each connected overlap cluster."""
    result, cluster, ends = [], [], []
    for event in sorted(events, key=lambda item: (item["start"], item["end"], item["id"])):
        start, end = datetime.fromisoformat(event["start"]), datetime.fromisoformat(event["end"])
        if ends and start >= max(ends):
            result.extend((item, column, len(ends)) for item, column in cluster)
            cluster, ends = [], []
        column = next(
            (index for index, previous in enumerate(ends) if previous <= start), len(ends)
        )
        if column == len(ends):
            ends.append(end)
        else:
            ends[column] = end
        cluster.append((event, column))
    result.extend((item, column, len(ends)) for item, column in cluster)
    return result


def render_timetable_pdf(
    title: str, settings: dict, events: list[dict], displayed_day: date | None = None
) -> bytes:
    """Draw one landscape A4 week with subtle subject fills, breaks and no dates.

    Parameters
    ----------
    title, settings, events, displayed_day
        Server-resolved title, annual grid, authorized segments and displayed date for holidays.

    Returns
    -------
    bytes
        An in-memory, single-page PDF with searchable text.
    """
    output = BytesIO()
    page_width, page_height = landscape(A4)
    canvas = Canvas(output, pagesize=landscape(A4))
    canvas.setTitle(title)
    left, bottom, top = 54, 24, page_height - 70
    width, height = page_width - left - 24, top - bottom
    days = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]
    count = 6 if settings["saturday"] else 5
    day_width = width / count
    start = settings["day_start"] // 3600 * 3600
    end = ((settings["day_end"] + 3599) // 3600) * 3600

    def ordinate(seconds: int) -> float:
        """Map seconds after midnight to the vertical page coordinate."""
        return top - (seconds - start) / (end - start) * height

    fitted_text(canvas, [title], left, top + 32, width, 23, 15)
    for index in range(count):
        x = left + index * day_width
        fitted_text(canvas, [days[index]], x + 6, top + 8, day_width - 12, 14, 9)
        day = (
            displayed_day - timedelta(days=displayed_day.weekday()) + timedelta(days=index)
            if displayed_day
            else None
        )
        holiday = next(
            (
                item
                for item in settings.get("holidays", [])
                if day
                and date.fromisoformat(item["start"]) <= day <= date.fromisoformat(item["end"])
            ),
            None,
        )
        if holiday:
            canvas.setFillColor(colors.HexColor("#F3F4F6"))
            canvas.rect(x, bottom, day_width, height, fill=1, stroke=0)
            fitted_text(canvas, [holiday["name"]], x + 6, bottom, day_width - 12, height - 8, 8)
            continue
        for pause in [
            *settings["breaks"],
            {
                "start": settings.get("lunch_start", 43200),
                "end": settings.get("lunch_end", 50400),
                "self": True,
            },
        ]:
            high, low = ordinate(pause["start"]), ordinate(pause["end"])
            canvas.setFillColor(colors.HexColor("#F3F4F6"))
            canvas.rect(x, low, day_width, high - low, fill=1, stroke=0)
            fitted_text(
                canvas,
                ["Self" if pause.get("self") else "Pause"],
                x + 4,
                low + 1,
                day_width - 8,
                max(1, high - low - 2),
                6,
            )
    canvas.setLineWidth(0.25)
    canvas.setStrokeColor(colors.HexColor("#DEE2E7"))
    for index in range(count + 1):
        x = left + index * day_width
        canvas.line(x, bottom, x, top)
    for seconds in range(start, end + 1, 3600):
        y = ordinate(seconds)
        canvas.line(left, y, left + width, y)
        fitted_text(canvas, [f"{seconds // 3600:02}:00"], 12, y - 5, 38, 10, 7)
    for weekday in range(count):
        daily = [
            event
            for event in events
            if datetime.fromisoformat(event["start"]).weekday() == weekday
            and event["kind"] != "kholle"
            and event.get("target_kind") != "kholles"
        ]
        for event, column, columns in event_columns(daily):
            begins, finishes = (datetime.fromisoformat(event[key]) for key in ("start", "end"))
            high = ordinate(begins.hour * 3600 + begins.minute * 60 + begins.second)
            midnight = begins.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
            low = ordinate(int((finishes.replace(tzinfo=None) - midnight).total_seconds()))
            block_width = day_width / columns - 4
            x = left + weekday * day_width + column * day_width / columns + 2
            color = colors.HexColor(event["color"])
            canvas.setFillColor(colors.Color(*[0.88 + 0.12 * value for value in color.rgb()]))
            canvas.roundRect(x, low + 1, block_width, high - low - 2, 3, fill=1, stroke=0)
            canvas.setFillColor(color)
            canvas.rect(x, low + 3, 2, max(1, high - low - 6), fill=1, stroke=0)
            subject = event.get("subject_label") if event.get("subject_id") else event["title"]
            kind = {"course": "Cours", "td": "TD", "tp": "TP"}[event["kind"]]
            fitted_text(
                canvas,
                [f"{subject} · {kind}", audience_label(event), event["teacher"]],
                x + 6,
                low + 3,
                max(1, block_width - 10),
                max(1, high - low - 6),
            )
    canvas.showPage()
    canvas.save()
    return output.getvalue()
