from fastapi import Depends, Query

from .auth import effective_school_id, get_current_user
from .models import User


def school_id_param(school_id: int | None = Query(None)) -> int | None:
    return school_id


def SchoolDep(user: User = Depends(get_current_user),
              school_id: int | None = Depends(school_id_param)) -> int:
    """Liefert die effektive Mandanten-ID unter Berücksichtigung der RBAC-Regeln (FD-902)."""
    return effective_school_id(user, school_id)
