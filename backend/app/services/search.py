"""Bounded typo-tolerant identity ranking without a persistent plaintext index."""

import re
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from rapidfuzz.fuzz import WRatio
from rapidfuzz.process import extract

from app.core.identity import normalize_search
from app.core.security import IdentityCipher


@dataclass(frozen=True, slots=True)
class PreparedName:
    """Keep display spelling and reusable matching forms exclusively in process memory."""

    first_name: str
    last_name: str
    text: str
    compact_forms: tuple[str, ...]
    prefix_text: str


def prepare_name(first_name: str, last_name: str) -> PreparedName:
    """Normalize one identity once for repeated interactive keystrokes."""
    first, last = normalize_search(first_name), normalize_search(last_name)
    text = first + " " + last
    forms = tuple(value.replace(" ", "") for value in (first, last, text, last + " " + first))
    return PreparedName(first_name, last_name, text, forms, " ".join(forms))


class NameSearchCache:
    """Bound per-worker plaintext names by capacity/age, validating ciphertext on every use."""

    def __init__(
        self,
        *,
        max_entries: int = 20000,
        ttl_seconds: float = 60,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        """Keep at most max_entries names, with expiry checked on each search."""
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._lock = Lock()
        self._entries: OrderedDict[int, tuple[bytes, bytes, float, PreparedName]] = OrderedDict()

    def prepare(
        self, candidates: list[tuple[int, bytes, bytes]], cipher: IdentityCipher
    ) -> dict[int, PreparedName]:
        """Reuse only current database-selected identities with matching encrypted fields.

        Returns
        -------
        dict[int, PreparedName]
            Only this request's authorized/filter-matching candidates, never cached membership.
        """
        now = self.clock()
        with self._lock:
            for user_id, (_, _, created, _) in list(self._entries.items()):
                if now - created >= self.ttl_seconds:
                    del self._entries[user_id]
            result = {}
            for user_id, first, last in candidates:
                cached = self._entries.get(user_id)
                if cached is None or cached[0] != first or cached[1] != last:
                    name = prepare_name(
                        cipher.decrypt(user_id, "first_name", first),
                        cipher.decrypt(user_id, "last_name", last),
                    )
                    self._entries[user_id] = (first, last, now, name)
                else:
                    name = cached[3]
                self._entries.move_to_end(user_id)
                result[user_id] = name
                while len(self._entries) > self.max_entries:
                    self._entries.popitem(last=False)
            return result

    def clear(self) -> None:
        """Release cached references at application shutdown."""
        with self._lock:
            self._entries.clear()


def rank_names(query: str, names: list[tuple[int, str, str]], limit: int) -> list[int]:
    """Return best IDs, prioritizing exact matches and prefixes before fuzzy similarity.

    Parameters
    ----------
    query
        A bounded administrator-supplied search, never logged or persisted.
    names
        Authorized candidate IDs, first names and family names in transient memory.
    limit
        Maximum number of returned accounts.

    Returns
    -------
    list[int]
        Matching IDs ordered by match quality and stable account ID.
    """
    return rank_prepared_names(
        query, {user_id: prepare_name(first, last) for user_id, first, last in names}, limit
    )


def rank_prepared_names(query: str, names: dict[int, PreparedName], limit: int) -> list[int]:
    """Rank only currently authorized candidates using reusable normalized identity forms."""
    normalized = normalize_search(query)
    compact = normalized.replace(" ", "")
    if len(compact) < 2:
        return []
    choices: dict[int, str] = {}
    priority: dict[int, int] = {}
    prefix = re.compile(r"(?:^| )" + re.escape(compact))
    token_prefixes = re.compile(
        "".join(r"(?=.*\b" + re.escape(token) + ")" for token in normalized.split())
    )
    for user_id, name in names.items():
        if compact in name.compact_forms:
            priority[user_id] = 3
        elif prefix.search(name.prefix_text) or token_prefixes.match(name.text):
            priority[user_id] = 2
        elif len(compact) >= 3 and compact in name.prefix_text:
            priority[user_id] = 1
        choices[user_id] = name.text
    # Consider all candidates before limiting, otherwise exact/prefix matches can be lost.
    fuzzy = extract(normalized, choices, scorer=WRatio, limit=None, score_cutoff=70)
    scores = {user_id: score for _, score, user_id in fuzzy}
    candidates = set(priority) | (set(scores) if len(compact) >= 4 else set())
    return sorted(
        candidates, key=lambda item: (-priority.get(item, 0), -scores.get(item, 0), item)
    )[:limit]
