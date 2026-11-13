"""Automatic competency labels, natural order and modular parent reassignment."""

import pytest
from pydantic import ValidationError

from app.models.curricula import Competency
from app.schemas.curricula import CompetencyFields
from app.services.competency_codes import alphabetic, competency_codes


def nodes(count: int) -> list[Competency]:
    """Build ordered synthetic competencies without database access."""
    return [Competency(id=i, name=str(i), position=i) for i in range(1, count + 1)]


def test_competency_hierarchical_codes() -> None:
    """Number roots, children, grandchildren and deeper branches with alternating segments."""
    codes, ordered = competency_codes(nodes(6), [(1, 3), (3, 4), (4, 5), (3, 6)])
    assert codes == {1: "A", 2: "B", 3: "A.1", 4: "A.1.a", 5: "A.1.a.1", 6: "A.1.b"}
    assert ordered == [1, 3, 4, 5, 6, 2]


def test_competency_shared_node_has_one_code_and_detachment_recomputes_it() -> None:
    """Use the first shortest path and reassign a root label after complete detachment."""
    sample = nodes(4)
    assert competency_codes(sample, [(1, 3), (2, 3), (3, 4)])[0][3] == "A.1"
    assert competency_codes(sample, [(2, 3), (3, 4)])[0][3] == "B.1"
    assert competency_codes(sample, [(3, 4)])[0][3] == "C"
    assert competency_codes(sample, [(1, 3), (2, 4), (3, 4)])[0][4] == "B.1"


def test_competency_codes_continue_after_z_and_sort_numeric_siblings() -> None:
    """Keep Z before AA and child 2 before child 10."""
    assert alphabetic(26, uppercase=True) == "Z"
    assert alphabetic(27, uppercase=True) == "AA"
    codes, ordered = competency_codes(nodes(30), [(1, i) for i in range(2, 31)])
    assert codes[11] == "A.10" and ordered == list(range(1, 31))


def test_competency_manual_codes_are_not_accepted() -> None:
    """Prevent direct API clients from overriding generated labels."""
    with pytest.raises(ValidationError):
        CompetencyFields(name="Analyser", expected_version=0, code="Z")
