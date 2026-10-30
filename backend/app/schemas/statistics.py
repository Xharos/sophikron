"""Aggregate-only statistics contracts; no recipient identities or private file paths."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Period = Literal["day", "week", "month"]


class Breakdown(BaseModel):
    """A named aggregate used by shared bar and doughnut charts."""

    label: str
    value: int
    count: int = 0
    id: int | None = None


class StorageStatistics(BaseModel):
    """Distinguish referenced documents, reservations and actual private folder contents."""

    files: int = 0
    bytes: int = 0
    quota_bytes: int = 0
    reserved_bytes: int = 0
    physical_bytes: int | None = None
    temporary_bytes: int | None = None
    pending_deletions: int | None = None
    formats: list[Breakdown] = Field(default_factory=list)


class StatisticsResponse(BaseModel):
    """One bounded period and scope, shared by administrator, author and course dashboards."""

    scope: Literal["admin", "author", "course"]
    period: Period
    timestamps: list[datetime]
    generated_at: datetime
    attempts_since: datetime | None = None
    series: dict[str, list[int]]
    totals: dict[str, int]
    storage: StorageStatistics
    accounts: list[Breakdown] = Field(default_factory=list)
    roles: list[Breakdown] = Field(default_factory=list)
    calendar_subscriptions: list[Breakdown] = Field(default_factory=list)
    calendar_recent_users: int = 0
    calendar_eligible_users: int = 0
    calendar_requests_total: int = 0
    promotions: list[Breakdown] = Field(default_factory=list)
    promotion_staff: list[Breakdown] = Field(default_factory=list)
    subjects: list[Breakdown] = Field(default_factory=list)
    popular: list[Breakdown] = Field(default_factory=list)
    courses: list[Breakdown] = Field(default_factory=list)
