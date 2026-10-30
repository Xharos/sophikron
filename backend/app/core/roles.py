"""Shared role eligibility rules, independent of actor permissions and role priority."""

from collections.abc import Iterable

TEACHING_ROLES = frozenset({"teacher", "kholleur"})
PROMOTION_ROLES = TEACHING_ROLES | {"user"}


def can_join_promotion(roles: Iterable[str]) -> bool:
    """Determine whether an account may belong to a promotion.

    Parameters
    ----------
    roles
        Explicit account roles; administrator alone does not grant eligibility.

    Returns
    -------
    bool
        Whether at least one pupil, teacher or khôlleur role is present.
    """
    return not PROMOTION_ROLES.isdisjoint(roles)
