"""Central version registry; future API versions use independent routers."""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    dashboard,
    groups,
    lesson_documents,
    lessons,
    profiles,
    site,
    statistics,
    teaching,
    timetable,
)

router = APIRouter()
v1 = APIRouter(prefix="/api/v1")
v1.include_router(auth.router)
v1.include_router(admin.router)
v1.include_router(dashboard.router)
v1.include_router(groups.router)
v1.include_router(timetable.router)
v1.include_router(statistics.router)
v1.include_router(teaching.router)
v1.include_router(profiles.router)
v1.include_router(site.router)
v1.include_router(lesson_documents.router)
v1.include_router(lessons.router)


@v1.get("", tags=["API"])
async def read_root() -> dict[str, str]:
    """Return API information without requiring PostgreSQL availability."""
    return {"message": "Welcome to Sophikron API"}


router.include_router(v1)
