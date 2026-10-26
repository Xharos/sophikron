"""Bounded contracts for independent partitions and their optimistic edits."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.auth import InputModel

PartitionKind = Literal["halves", "thirds", "kholles"]
PupilId = Annotated[int, Field(gt=0, strict=True)]


class GroupAssignment(BaseModel):
    """Identify a pupil's saved group without exposing other pupils or bubble positions."""

    promotion_id: int
    kind: PartitionKind
    number: int


class PartitionVersion(InputModel):
    """Require the revision seen by the editor, including an absent partition."""

    expected_revision: str | None = Field(pattern=r"^[0-9a-f]{32}$")


class PartitionGenerate(PartitionVersion):
    """Carry the pupil snapshot and a khôlle generation target between two and five."""

    roster_ids: list[PupilId] = Field(max_length=2000)
    target_size: int = Field(default=3, ge=2, le=5, strict=True)


class GroupDraft(InputModel):
    """Describe one bubble and its assigned pupils without arbitrary names or markup."""

    number: int = Field(ge=1, le=1000, strict=True)
    x: int = Field(ge=0, le=1000000, strict=True)
    y: int = Field(ge=0, le=1000000, strict=True)
    student_ids: list[PupilId] = Field(max_length=2000)


class PartitionSave(PartitionGenerate):
    """Replace one complete partition in a single validated transaction."""

    groups: list[GroupDraft] = Field(min_length=1, max_length=1000)


class PartitionResponse(BaseModel):
    """Return a saved partition with no copied private student identities."""

    kind: PartitionKind
    revision: str
    target_size: int
    groups: list[GroupDraft]


class GroupStudent(BaseModel):
    """Expose only names needed to display an authorized promotion's bubbles."""

    id: int
    first_name: str
    last_name: str


class PromotionGroupsResponse(BaseModel):
    """Supply the current roster and all three independent saved partitions."""

    students: list[GroupStudent]
    partitions: list[PartitionResponse]
