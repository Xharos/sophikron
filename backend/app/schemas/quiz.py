"""Bound inputs for question editing and stateless preview."""

import re
import unicodedata
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
NumberText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Identifier = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]
OptionIndex = Annotated[int, Field(strict=True, ge=0, lt=12)]

MAX_IMAGE_BYTES = 1024 * 1024
MAX_ENCODED_IMAGE = 4 * ((MAX_IMAGE_BYTES + 2) // 3) + 32

SCALAR = r"[+-]?(?:[0-9]+(?:[.,][0-9]+)?|[.,][0-9]+)(?:[eE][+-]?[0-9]{1,2})?"
FRACTION = r"[+-]?[0-9]+\s*/\s*[+-]?[0-9]+"


def parse_number(value: str) -> Fraction:
    """Read a signed decimal or integer fraction as an exact rational.

    Parameters
    ----------
    value
        Bounded answer written with a comma, point, or fraction bar.

    Returns
    -------
    Fraction
        Exact value. Invalid formats and zero denominators raise ValueError.
    """
    value = value.strip().replace("−", "-")
    if len(value) <= 80 and re.fullmatch(SCALAR, value):
        return Fraction(value.replace(",", "."))
    if len(value) <= 80 and re.fullmatch(FRACTION, value):
        numerator, denominator = map(int, value.split("/"))
        if denominator:
            return Fraction(numerator, denominator)
    raise ValueError("Saisissez un nombre ou une fraction (par exemple 0,5 ou 1/2).")


def normalize_answer(value: str) -> str:
    """Return text normalized for case, accents and runs of whitespace."""
    decomposed = unicodedata.normalize("NFD", value.casefold())
    plain = "".join(char for char in decomposed if not unicodedata.category(char).startswith("M"))
    return " ".join(plain.split())


class QuizInput(BaseModel):
    """Reject unknown fields and bound input strings."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, str_max_length=4000)


class ChoiceRule(QuizInput):
    """Keep choices ordered and identify the correct subset by index."""

    kind: Literal["choice"]
    options: list[ShortText] = Field(min_length=2, max_length=12)
    correct: list[OptionIndex] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def check_options(self) -> "ChoiceRule":
        """Require distinct options and a valid subset."""
        if len(set(self.options)) != len(self.options):
            raise ValueError("Les propositions doivent être distinctes.")
        if len(set(self.correct)) != len(self.correct) or max(self.correct) >= len(self.options):
            raise ValueError("Sélectionnez les bonnes propositions.")
        return self


class NumberRule(QuizInput):
    """Accept exact numeric equivalence or an inclusive absolute tolerance."""

    kind: Literal["number"]
    expected: NumberText
    tolerance: NumberText = "0"

    @model_validator(mode="after")
    def check_numbers(self) -> "NumberRule":
        """Require a valid target and a nonnegative tolerance."""
        try:
            parse_number(self.expected)
        except ValueError as error:
            raise ValueError(f"Valeur attendue. {error}") from None
        try:
            tolerance = parse_number(self.tolerance)
        except ValueError as error:
            raise ValueError(f"Tolérance. {error}") from None
        if tolerance < 0:
            raise ValueError("La tolérance doit être positive ou nulle.")
        return self


class TextRule(QuizInput):
    """Allow one or more teacher-defined text variants."""

    kind: Literal["text"]
    accepted: list[ShortText] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def check_answers(self) -> "TextRule":
        """Reject answers that become empty after normalization."""
        if any(not normalize_answer(value) for value in self.accepted):
            raise ValueError("Chaque réponse doit contenir du texte.")
        return self


Rule = Annotated[ChoiceRule | NumberRule | TextRule, Field(discriminator="kind")]


class QuestionFields(QuizInput):
    """Describe the editable definition of a standalone question."""

    title: str = Field(min_length=1, max_length=160)
    statement: str = Field(default="", max_length=4000)
    prompt: str = Field(min_length=1, max_length=4000)
    rule: Rule
    competency_ids: list[Identifier] = Field(default_factory=list, max_length=50)
    image: str | None = Field(default=None, max_length=MAX_ENCODED_IMAGE)
    image_alt: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def check_fields(self) -> "QuestionFields":
        """Keep text compatible with storage and require an image description."""
        text = [self.title, self.statement, self.prompt, self.image_alt]
        if isinstance(self.rule, ChoiceRule):
            text.extend(self.rule.options)
        elif isinstance(self.rule, TextRule):
            text.extend(self.rule.accepted)
        if any("\x00" in value for value in text):
            raise ValueError("Caractère non autorisé.")
        if self.image and not self.image_alt:
            raise ValueError("Décrivez l’image pour les personnes qui ne peuvent pas la voir.")
        if len(set(self.competency_ids)) != len(self.competency_ids):
            raise ValueError("Les compétences doivent être distinctes.")
        return self


class Revision(QuizInput):
    """Protect changes from stale versions of the question."""

    version: int = Field(strict=True, ge=0, le=2**63 - 1)


class QuestionUpdate(QuestionFields, Revision):
    """Replace content while checking the displayed version."""


class ArchiveUpdate(Revision):
    """Set the archive status to a specific value."""

    archived: bool = Field(strict=True)


class PreviewAnswer(Revision):
    """Accept bounded text or selected option indices."""

    answer: ShortText | Annotated[list[OptionIndex], Field(min_length=1, max_length=12)]
