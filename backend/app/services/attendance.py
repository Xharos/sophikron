"""Authorize roster exports before decrypting names or rendering private PDFs."""

import anyio

from app.models import Promotion, UserPromotion
from app.repositories.groups import GroupsRepository
from app.services.attendance_pdf import AttendanceStudent, render_attendance_pdf
from app.services.auth import AuthService, UserContext
from app.services.errors import AuthError


class AttendanceService:
    """Generate a transient document inside the caller's current student-directory scope."""

    def __init__(self, auth: AuthService) -> None:
        """Reuse authenticated request resources and the authoritative pupil repository."""
        self.auth = auth

    async def generate(self, actor: UserContext, promotion_id: int) -> bytes:
        """Read the complete authorized roster and render it outside the database transaction.

        Parameters
        ----------
        actor
            Authenticated requester; permissions and identity are checked again in the database.
        promotion_id
            Promotion whose current pupils should be exported.

        Returns
        -------
        bytes
            An in-memory PDF with no persistent copy or secret-bearing download link.
        """
        async with self.auth.db.begin():
            user = await self.auth._actor(actor)
            permissions = await self.auth.repo.permissions(actor.id)
            if user.is_bootstrap or not {"users.read", "teaching.read"}.intersection(permissions):
                raise AuthError(403, "Vous n’avez pas accès à cette action.")
            if "users.read" not in permissions:
                membership = await self.auth.db.get(UserPromotion, (actor.id, promotion_id))
                if membership is None:
                    raise AuthError(404, "Promotion introuvable.")
            promotion = await self.auth.db.get(Promotion, promotion_id)
            if promotion is None:
                raise AuthError(404, "Promotion introuvable.")
            cipher = self.auth.cipher
            pupils = await GroupsRepository(self.auth.db).pupils(promotion_id)
            students = [
                AttendanceStudent(
                    last_name=cipher.decrypt(pupil.id, "last_name", pupil.last_name_encrypted),
                    first_name=cipher.decrypt(pupil.id, "first_name", pupil.first_name_encrypted),
                    archived=pupil.status == "disabled",
                    active=pupil.status == "active",
                )
                for pupil in pupils
            ]
            requested_by = " ".join(
                (
                    cipher.decrypt(user.id, "last_name", user.last_name_encrypted).upper(),
                    cipher.decrypt(user.id, "first_name", user.first_name_encrypted).title(),
                )
            )
            name, color = f"{promotion.identifier} - {promotion.year}", promotion.color
            generated_at = self.auth.clock()
        return await anyio.to_thread.run_sync(
            render_attendance_pdf,
            name,
            color,
            students,
            requested_by,
            generated_at,
        )
