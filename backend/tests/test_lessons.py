"""Pure validation and inheritance tests for course content and date policies."""

from datetime import date
from typing import get_args

import pytest
from pydantic import ValidationError

from app.models.lessons import LessonElement
from app.schemas.lessons import ElementFields, LessonFields, LessonIcon, PromotionGrant, youtube_id
from app.schemas.site import SubjectFields
from app.services.errors import AuthError
from app.services.lessons import effective_period, school_year_period


@pytest.mark.parametrize("icon", get_args(LessonIcon))
def test_subject_accepts_catalogue_icons(icon: str) -> None:
    """Accept every supported subject icon for both new and existing identities."""
    assert SubjectFields(name="Matière", icon=icon).icon == icon


@pytest.mark.parametrize("icon", ["unknown", "<svg onload=alert(1)>", "", "fa-atom"])
def test_subject_rejects_icons_outside_catalogue(icon: str) -> None:
    """Keep subject icons restricted to named bundled assets."""
    with pytest.raises(ValidationError):
        SubjectFields(name="Matière", icon=icon)


def test_only_media_has_dates_and_structural_ancestors_do_not_restrict_content() -> None:
    """Ignore obsolete structural dates and treat always-visible media independently."""
    inherited = (date(2026, 9, 1), date(2026, 12, 31), "Legacy section")
    for kind in ["section", "subsection", "text", "table"]:
        element = LessonElement(
            kind=kind, schedule_mode="range", starts_on=inherited[0], ends_on=inherited[1]
        )
        assert effective_period(element, inherited) == (None, None, None)
    for kind in ["file", "youtube"]:
        element = LessonElement(
            kind=kind, title="Resource", schedule_mode="from", starts_on=date(2027, 1, 10)
        )
        assert effective_period(element, inherited) == (date(2027, 1, 10), None, "Resource")
        element.schedule_mode = "inherit"
        assert effective_period(element, inherited) == (None, None, None)


@pytest.mark.parametrize(
    "values",
    [
        {"schedule_mode": "inherit", "starts_on": "2026-09-01"},
        {"schedule_mode": "from"},
        {"schedule_mode": "from", "starts_on": "2026-09-01", "ends_on": "2027-08-31"},
        {"schedule_mode": "range", "starts_on": "2026-09-01"},
        {"schedule_mode": "range", "starts_on": "2027-09-01", "ends_on": "2027-08-31"},
        {"schedule_mode": "always"},
    ],
)
def test_reject_incomplete_or_inconsistent_schedules(values: dict[str, object]) -> None:
    """Accept no silent fallback when a caller supplies an invalid explicit restriction."""
    with pytest.raises(ValidationError):
        ElementFields.model_validate(values)


def test_school_year_defaults_and_invalid_last_year() -> None:
    """Grant September through August inclusively, never an invalid June or overflow date."""
    assert school_year_period(2026) == (date(2026, 9, 1), date(2027, 8, 31))
    with pytest.raises(AuthError):
        school_year_period(9999)
    assert ElementFields().schedule_mode == "inherit"
    for values in (
        {"starts_on": "2026-09-01"},
        {"starts_on": "2027-09-01", "ends_on": "2027-08-31"},
    ):
        with pytest.raises(ValidationError):
            PromotionGrant(expected_version=0, **values)


@pytest.mark.parametrize(
    "url",
    [
        "https://youtu.be/abcdefghijk",
        "https://www.youtube.com/watch?v=abcdefghijk&t=12",
        "https://youtube.com/shorts/abcdefghijk",
        "https://m.youtube.com/embed/abcdefghijk",
    ],
)
def test_youtube_accepts_only_canonical_video_identifiers(url: str) -> None:
    """Recognize supported URLs without making network requests or accepting arbitrary embeds."""
    assert youtube_id(url) == "abcdefghijk"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://youtube.com/watch?v=abcdefghijk",
        "https://youtube.com.attacker.test/watch?v=abcdefghijk",
        "https://youtube.com@attacker.test/watch?v=abcdefghijk",
        "https://user:password@youtube.com/watch?v=abcdefghijk",
        "https://youtube.com:443/watch?v=abcdefghijk",
        "https://youtu.be/abcdefghijk/extra",
        "https://youtube.com/watch?v=short",
        "https://youtube.com/watch?v=abcdefghijk&v=ABCDEFGHIJK",
        "<iframe src='evil'></iframe>",
    ],
)
def test_youtube_rejects_untrusted_hosts_schemes_and_markup(url: str) -> None:
    """Keep arbitrary URLs, credentials and HTML outside the course video contract."""
    with pytest.raises(ValueError):
        youtube_id(url)


def test_metadata_normalizes_names_and_rejects_css_and_ownership_fields() -> None:
    """Normalize title collisions while refusing untrusted CSS or an assigned creator."""
    data = LessonFields(title="  Mathématiques\t Ⅰ ", description="Programme", subject_id=1)
    assert data.title == "Mathématiques I" and data.subject_id == 1
    for values in ({"title": " "}, {"color": "red; background:url(evil)"}, {"creator_id": 5}):
        with pytest.raises(ValidationError):
            LessonFields.model_validate(
                {"title": "Maths", "description": "Cours", "subject_id": 1, **values}
            )


def test_normalization_cannot_bypass_database_text_limits() -> None:
    """Validate expanded Unicode before applying storage limits to titles and descriptions."""
    for values in ({"title": "ﬃ" * 160}, {"description": "ﬃ" * 2000}, {"title": 5}):
        with pytest.raises(ValidationError):
            LessonFields.model_validate(
                {"title": "Maths", "description": "Cours", "subject_id": 1, **values}
            )
