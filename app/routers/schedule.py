from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ensure_resource_admin, get_current_user
from app.models import User
from app.routers.resources import get_resource_or_404
from app.schemas import ScheduleInterval, ScheduleUpdate
from app.services.schedule import ScheduleError, replace_schedule

router = APIRouter(prefix="/resources/{resource_id}/schedule", tags=["Schedule"])


def _sorted(resource) -> list[ScheduleInterval]:
    return [
        ScheduleInterval.model_validate(s)
        for s in sorted(resource.schedules, key=lambda s: (s.weekday, s.start_time))
    ]


@router.get("", response_model=list[ScheduleInterval])
def read_schedule(
    resource_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[ScheduleInterval]:
    return _sorted(get_resource_or_404(db, resource_id))


@router.put("", response_model=list[ScheduleInterval])
def update_schedule(
    resource_id: int,
    body: ScheduleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ScheduleInterval]:
    resource = get_resource_or_404(db, resource_id)
    ensure_resource_admin(resource, user)
    try:
        replace_schedule(resource, body.intervals)
    except ScheduleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.commit()
    db.refresh(resource)
    return _sorted(resource)
