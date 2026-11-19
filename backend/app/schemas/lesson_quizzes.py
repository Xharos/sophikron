"""Bound requests and public summaries for course quiz blocks."""

from typing import Annotated

from pydantic import BaseModel, Field

from app.schemas.quiz import OptionIndex, QuizInput, ShortText


class QuizReference(BaseModel):
    """A bank identity and label suitable for the course editor."""

    id: int
    title: str


class QuizProgress(BaseModel):
    """Describe the learner's first passage without exposing correction rules."""

    completed: int
    total: int
    started: bool = False


class QuizStart(QuizInput):
    """Open the recorded passage or request its ephemeral replay order."""

    replay: bool = False
    previous_order: list[Annotated[int, Field(ge=0, lt=50)]] | None = Field(
        default=None, max_length=50
    )


class QuizAnswer(QuizInput):
    """Validate one first-passage answer against its current revision."""

    revision: int = Field(ge=0, le=2**63 - 1)
    answer: ShortText | Annotated[list[OptionIndex], Field(min_length=1, max_length=12)]


class QuizReplay(QuizInput):
    """Fetch or validate a replay card without updating the first passage."""

    index: int = Field(ge=0, lt=50)
    answer: ShortText | Annotated[list[OptionIndex], Field(min_length=1, max_length=12)] | None = (
        None
    )


class QuizRun(BaseModel):
    """Public card or replay order following an authorized operation."""

    completed: int
    total: int
    revision: int
    card: dict | None = None
    correct: bool | None = None
    order: list[int] | None = None
