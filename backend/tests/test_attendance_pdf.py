"""Verify attendance layout, pagination and safe identity rendering in actual PDFs."""

from datetime import UTC, datetime
from io import BytesIO

import pytest
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4

from app.services.attendance_pdf import (
    AttendanceGroup,
    AttendanceStudent,
    group_label,
    render_attendance_pdf,
)

GENERATED = datetime(2026, 10, 29, 12, 34, 56, tzinfo=UTC)


@pytest.mark.parametrize(
    "variant,columns", [("halves", 2), ("thirds", 3), ("kholles", 3), ("custom", 3)]
)
def test_group_tables_paginate_with_parallel_headings(variant: str, columns: int) -> None:
    """Repeat side-by-side headings over pages and render every pupil exactly once."""
    groups = [
        AttendanceGroup(
            f"Groupe {index}",
            [
                AttendanceStudent(f"Élève-{index}-{pupil:03}", "Jean", archived=pupil == 89)
                for pupil in range(90)
            ],
        )
        for index in range(columns)
    ]
    pdf = PdfReader(
        BytesIO(
            render_attendance_pdf(
                "PTSI",
                "#4361EE",
                [],
                "Enseignant",
                GENERATED,
                variant,
                groups,
            )
        )
    )
    assert len(pdf.pages) > 1
    for page in pdf.pages:
        text = page.extract_text()
        for index in range(columns):
            assert f"Groupe {index}" in text
    text = "\n".join(page.extract_text() for page in pdf.pages)
    for index in range(columns):
        for pupil in range(90):
            assert text.count(f"ÉLÈVE-{index}-{pupil:03}") == 1
    assert "Remarque" not in text


def test_global_contains_assignments_and_escaped_names() -> None:
    """Export saved group labels alongside safely rendered identities and a blank remark."""
    pdf = PdfReader(
        BytesIO(
            render_attendance_pdf(
                "PTSI",
                "#4361EE",
                [AttendanceStudent("<Nom>", "Jean", assignments=("A", "X", "01"))],
                "Enseignant",
                GENERATED,
                "global",
            )
        )
    )
    text = pdf.pages[0].extract_text()
    for value in ("<NOM>", "Demi", "Tiers", "Khôlle", "Remarque", "A", "X", "01"):
        assert value in text
    assert [group_label(kind, 1) for kind in ("halves", "thirds", "kholles")] == ["A", "X", "01"]


@pytest.mark.parametrize("variant", ["halves", "thirds", "kholles", "custom"])
def test_empty_group_export_is_explicit(variant: str) -> None:
    """Return a readable empty state when no saved composition exists."""
    pdf = PdfReader(
        BytesIO(
            render_attendance_pdf(
                "PTSI",
                "#4361EE",
                [],
                "Enseignant",
                GENERATED,
                variant,
            )
        )
    )
    assert "Aucun groupe enregistré." in pdf.pages[0].extract_text()


def render(students: list[AttendanceStudent]) -> PdfReader:
    """Parse an in-memory synthetic export, without creating a persistent roster file."""
    return PdfReader(
        BytesIO(
            render_attendance_pdf(
                "PTSI",
                "#4361EE",
                students,
                "DUPONT Émilie",
                GENERATED,
            )
        )
    )


def test_standard_roster_fits_one_a4_page_with_private_generation_details() -> None:
    """Keep 45 pupils on one A4 page with all requested headings and Paris time."""
    pdf = render([AttendanceStudent(f"Élève {i:02}", "jean-pierre") for i in range(45)])
    assert len(pdf.pages) == 1
    page = pdf.pages[0]
    assert float(page.mediabox.width) == pytest.approx(A4[0], abs=0.01)
    assert float(page.mediabox.height) == pytest.approx(A4[1], abs=0.01)
    text = page.extract_text()
    assert "PTSI" in text and "NOM" in text and "Prénom" in text and "Remarque" in text
    assert text.count("Jean-Pierre") == 45
    assert "ÉLÈVE 00" in text and "ÉLÈVE 44" in text
    assert "DUPONT Émilie" in text and "29/10/2026 à 13:34:56" in text
    assert pdf.metadata.author == "DUPONT Émilie"
    operators = page.get_contents().operations
    # Exact promotion title color and alternating light-grey row backgrounds are drawn.
    fills = [tuple(float(value) for value in operands) for operands, op in operators if op == b"rg"]
    assert any(color == pytest.approx((67 / 255, 97 / 255, 238 / 255)) for color in fills)
    assert any(color == pytest.approx((246 / 255,) * 3) for color in fills)


def test_large_roster_repeats_title_columns_and_footer_on_every_page() -> None:
    """Paginate without losing pupils or generation metadata."""
    pdf = render([AttendanceStudent(f"Élève {i:03}", "Camille") for i in range(125)])
    assert len(pdf.pages) >= 3
    texts = [page.extract_text() for page in pdf.pages]
    assert sum(text.count("Camille") for text in texts) == 125
    for text in texts:
        assert all(
            value in text
            for value in (
                "PTSI",
                "NOM",
                "Prénom",
                "Remarque",
                "DUPONT Émilie",
                "29/10/2026 à 13:34:56",
            )
        )


def test_archived_pupils_sort_last_with_struck_through_names_and_safe_markup() -> None:
    """Sort both sections alphabetically, preserve accents and escape paragraph markup."""
    pdf = render(
        [
            AttendanceStudent("Albert", "élise", archived=True),
            AttendanceStudent("Zulu", "marie"),
            AttendanceStudent("Éclair", "jean-luc"),
            AttendanceStudent("Durand", "<b>léa & zoé</b>"),
        ]
    )
    page = pdf.pages[0]
    text = page.extract_text()
    assert text.index("DURAND") < text.index("ÉCLAIR") < text.index("ZULU") < text.index("ALBERT")
    assert "Élise" in text and "Jean-Luc" in text and "<B>Léa & Zoé</B>" in text
    lines = [operands for operands, op in page.get_contents().operations if op == b"l"]
    # Two additional strokes cross the archived pupil's surname and first name.
    plain = render(
        [
            AttendanceStudent("Albert", "élise"),
            AttendanceStudent("Zulu", "marie"),
            AttendanceStudent("Éclair", "jean-luc"),
            AttendanceStudent("Durand", "<b>léa & zoé</b>"),
        ]
    )
    plain_lines = [op for _, op in plain.pages[0].get_contents().operations if op == b"l"]
    assert len(lines) == len(plain_lines) + 2


def test_empty_roster_and_long_names_render_without_overflow() -> None:
    """Handle empty promotions and wrap long identity fields instead of clipping them."""
    assert len(render([]).pages) == 1
    last_name = "Trèslongnom" * 10
    first_name = "Marie-" * 15
    pdf = render([AttendanceStudent(last_name, first_name)])
    text = "".join(pdf.pages[0].extract_text().split())
    assert last_name.upper() in text and first_name.title() in text


def test_account_badges_distinguish_active_pending_and_archived_accounts() -> None:
    """Draw one green badge for an active account and red badges for other states."""
    pdf = render(
        [
            AttendanceStudent("Active", "Alice", active=True),
            AttendanceStudent("Pending", "Benoît"),
            AttendanceStudent("Archived", "Camille", archived=True),
        ]
    )
    fills = [
        tuple(float(value) for value in operands)
        for operands, operation in pdf.pages[0].get_contents().operations
        if operation == b"rg"
    ]
    green = (22 / 255, 128 / 255, 60 / 255)
    red = (198 / 255, 40 / 255, 40 / 255)
    assert sum(color == pytest.approx(green, abs=1e-6) for color in fills) == 1
    assert sum(color == pytest.approx(red, abs=1e-6) for color in fills) == 2
    operations = pdf.pages[0].get_contents().operations
    assert sum(op == b"c" for _, op in operations) == 12  # Four Bezier arcs per circle.
    assert "●" not in pdf.pages[0].extract_text()


def test_global_omits_undefined_partitions_and_colors_only_letter_groups() -> None:
    """Keep only defined group columns and use five distinct letter colors."""
    from app.services.attendance_pdf import GROUP_COLORS

    assert len(set(GROUP_COLORS.values())) == 5
    assert "01" not in GROUP_COLORS
    pdf = PdfReader(BytesIO(render_attendance_pdf(
        "PTSI", "#4361EE", [AttendanceStudent("Nom", "Jean", assignments=("A", "", ""))],
        "Enseignant", GENERATED, "global", defined_partitions=["halves"],
    )))
    text = pdf.pages[0].extract_text()
    assert "Demi" in text and "Tiers" not in text and "Khôlle" not in text
    assert "Remarque" in text


def test_group_tables_have_gutters_and_no_unused_custom_columns() -> None:
    """Separate mini tables horizontally and vertically, fitting columns to custom groups."""
    from app.services.attendance_pdf import grouped_tables

    groups = [AttendanceGroup(f"Groupe {index}", [AttendanceStudent("Nom", "Jean")])
              for index in range(15)]
    story = grouped_tables(groups, 3, 530)
    assert len(story) == 10  # Five rows, each followed by vertical whitespace.
    assert story[0]._colWidths[1::2] == [12, 12]
    single = grouped_tables(groups[:1], 1, 530)[0]
    assert single._colWidths == [530]
