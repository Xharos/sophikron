"""Programme input boundaries and modular graph cycle detection."""

import pytest
from pydantic import ValidationError

from app.schemas.administration import PromotionCreate, PromotionSnapshot
from app.schemas.curricula import CompetencyFields, CurriculumFields
from app.services.curricula import validate_parents
from app.services.errors import AuthError


@pytest.mark.parametrize("parents", [[1], [2], [3], [1, 4]])
def test_reject_self_and_descendant_parents(parents: list[int]) -> None:
    """Prevent cycles even through multiple levels or shared descendants."""
    with pytest.raises(AuthError, match="cycle"):
        validate_parents(1, parents, [(1, 2), (2, 3), (4, 3)])


def test_allow_shared_child_and_detachment() -> None:
    """Permit multiple independent parents and complete detachment to a root."""
    validate_parents(3, [1, 2], [(1, 3), (2, 3)])
    validate_parents(3, [], [(1, 3), (2, 3)])


@pytest.mark.parametrize(
    "changes",
    [
        {"semester": 0},
        {"semester": 5},
        {"parent_ids": [1, 1]},
        {"parent_ids": [-1]},
        {"name": "  "},
        {"color": "red"},
        {"expected_version": -1},
        {"comment": "x" * 12001},
    ],
)
def test_competency_input_bounds(changes: dict[str, object]) -> None:
    """Reject invalid values before entering a transaction."""
    with pytest.raises(ValidationError):
        CompetencyFields.model_validate({"name": "Analyser", "expected_version": 0, **changes})


def test_optional_text_and_semester() -> None:
    """Allow simple root competencies without imposing SII's three levels."""
    data = CompetencyFields(name=" Analyser ", expected_version=0, comment=" ")
    assert data.name == "Analyser"
    assert data.semester is None and data.comment is None
    assert data.parent_ids == [] and data.color is None


def test_legacy_promotion_snapshot_remains_readable() -> None:
    """Keep old journal references readable without accepting old fields in current writes."""
    old = {"year": 2026, "identifier": "PT", "color": "#123456", "track_id": 7}
    assert PromotionSnapshot.model_validate(old).track_id == 7
    with pytest.raises(ValidationError):
        PromotionCreate.model_validate(old)


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "file:///programme.pdf", "https://a:b@example.org/p.pdf"]
)
def test_source_link_rejects_unsafe_schemes_and_credentials(url: str) -> None:
    """Only permit web links without embedded credentials."""
    with pytest.raises(ValidationError):
        CurriculumFields(title="Programme", subject_ids=[1], source_url=url)
