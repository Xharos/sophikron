"""French identity validation and deterministic username/search normalization."""

import re
import unicodedata

FRENCH_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzàâäæçéèêëîïôöœùûüÿ")


def normalize_name(value: str) -> str:
    """Return a nonempty French name with normalized Unicode and spacing."""
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
    if not normalized or len(normalized) > 100:
        raise ValueError("Invalid name")
    if any(char.lower() not in FRENCH_LETTERS and char not in " '-’" for char in normalized):
        raise ValueError("Invalid name")
    if not any(char.lower() in FRENCH_LETTERS for char in normalized):
        raise ValueError("Invalid name")
    return normalized


def normalize_search(value: str) -> str:
    """Return lowercase ASCII words, expanding French ligatures and separators."""
    expanded = value.lower().replace("œ", "oe").replace("æ", "ae")
    ascii_value = unicodedata.normalize("NFKD", expanded).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z]+", " ", ascii_value).split())


def username_prefix(first_name: str, last_name: str) -> str:
    """Return the first initial and up to four family-name letters without separators."""
    first = normalize_search(normalize_name(first_name)).replace(" ", "")
    last = normalize_search(normalize_name(last_name)).replace(" ", "")
    return first[0] + last[:4]
