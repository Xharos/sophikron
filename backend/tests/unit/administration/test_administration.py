"""Identity normalization, role contracts, event validation and fuzzy relevance."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.http import SearchAccessLogFilter
from app.core.identity import normalize_name, username_prefix
from app.core.roles import can_join_promotion
from app.models import Promotion
from app.schemas.administration import PromotionCreate, PromotionUpdate
from app.schemas.auth import CreateUserRequest
from app.services.activity import record_event
from app.services.auth import AuthService
from app.services.errors import AuthError
from app.services.search import NameSearchCache, rank_names


@pytest.mark.parametrize(
    "first,last,prefix",
    [
        ("Valentin", "BURGAUD", "vburg"),
        ("Valentin", "Roy", "vroy"),
        ("Valentin", "Rémi", "vremi"),
        ("Dionis", "DU SEJOUR", "dduse"),
        ("Élodie", "D’Artagnan", "edart"),
        ("Anne-Marie", "Le Bœuf", "alebo"),
        ("Œdipe", "Ægir", "oaegi"),
    ],
)
def test_username_normalization(first: str, last: str, prefix: str) -> None:
    """Strip accents and separators for usernames while preserving stored French identities."""
    assert username_prefix(first, last) == prefix
    assert normalize_name(last) == last


@pytest.mark.parametrize("name", ["", "   ", "---", "123", "李", "A\x00B", "A/B", "AБ"])
def test_invalid_names(name: str) -> None:
    """Reject empty identities and unsupported alphabets or punctuation."""
    with pytest.raises(ValueError):
        normalize_name(name)


@pytest.mark.parametrize(
    "roles",
    [
        ["user"],
        ["kholleur"],
        ["teacher"],
        ["admin"],
        ["teacher", "admin"],
        ["kholleur", "teacher"],
        ["kholleur", "admin"],
        ["kholleur", "teacher", "admin"],
    ],
)
def test_allowed_roles(roles: list[str]) -> None:
    """Keep administrator-only accounts valid without implying teacher permissions."""
    data = CreateUserRequest(
        first_name="Valentin", last_name="Roy", email="v@example.org", roles=roles
    )
    assert data.roles == roles and data.promotion_ids == []


def test_default_student_role() -> None:
    """Give new accounts only student access when roles are omitted."""
    data = CreateUserRequest(first_name="Valentin", last_name="Roy", email="v@example.org")
    assert data.roles == ["user"]


@pytest.mark.parametrize(
    "roles,expected",
    [
        (["user"], True),
        (["teacher"], True),
        (["kholleur"], True),
        (["teacher", "kholleur"], True),
        (["admin", "teacher"], True),
        (["admin", "kholleur"], True),
        (["admin", "teacher", "kholleur"], True),
        (["admin"], False),
        ([], False),
        (["unknown"], False),
    ],
)
def test_promotion_role_eligibility(roles: list[str], expected: bool) -> None:
    """Require an explicit eligible role independently of administrator priority."""
    assert can_join_promotion(roles) is expected


@pytest.mark.asyncio
async def test_admin_only_creation_rejects_promotions_before_writes() -> None:
    """Reject ineligible creation before reserving an ID or inserting any account."""
    service = object.__new__(AuthService)
    data = CreateUserRequest(
        first_name="Camille",
        last_name="Martin",
        email="camille@example.org",
        roles=["admin"],
        promotion_ids=[1],
    )
    with pytest.raises(AuthError) as failure:
        await service._create(data)
    assert failure.value.status == 422


@pytest.mark.parametrize(
    "roles",
    [
        [],
        ["student"],
        ["user", "teacher"],
        ["user", "admin"],
        ["user", "kholleur"],
        ["user", "teacher", "admin"],
        ["teacher", "teacher"],
    ],
)
def test_forbidden_roles(roles: list[str]) -> None:
    """Refuse incompatible or obsolete role combinations before any account is created."""
    with pytest.raises(ValidationError):
        CreateUserRequest(
            first_name="Valentin", last_name="Roy", email="v@example.org", roles=roles
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"username": "chosen103"},
        {"password": "secret"},
        {"promotion_ids": [0]},
        {"promotion_ids": [1, 1]},
    ],
)
def test_strict_creation(extra: dict[str, object]) -> None:
    """Forbid caller-selected usernames/passwords and invalid membership lists."""
    with pytest.raises(ValidationError):
        CreateUserRequest.model_validate(
            dict(first_name="Valentin", last_name="Roy", email="v@example.org", roles=["user"])
            | extra
        )


def test_promotion_validation() -> None:
    """Normalize catalogue metadata and distinguish omitted fields from invalid nulls."""
    data = PromotionCreate(year=2019, identifier=" PTSI ", color="#abcdef")
    assert data.identifier == "PTSI" and data.color == "#ABCDEF"
    assert PromotionUpdate().model_dump(exclude_unset=True) == {}
    for payload in ({"is_active": None}, {"identifier": " "}, {"color": "red"}, {"year": 0}):
        with pytest.raises(ValidationError):
            PromotionUpdate.model_validate(payload)


@pytest.mark.parametrize("query", ["burg", "burgaud val", "valentin burgo", "VALENTIN BURGAUD"])
def test_fuzzy_relevance(query: str) -> None:
    """Return the intended person for partial, reversed and misspelled French names."""
    names = [(1, "Valentin", "Burgaud"), (2, "Alice", "Martin"), (3, "Paul", "Durand")]
    assert rank_names(query, names, 20)[0] == 1


def test_fuzzy_accents_separators_and_order() -> None:
    """Favor exact names, tolerate accents/separators and bound short-query noise."""
    names = [(1, "Paul", "Rémilly"), (2, "Alice", "Rémi"), (3, "Dionis", "DU SEJOUR")]
    assert rank_names("remi", names, 1) == [2]
    assert rank_names("dusejour", names, 20)[0] == 3
    assert rank_names("zz", names, 20) == []
    assert rank_names("--", names, 20) == []


@pytest.mark.asyncio
async def test_event_schema_rejects_untrusted_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """Allow declared facts but forbid arbitrary payloads, references and unknown types."""
    session = MagicMock()
    monkeypatch.setattr(
        "app.services.activity.capture_roles", AsyncMock(return_value={1: "admin", 2: "user"})
    )
    await record_event(
        session,
        "promotion.member_added",
        1,
        subject_user_id=2,
        resource_type="promotion",
        resource_id=3,
        promotion=Promotion(id=3, identifier="PTSI", year=2026, color="#123456"),
    )
    assert session.add.call_args.args[0].data == {}
    with pytest.raises(ValidationError):
        await record_event(
            session, "auth.login_succeeded", 1, subject_user_id=1, data={"password": "secret"}
        )
    with pytest.raises(ValueError):
        await record_event(session, "promotion.created", 1)
    with pytest.raises(KeyError):
        await record_event(session, "unregistered.event", 1)


@pytest.mark.asyncio
async def test_username_collision_retry_and_exhaustion() -> None:
    """Try distinct suffixes, preserve a colliding account and stop after all 900 candidates."""
    service = object.__new__(AuthService)
    service.cipher = MagicMock()
    service.cipher.lookup.side_effect = lambda field, value: value.encode()
    service.repo = MagicMock()
    service.repo.by_lookup = AsyncMock(side_effect=[object(), None])
    with patch("app.services.auth.secrets.SystemRandom.shuffle"):
        assert await service._generate_username("Valentin", "Roy") == "vroy101"
    assert service.repo.by_lookup.await_count == 2
    service.repo.by_lookup = AsyncMock(return_value=object())
    with pytest.raises(AuthError) as error:
        await service._generate_username("Valentin", "Roy")
    assert error.value.status == 409 and service.repo.by_lookup.await_count == 900


def test_search_text_removed_from_access_logs() -> None:
    """Keep personal search text out of Uvicorn access entries without suppressing statuses."""
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", "/api/v1/admin/users/search?q=private", "1.1", 200),
        None,
    )
    assert SearchAccessLogFilter().filter(record)
    assert "private" not in record.getMessage() and "200" in record.getMessage()


def test_name_cache_capacity_expiry_and_invalidation() -> None:
    """Reuse names only while ciphertext/TTL match, and never cache candidate membership."""
    now = [0.0]
    cipher = MagicMock()
    cipher.decrypt.side_effect = lambda user_id, field, value: value.decode()
    cache = NameSearchCache(max_entries=1, ttl_seconds=60, clock=lambda: now[0])
    candidate = [(1, b"Valentin", b"Burgaud")]
    assert cache.prepare(candidate, cipher)[1].last_name == "Burgaud"
    cache.prepare(candidate, cipher)
    assert cipher.decrypt.call_count == 2
    assert cache.prepare([(1, b"Valentin", b"Roy")], cipher)[1].last_name == "Roy"
    assert cipher.decrypt.call_count == 4
    now[0] = 61
    cache.prepare([(1, b"Valentin", b"Roy")], cipher)
    assert cipher.decrypt.call_count == 6
    assert set(cache.prepare([(2, b"Alice", b"Martin")], cipher)) == {2}
    cache.prepare(candidate, cipher)
    assert cipher.decrypt.call_count == 10  # ID 1 was evicted by the one-entry capacity.
    assert cache.prepare([], cipher) == {}
    cache.clear()
    cache.prepare(candidate, cipher)
    assert cipher.decrypt.call_count == 12
