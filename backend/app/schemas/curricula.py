"""Bounded contracts for programme metadata and modular competency editing."""

from typing import Annotated, Literal

from pydantic import Field, HttpUrl, field_validator, model_validator

from app.schemas.auth import InputModel

Identifier = Annotated[int, Field(gt=0)]


class Revision(InputModel):
    """Reject stale edits using a programme-wide revision."""

    expected_version: int = Field(ge=0)


def trim_name(value: str) -> str:
    """Return a nonempty normalized display name."""
    value = " ".join(value.split())
    if not value:
        raise ValueError("Un nom est requis.")
    return value


class CurriculumFields(InputModel):
    """Create a self-contained programme using existing subjects and an official PDF link."""

    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=3000)
    source_url: HttpUrl | None = None
    subject_ids: list[Identifier] = Field(min_length=1, max_length=100)
    is_active: bool = True

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        """Reject blank programme titles."""
        return trim_name(value)

    @field_validator("source_url")
    @classmethod
    def public_link(cls, value: HttpUrl | None) -> HttpUrl | None:
        """Reject credentials and unbounded source URLs; no server-side fetch occurs."""
        if value and (value.username or value.password or len(str(value)) > 2000):
            raise ValueError("Lien invalide.")
        return value

    @field_validator("subject_ids")
    @classmethod
    def unique_subjects(cls, value: list[int]) -> list[int]:
        """Require each subject once."""
        if len(set(value)) != len(value):
            raise ValueError("Matière dupliquée.")
        return value


class CurriculumUpdate(CurriculumFields, Revision):
    """Edit programme settings using optimistic concurrency."""


class CompetencyFields(Revision):
    """Replace one competency and all its parent links in a single transaction."""

    name: str = Field(min_length=1, max_length=300)
    semester: int | None = Field(default=None, ge=1, le=4)
    knowledge: str | None = Field(default=None, max_length=12000)
    comment: str | None = Field(default=None, max_length=12000)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    position: int = Field(default=0, ge=0, le=10000)
    parent_ids: list[Identifier] = Field(default_factory=list, max_length=100)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        """Normalize names while retaining punctuation and accents."""
        return trim_name(value)

    @field_validator("knowledge", "comment")
    @classmethod
    def empty_to_null(cls, value: str | None) -> str | None:
        """Store empty optional text as null for portable future exports."""
        return value.strip() or None if value is not None else None

    @field_validator("parent_ids")
    @classmethod
    def unique_parents(cls, value: list[int]) -> list[int]:
        """Reject duplicate edges."""
        if len(set(value)) != len(value):
            raise ValueError("Parent dupliqué.")
        return value


class PortableCompetency(CompetencyFields):
    """Use file-local identities; codes are recalculated after import."""

    id: Identifier
    expected_version: Literal[0] = 0


class CompetencyFile(InputModel):
    """Validate a bounded flat DAG without recursive traversal or executable content."""

    format: Literal["sophikron.competencies"]
    version: Literal[1]
    subject_name: str = Field(max_length=100)
    nodes: list[PortableCompetency] = Field(max_length=2000)

    @model_validator(mode="after")
    def validate_graph(self) -> "CompetencyFile":
        """Reject duplicate identities, dangling edges, cycles and depth above 128."""
        by_id = {node.id: node for node in self.nodes}
        if len(by_id) != len(self.nodes):
            raise ValueError("Identifiants dupliqués.")
        incoming = {node.id: len(node.parent_ids) for node in self.nodes}
        children: dict[int, list[int]] = {}
        if sum(incoming.values()) > 20000:
            raise ValueError("Trop de relations.")
        for node in self.nodes:
            for parent in node.parent_ids:
                if parent not in by_id:
                    raise ValueError("Parent introuvable.")
                children.setdefault(parent, []).append(node.id)
        queue = [identifier for identifier, count in incoming.items() if not count]
        depth = dict.fromkeys(queue, 1)
        for identifier in queue:
            for child in children.get(identifier, []):
                depth[child] = max(depth.get(child, 0), depth[identifier] + 1)
                if depth[child] > 128:
                    raise ValueError("Profondeur maximale dépassée.")
                incoming[child] -= 1
                if not incoming[child]:
                    queue.append(child)
        if len(queue) != len(self.nodes):
            raise ValueError("Cycle entre compétences.")
        return self


class CompetencyImport(Revision):
    """Apply a validated portable graph to a revision-matching subject."""

    document: CompetencyFile
