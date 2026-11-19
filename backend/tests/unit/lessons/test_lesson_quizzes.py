"""Course practice shuffling and protection of the answer key."""

from app.services.lesson_quizzes import public_card, shuffled


def test_replay_uses_a_different_order_when_possible() -> None:
    """A two-card replay must differ from the previous pass in the same view."""
    assert shuffled(2, [0, 1]) == [1, 0]
    assert shuffled(2, [1, 0]) == [0, 1]
    assert shuffled(1, [0]) == [0]


def test_course_card_omits_correction() -> None:
    """Expose choices but keep their correct subset in the frozen server copy."""
    card = public_card(
        {
            "title": "Circuit",
            "kind": "choice",
            "rule": {"options": ["A", "B"], "correct": [1]},
        }
    )
    assert card == {"title": "Circuit", "kind": "choice", "options": ["A", "B"]}
