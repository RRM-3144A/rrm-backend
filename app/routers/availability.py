from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.routers.resources import get_resource_or_404
from app.schemas import AvailabilitySlot
from app.services.availability import MAX_RANGE_DAYS, get_availability

router = APIRouter(prefix="/resources/{resource_id}/availability", tags=["Availability"])


@router.get("", response_model=list[AvailabilitySlot])
def read_availability(
    resource_id: int,
    start_date: date,
    end_date: date,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[AvailabilitySlot]:
    """30-minute slots within operating hours, from start_date to end_date inclusive."""
    if end_date < start_date:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "end_date must not be before start_date"
        )
    if (end_date - start_date).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The interval can span at most {MAX_RANGE_DAYS} days",
        )
    resource = get_resource_or_404(db, resource_id)
    return get_availability(db, resource, start_date, end_date)
