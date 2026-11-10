"""Identity cache isolation, expiry and deterministic search contracts."""

from unittest.mock import Mock

import pytest

from app.services.search import NameSearchCache, prepare_name, rank_names, rank_prepared_names


def test_prepare_name_preserves_display_and_normalizes_search() -> None:
    """Keep original spelling while expanding accents for matching."""
    result = prepare_name("Éléonore", "D'Œuvre")
    assert result.first_name == "Éléonore"
    assert result.last_name == "D'Œuvre"
    assert result.text == "eleonore d oeuvre"
    assert "doeuvreeleonore" in result.compact_forms


@pytest.mark.parametrize("query", ["", " ", "a", "123"])
def test_short_search_returns_no_identity(query: str) -> None:
    """Do not disclose matches for uninformative normalized queries."""
    assert rank_names(query, [(1, "Alice", "Martin")], 20) == []


def test_ranking_is_bounded_and_uses_only_supplied_candidates() -> None:
    """Exact matches lead and the caller's authorization scope is preserved."""
    names = [(1, "Alice", "Martin"), (2, "Alix", "Martin"), (3, "Bob", "Durand")]
    assert rank_names("Alice Martin", names, 1) == [1]
    assert rank_names("Alice Martin", [], 20) == []
    assert rank_prepared_names("Alice", {1: prepare_name("Alice", "Martin")}, 0) == []


def test_cache_reuses_matching_ciphertext_and_clear_releases_entries() -> None:
    """Reuse matching names but decrypt again after explicit shutdown cleanup."""
    cipher = Mock()
    cipher.decrypt.side_effect = ["Alice", "Martin", "Alice", "Martin"]
    cache = NameSearchCache()
    candidates = [(1, b"first", b"last")]
    first = cache.prepare(candidates, cipher)
    assert cache.prepare(candidates, cipher) == first
    assert cipher.decrypt.call_count == 2
    assert cache.prepare([], cipher) == {}
    cache.clear()
    assert cache.prepare(candidates, cipher) == first
    assert cipher.decrypt.call_count == 4


def test_cache_expires_at_deadline() -> None:
    """Expire at the TTL boundary even when ciphertext has not changed."""
    clock = Mock(return_value=0)
    cipher = Mock()
    cipher.decrypt.side_effect = ["Alice", "Martin"] * 2
    cache = NameSearchCache(clock=clock, ttl_seconds=10)
    candidates = [(1, b"first", b"last")]
    cache.prepare(candidates, cipher)
    clock.return_value = 9
    cache.prepare(candidates, cipher)
    assert cipher.decrypt.call_count == 2
    clock.return_value = 10
    cache.prepare(candidates, cipher)
    assert cipher.decrypt.call_count == 4


def test_cache_revalidates_changed_identity() -> None:
    """Never serve a stale display name after the database ciphertext changes."""
    cipher = Mock()
    cipher.decrypt.side_effect = ["Alice", "Martin", "Alice", "Durand"]
    cache = NameSearchCache()
    cache.prepare([(1, b"a", b"b")], cipher)
    assert cache.prepare([(1, b"a", b"c")], cipher)[1].last_name == "Durand"


def test_capacity_evicts_the_least_recent_identity() -> None:
    """An evicted entry must be decrypted again rather than retained beyond capacity."""
    cipher = Mock()
    cipher.decrypt.side_effect = ["Alice", "Martin", "Bob", "Durand", "Alice", "Martin"]
    cache = NameSearchCache(max_entries=1)
    cache.prepare([(1, b"a", b"b")], cipher)
    cache.prepare([(2, b"c", b"d")], cipher)
    cache.prepare([(1, b"a", b"b")], cipher)
    assert cipher.decrypt.call_count == 6


def test_decryption_failure_is_not_cached() -> None:
    """Propagate corrupted ciphertext errors and allow a subsequent valid lookup."""
    cipher = Mock()
    cipher.decrypt.side_effect = ValueError("corrupt")
    cache = NameSearchCache()
    with pytest.raises(ValueError, match="corrupt"):
        cache.prepare([(1, b"a", b"b")], cipher)
    cipher.decrypt.side_effect = ["Alice", "Martin"]
    assert cache.prepare([(1, b"a", b"b")], cipher)[1].first_name == "Alice"
