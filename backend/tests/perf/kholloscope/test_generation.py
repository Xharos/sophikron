"""Real small-model CP-SAT runtime with exact annual-volume checks."""

import threading
from collections import Counter
from collections.abc import Callable
from time import perf_counter

import pytest

from app.services.kholloscope_solver import generate

pytestmark = pytest.mark.perf


def test_generation_budget_and_exact_volumes(
    solver_input: dict,
    record_property: Callable[[str, object], None],
) -> None:
    """A bounded real solve must return exact quotas rather than a fast partial schedule."""
    start = perf_counter()
    result = generate(solver_input, {"time_limit": 5}, lambda _message: None, threading.Event())
    elapsed = perf_counter() - start
    assert len(result["template"]) == 8
    assert Counter((s["track"], s["subject_id"]) for s in result["sessions"]) == Counter(
        {(group, subject): 2 for group in (1, 2) for subject in range(1, 5)}
    )
    record_property("elapsed_seconds", elapsed)
    assert elapsed < 10
