"""Calendar credentials reuse authenticated encryption with a dedicated field binding."""

import secrets
from datetime import UTC, datetime

import pytest

from app.core.security import IdentityCipher, token_digest
from app.models import TimetableSubscription
from app.services.calendar_subscriptions import rotate_subscription
from app.services.timetable import calendar_event_text


@pytest.mark.parametrize(
    "target,number,label",
    [
        ("promotion", None, "Classe entière"),
        ("halves", 2, "Demi-groupe B"),
        ("thirds", 3, "Tiers de groupe Z"),
        ("kholles", 4, "Groupe de khôlle 004"),
        ("custom", 5, "Option allemand"),
        ("student", None, "Séance individuelle"),
    ],
)
def test_export_subject_and_audience_notes(target: str, number: int | None, label: str) -> None:
    """Prefer the actual subject, localize audiences and keep the teacher on a separate line."""
    summary, notes = calendar_event_text(
        {
            "kind": "td",
            "subject_id": 1,
            "subject_label": "Mathématiques",
            "title": "A custom session title",
            "target_kind": target,
            "target_number": number,
            "audience_label": "Option allemand",
            "promotion_label": "PTSI",
            "teacher": "Camille Martin",
        }
    )
    assert summary == "TD - MATHÉMATIQUES"
    assert notes == f"PTSI — {label}\nCamille Martin"


def test_export_subjectless_session_without_teacher() -> None:
    """Retain a useful custom title and omit empty teacher lines."""
    assert calendar_event_text(
        {
            "kind": "kholle",
            "subject_id": None,
            "title": "Préparation orale",
            "teacher": "",
            "target_kind": "promotion",
        }
    ) == ("Khôlle - PRÉPARATION ORALE", "Classe entière")


def test_calendar_secret_rotation_uses_long_random_row_bound_encryption() -> None:
    """Invalidate the previous verifier, clear revocation and reject transplanted credentials."""
    cipher = IdentityCipher("test", {"test": secrets.token_bytes(32)}, secrets.token_bytes(32))
    now = datetime.now(UTC)
    row = TimetableSubscription(user_id=17, revoked_at=now, last_requested_at=now)
    rotate_subscription(row, cipher, now)
    token = cipher.decrypt(17, "calendar_token", row.token_encrypted)
    assert len(token) == 86 and row.token_hash == token_digest(token)
    assert row.revoked_at is None and row.last_requested_at == now
    with pytest.raises(ValueError):
        cipher.decrypt(18, "calendar_token", row.token_encrypted)
    with pytest.raises(ValueError):
        cipher.decrypt(17, "username", row.token_encrypted)
    rotate_subscription(row, cipher, now)
    assert row.token_hash != token_digest(token)
