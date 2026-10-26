"""Live subject eligibility and revocation shared by course and account transactions."""

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lessons import Lesson, LessonCollaborator
from app.models.site import Subject, TeacherSubject
from app.schemas.site import CourseImpact
from app.services.errors import AuthError


async def has_subject(db: AsyncSession, user_id: int, subject_id: int) -> bool:
    """Return whether a current assignment points to an active subject."""
    return bool(
        await db.scalar(
            select(TeacherSubject.user_id)
            .join(Subject)
            .where(TeacherSubject.user_id == user_id, Subject.id == subject_id, Subject.is_active)
        )
    )


async def course_impact(db: AsyncSession, user_id: int) -> list[CourseImpact]:
    """List retained responsibilities and collaborations without exposing course bodies."""
    rows = await db.scalars(
        select(Lesson)
        .where(
            or_(
                Lesson.responsible_id == user_id,
                Lesson.id.in_(
                    select(LessonCollaborator.lesson_id).where(
                        LessonCollaborator.user_id == user_id
                    )
                ),
            )
        )
        .order_by(Lesson.title_key)
    )
    return [
        CourseImpact(
            id=row.id,
            title=row.title,
            subject_id=row.subject_id,
            responsible=row.responsible_id == user_id,
        )
        for row in rows
    ]


def require_impact_acknowledgement(courses: list[CourseImpact], acknowledged: bool) -> None:
    """Reject a destructive rights change until the administrator has seen its consequences."""
    if courses and not acknowledged:
        raise AuthError(
            409,
            f"Ce compte gère {len(courses)} cours. Confirmez le retrait de ses droits ; "
            "un administrateur pourra réaffecter leur responsable depuis chaque cours.",
        )


async def revoke_course_rights(
    db: AsyncSession, user_id: int, subject_ids: set[int] | None = None
) -> None:
    """Remove eligibility and collaboration while retaining historical responsibility.

    Parameters
    ----------
    db
        Locked account-lifecycle transaction.
    user_id
        Account losing teaching rights.
    subject_ids
        Restricted subject removals, or all assignments and collaborations when absent.

    Returns
    -------
    None
        Changes remain inside the caller's atomic transaction.
    """
    lessons = select(Lesson.id)
    assignments = delete(TeacherSubject).where(TeacherSubject.user_id == user_id)
    if subject_ids is not None:
        lessons = lessons.where(Lesson.subject_id.in_(subject_ids))
        assignments = assignments.where(TeacherSubject.subject_id.in_(subject_ids))
    affected = lessons.where(
        or_(
            Lesson.responsible_id == user_id,
            Lesson.id.in_(
                select(LessonCollaborator.lesson_id).where(LessonCollaborator.user_id == user_id)
            ),
        )
    )
    await db.execute(
        update(Lesson).where(Lesson.id.in_(affected)).values(version=Lesson.version + 1)
    )
    await db.execute(
        delete(LessonCollaborator).where(
            LessonCollaborator.user_id == user_id, LessonCollaborator.lesson_id.in_(lessons)
        )
    )
    await db.execute(assignments)
