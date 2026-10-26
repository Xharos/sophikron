"""Partition balancing, complete coverage and khôlle size contracts."""

from collections import Counter
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.schemas.groups import GroupDraft, PartitionGenerate, PartitionKind, PartitionSave
from app.services.errors import AuthError
from app.services.groups import generate_groups, validate_groups


@pytest.mark.parametrize("kind", ["halves", "thirds", "kholles"])
@pytest.mark.parametrize("size", [2, 3, 4, 5])
@pytest.mark.parametrize("count", [1, 2, 7, 31, 100])
def test_generation_covers_pupils_and_balances(kind: PartitionKind, size: int, count: int) -> None:
    """Cover every pupil once and respect generation targets even for remainders."""
    pupils = list(range(1, count + 1))
    groups = generate_groups(kind, pupils, size)
    assert Counter(pupil for group in groups for pupil in group.student_ids) == Counter(pupils)
    sizes = [len(group.student_ids) for group in groups]
    if kind == "kholles":
        assert sizes == [size] * (count // size) + ([count % size] if count % size else [])
    else:
        assert max(sizes) - min(sizes) <= 1
    validate_groups(kind, groups, set(pupils), size)
    assert pupils == list(range(1, count + 1))


def test_generation_shuffles_without_linking_partition_draws() -> None:
    """Each generation invokes its own shuffle and leaves the input roster intact."""
    pupils = list(range(1, 10))
    with patch("app.services.groups.secrets.SystemRandom") as random:
        random.return_value.shuffle.side_effect = lambda values: values.reverse()
        halves = generate_groups("halves", pupils, 3)
        thirds = generate_groups("thirds", pupils, 3)
    assert halves[0].student_ids == [9, 7, 5, 3, 1]
    assert thirds[0].student_ids == [9, 6, 3]
    assert random.return_value.shuffle.call_count == 2
    assert pupils == list(range(1, 10))


def test_large_roster_positions_stay_inside_contract() -> None:
    """Keep every generated bubble valid at the accepted maximum roster size."""
    groups = generate_groups("kholles", list(range(1, 2001)), 2)
    assert len(groups) == 1000
    validate_groups("kholles", groups, set(range(1, 2001)), 2)


@pytest.mark.parametrize("kind", ["halves", "thirds", "kholles"])
def test_generation_preserves_archived_assignments(kind: PartitionKind) -> None:
    """Regenerate only non-archived pupils and retain every archived group's identity."""
    pupils = list(range(1, 13))
    previous = generate_groups(kind, pupils, 3)
    archived = set(previous[-1].student_ids)
    result = generate_groups(kind, pupils, 3, archived, previous)
    for pupil in archived:
        assert (
            next(group.number for group in result if pupil in group.student_ids)
            == previous[-1].number
        )
    assert Counter(pupil for group in result for pupil in group.student_ids) == Counter(pupils)
    validate_groups(kind, result, set(pupils), 3, archived)


def test_archived_only_groups_and_manual_moves_do_not_affect_sizes() -> None:
    """Keep numbered archived-only groups while permitting archived transfers and reactivation."""
    groups = [
        GroupDraft(number=1, x=0, y=0, student_ids=[1, 2, 3, 7]),
        GroupDraft(number=2, x=300, y=0, student_ids=[4, 5, 6]),
        GroupDraft(number=15, x=600, y=0, student_ids=[8]),
    ]
    validate_groups("kholles", groups, set(range(1, 9)), 3, {7, 8})
    with pytest.raises(AuthError):
        validate_groups("kholles", groups, set(range(1, 9)), 3, {8})
    groups[0].student_ids.remove(7)
    groups[2].student_ids.append(7)
    validate_groups("kholles", groups, set(range(1, 9)), 3, {7, 8})
    validate_groups("kholles", groups, set(range(1, 9)), 3, {7})


@pytest.mark.parametrize("kind", ["halves", "thirds", "kholles"])
def test_all_archived_rosters_remain_editable(kind: PartitionKind) -> None:
    """Retain valid archived assignments even when there are no effective pupils."""
    pupils = [1, 2, 3, 4]
    archived = set(pupils)
    groups = generate_groups(kind, pupils, 3, archived)
    validate_groups(kind, groups, archived, 3, archived)
    assert {pupil for group in groups for pupil in group.student_ids} == archived


@pytest.mark.parametrize("size", [0, 1, 6, 3.5, True, "3"])
def test_generation_size_rejects_out_of_range_and_coercion(size: object) -> None:
    """Only integer targets between two and five are accepted from clients."""
    with pytest.raises(ValidationError):
        PartitionGenerate(expected_revision=None, roster_ids=[1], target_size=size)


@pytest.mark.parametrize("assignments", [[[1], [1, 2]], [[1], []], [[1], [99]], [[1, 2], [3]]])
def test_incomplete_duplicate_and_foreign_pupils_rejected(assignments: list[list[int]]) -> None:
    """Never accept a duplicated pupil or an incomplete or foreign roster."""
    groups = [
        GroupDraft(number=i + 1, x=0, y=0, student_ids=ids) for i, ids in enumerate(assignments)
    ]
    with pytest.raises(AuthError) as failure:
        validate_groups("halves", groups, {1, 2})
    assert failure.value.status == 422


def test_manual_balance_and_kholle_limit() -> None:
    """A five/one split requires a target of five and is invalid for a target of three."""
    groups = [
        GroupDraft(number=1, x=0, y=0, student_ids=[1, 2, 3, 4, 5]),
        GroupDraft(number=2, x=300, y=0, student_ids=[6]),
    ]
    validate_groups("kholles", groups, set(range(1, 7)), 5)
    with pytest.raises(AuthError):
        validate_groups("kholles", groups, set(range(1, 7)), 3)
    with pytest.raises(AuthError):
        validate_groups("halves", groups, set(range(1, 7)))
    groups[0].student_ids.append(6)
    groups[1].student_ids = []
    with pytest.raises(AuthError):
        validate_groups("kholles", groups, set(range(1, 7)))


@pytest.mark.parametrize(
    "target,sizes,valid",
    [
        (3, [3] * 15, True),
        (3, [5, 1] + [3] * 13, False),
        (3, [4, 2] + [3] * 13, False),
        (3, [3] * 15 + [1], True),
        (3, [3] * 14 + [2, 2], False),
        (3, [3] * 15 + [2], True),
        (3, [3, 2, 2], False),
        (3, [3, 3, 1], True),
        (5, [5] * 9, True),
        (2, [2] * 22 + [1], True),
        (4, [4] * 11 + [1], True),
        (3, [1, 3, 3], True),
    ],
)
def test_kholles_require_target_with_only_one_remainder(
    target: int, sizes: list[int], valid: bool
) -> None:
    """Preserve the chosen size and allow exactly one remainder group at any position."""
    groups = []
    next_pupil = 1
    for number, size in enumerate(sizes, start=1):
        groups.append(
            GroupDraft(
                number=number, x=0, y=0, student_ids=list(range(next_pupil, next_pupil + size))
            )
        )
        next_pupil += size
    pupils = set(range(1, next_pupil))
    if valid:
        validate_groups("kholles", groups, pupils, target)
    else:
        with pytest.raises(AuthError) as failure:
            validate_groups("kholles", groups, pupils, target)
        assert failure.value.status == 422


def test_invalid_structure_and_empty_roster() -> None:
    """Reject absent pupils, invalid numbering, extra groups and arbitrary labels."""
    with pytest.raises(AuthError):
        generate_groups("halves", [], 3)
    groups = generate_groups("thirds", [1, 2, 3], 3)
    with pytest.raises(AuthError):
        validate_groups("halves", groups, {1, 2, 3})
    groups[1].number = 1
    with pytest.raises(AuthError):
        validate_groups("thirds", groups, {1, 2, 3})
    with pytest.raises(ValidationError):
        PartitionSave(expected_revision=None, roster_ids=[1], groups=[])
