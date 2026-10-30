"""Authorize timetable exports using the same board and current calendar scope as the UI."""

from datetime import date

import anyio

from app.models import Promotion
from app.services.activity import record_event
from app.services.auth import UserContext
from app.services.timetable import TimetableService
from app.services.timetable_pdf import render_timetable_pdf, select_view


class TimetableExportService(TimetableService):
    """Export server-resolved sessions; never trust browser-supplied event data or labels."""

    async def generate(
        self, actor: UserContext, identifier: int, year_id: int, day: date, node: str
    ) -> bytes:
        """Read the authorized view and render it in memory outside the transaction.

        Parameters
        ----------
        actor, identifier, year_id, day, node
            Current caller, calendar, annual grid, selected date and tree key.

        Returns
        -------
        bytes
            A private landscape A4 document with no stored copy.
        """
        board = await self.board(actor, [identifier], None)
        year, suffix, events = select_view(board, year_id, day, node)
        async with self.db.begin():
            calendar = await self._calendar(identifier, actor, write=False)
            promotion = (
                await self.db.get(Promotion, calendar.promotion_id)
                if calendar.promotion_id
                else None
            )
            title = f"{promotion.identifier} {promotion.year}" if promotion else calendar.name
            if suffix:
                title += f" - {suffix}"
        result = await anyio.to_thread.run_sync(
            render_timetable_pdf, title, year["settings"], events, day
        )
        async with self.db.begin():
            await record_event(
                self.db,
                "timetable.exported",
                actor.id,
                resource_type="timetable",
                resource_id=identifier,
                data={
                    "calendar_name": calendar.name,
                    "title": title,
                    "occurrence": day,
                    "school_year": year["school_year"],
                },
            )
        return result
