"""Parse portable JSON strictly; uploaded text is data and is never executed."""

import json

from pydantic import ValidationError

from app.schemas.curricula import CompetencyImport
from app.services.errors import AuthError

FILE_LIMIT = 4 * 1024 * 1024
REQUEST_LIMIT = FILE_LIMIT * 2 + 4096


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate and prototype-related keys before constructing dictionaries."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result or key in {"__proto__", "constructor", "prototype"}:
            raise ValueError("Clé JSON interdite ou dupliquée.")
        result[key] = value
    return result


def parse_import(body: bytes) -> CompetencyImport:
    """Return a validated bounded import or a safe error without echoing file contents."""
    if len(body) > REQUEST_LIMIT:
        raise AuthError(413, "Fichier trop volumineux (4 Mo maximum).")
    try:
        value = json.loads(body, object_pairs_hook=unique_object)
        if isinstance(value, dict) and isinstance(value.get("document"), str):
            if len(value["document"].encode("utf-8")) > FILE_LIMIT:
                raise ValueError("Fichier trop volumineux.")
            value["document"] = json.loads(value["document"], object_pairs_hook=unique_object)
        if (
            isinstance(value, dict)
            and len(json.dumps(value.get("document"), ensure_ascii=False, allow_nan=False).encode())
            > FILE_LIMIT
        ):
            raise ValueError("Fichier trop volumineux.")
        return CompetencyImport.model_validate(value)
    except (ValueError, ValidationError, RecursionError, UnicodeError):
        raise AuthError(
            422, "JSON invalide : vérifiez le format, les champs et les relations."
        ) from None
