"""Measured performance regression budgets with correctness assertions."""

from collections.abc import Callable
from time import perf_counter

import pytest

from app.services.search import prepare_name, rank_prepared_names

pytestmark = pytest.mark.perf


@pytest.mark.parametrize("count", [2000, 10000])
def test_search_ranking_latency(count: int, record_property: Callable[[str, object], None]) -> None:
    """Keep top-result correctness while measuring repeated large candidate ranking."""
    names = {i: prepare_name("Alpha", "Specimen") for i in range(count)}
    names[count] = prepare_name("Exemple", "Fictif")
    samples = []
    for _ in range(6):
        start = perf_counter()
        result = rank_prepared_names("exemple ficto", names, 20)
        samples.append(perf_counter() - start)
        assert result[0] == count
    p95 = max(samples[1:])
    record_property("p95_seconds", p95)
    record_property("accounts", count)
    assert p95 < 2
