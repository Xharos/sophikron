"""Register application metadata for Alembic without initializing connections."""

from app.models.activity import ActivityEvent
from app.models.auth import (
    AccountInvitation,
    ApplicationState,
    AuthRateLimit,
    LoginAttempt,
    Role,
    Session,
    User,
    UserRole,
)
from app.models.groups import (
    PromotionCustomGroup,
    PromotionCustomGroupMember,
    PromotionGroup,
    PromotionGroupMember,
    PromotionPartition,
)
from app.models.lessons import (
    Lesson,
    LessonCollaborator,
    LessonElement,
    LessonFile,
    LessonFileDeletion,
    LessonPromotion,
    LessonUpload,
)
from app.models.permissions import Permission, RolePermission
from app.models.promotions import Promotion, PromotionAccountBlock, UserPromotion
from app.models.releases import ReleaseCheck
from app.models.site import (
    SiteSettings,
    Subject,
    TeacherSubject,
)
from app.models.statistics import ApiMetric, CalendarUsageTotal, LoginStatistic
from app.models.timetable import (
    TeacherAvailability,
    TimetableCalendar,
    TimetablePreferences,
    TimetableRoom,
    TimetableSchoolYear,
    TimetableSeries,
    TimetableSubscription,
    TimetableYear,
)

__all__ = [
    "ReleaseCheck",
    "ApiMetric",
    "CalendarUsageTotal",
    "PromotionCustomGroup",
    "PromotionCustomGroupMember",
    "TimetablePreferences",
    "TeacherAvailability",
    "TimetableCalendar",
    "TimetableRoom",
    "TimetableSchoolYear",
    "TimetableSeries",
    "TimetableSubscription",
    "TimetableYear",
    "SiteSettings",
    "Subject",
    "TeacherSubject",
    "AccountInvitation",
    "ActivityEvent",
    "ApplicationState",
    "AuthRateLimit",
    "LoginAttempt",
    "LoginStatistic",
    "Lesson",
    "LessonFile",
    "LessonUpload",
    "LessonFileDeletion",
    "LessonCollaborator",
    "LessonElement",
    "LessonPromotion",
    "Permission",
    "Promotion",
    "PromotionPartition",
    "PromotionGroup",
    "PromotionGroupMember",
    "PromotionAccountBlock",
    "Role",
    "RolePermission",
    "Session",
    "User",
    "UserPromotion",
    "UserRole",
]
