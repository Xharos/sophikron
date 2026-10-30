"""Verify private view filtering and the actual searchable landscape PDF."""

from datetime import date
from io import BytesIO

import pytest
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4, landscape

from app.services.errors import AuthError
from app.services.timetable_pdf import event_columns, render_timetable_pdf, select_view


def event(identifier: str, **changes: object) -> dict:
    """Return a decorated synthetic Monday session with optional field overrides."""
    return {
        "id": identifier,
        "year_id": 1,
        "promotion_id": 1,
        "start": "2026-11-02T08:00:00+01:00",
        "end": "2026-11-02T09:00:00+01:00",
        "kind": "td",
        "subject_id": 1,
        "subject_label": "Mathématiques",
        "title": "Titre",
        "teacher": "DUPONT Émilie",
        "color": "#4361EE",
        "target_kind": "promotion",
        **changes,
    }


def board() -> dict:
    """Build intersecting partitions and a custom audience with a single shared pupil."""
    return {
        "years": [{"id": 1}],
        "members": [
            {
                "id": 1,
                "name": "Élève",
                "roles": ["user"],
                "assignments": [
                    {"promotion_id": 1, "kind": kind, "number": 1}
                    for kind in ("halves", "thirds", "custom")
                ],
            }
        ],
        "groups": [
            {"kind": kind, "number": 1, "student_ids": [1], "name": "Option"}
            for kind in ("halves", "thirds", "custom")
        ],
        "events": [
            event("all"),
            event("A", target_kind="halves", target_number=1),
            event("B", target_kind="halves", target_number=2),
            event("X", target_kind="thirds", target_number=1),
            event("option", target_kind="custom", target_number=1),
            event("kh", kind="kholle"),
            event("kh-target", target_kind="kholles"),
            event("next", start="2026-11-09T08:00:00+01:00"),
            event("other", year_id=2),
        ],
    }


def test_selected_week_and_intersecting_audiences_exclude_all_kholles() -> None:
    """Match the UI's actual membership filter, including common and intersecting lessons."""
    data = board()
    _, suffix, events = select_view(data, 1, date(2026, 11, 4), "halves-1")
    assert suffix == "Demi-groupe A"
    assert {item["id"] for item in events} == {"all", "A", "X", "option"}
    assert len(select_view(data, 1, date(2026, 11, 4), "promotion")[2]) == 5
    assert select_view(data, 1, date(2026, 11, 4), "custom-1")[1] == "Option"
    assert select_view(data, 1, date(2026, 11, 4), "student-1")[1] == "Élève"
    assert [item["id"] for item in select_view(data, 1, date(2026, 11, 4), "unassigned")[2]] == [
        "all"
    ]
    for node in ("halves-9", "student-9"):
        with pytest.raises(AuthError):
            select_view(data, 1, date(2026, 11, 4), node)
    with pytest.raises(AuthError):
        select_view(data, 9, date(2026, 11, 4), "promotion")


def test_overlap_columns_reuse_space_after_each_cluster() -> None:
    """Keep simultaneous blocks side by side and give isolated lessons the full day width."""
    columns = event_columns(
        [
            event("a"),
            event("b"),
            event("later", start="2026-11-02T09:00:00+01:00", end="2026-11-02T10:00:00+01:00"),
        ]
    )
    assert [(index, count) for _, index, count in columns] == [(0, 2), (1, 2), (0, 1)]


def test_holiday_label_replaces_pauses_and_empty_week_stays_one_page() -> None:
    """Match closed-day backgrounds without printing holiday dates."""
    settings = {"day_start": 28800, "day_end": 64800, "saturday": False, "breaks": [],
                "holidays": [{"name": "Vacances", "start": "2026-11-02", "end": "2026-11-06"}]}
    pdf = PdfReader(BytesIO(render_timetable_pdf("Agenda", settings, [], date(2026, 11, 4))))
    text = pdf.pages[0].extract_text()
    assert len(pdf.pages) == 1
    assert text.count("Vacances") == 5
    assert "Self" not in text and "2026" not in text


@pytest.mark.parametrize("saturday", [False, True])
def test_landscape_page_contains_labels_breaks_and_no_dates_or_kholles(saturday: bool) -> None:
    """Render one A4 page with all required names and no exact dates or session hours."""
    settings = {
        "day_start": 28800,
        "day_end": 64800,
        "saturday": saturday,
        "breaks": [{"start": 36000, "end": 37200}],
    }
    pdf = PdfReader(
        BytesIO(
            render_timetable_pdf(
                "PTSI - Demi-groupe A",
                settings,
                [
                    event("one", target_kind="halves", target_number=1),
                    event("two", kind="tp", subject_label="Physique", teacher="MARTIN Jean"),
                    event("kh", kind="kholle", teacher="Excluded"),
                ],
            )
        )
    )
    assert len(pdf.pages) == 1
    page = pdf.pages[0]
    assert float(page.mediabox.width) == pytest.approx(landscape(A4)[0], abs=0.01)
    text = page.extract_text()
    for label in (
        "Lundi",
        "Vendredi",
        "08:00",
        "18:00",
        "Mathématiques",
        "TD",
        "TP",
        "Groupe A",
        "DUPONT Émilie",
        "MARTIN Jean",
        "Pause",
        "Self",
    ):
        assert "".join(label.split()) in "".join(text.split())
    assert ("Samedi" in text) is saturday
    assert "2026" not in text and "Excluded" not in text
    assert "09:00" in text  # Time axis remains, session time ranges are absent.
