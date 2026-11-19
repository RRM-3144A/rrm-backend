from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_admin
from app.models import User
from app.schemas import PendingReservationOut
from app.services.admin_requests import list_admin_pending_reservations

router = APIRouter(prefix="/reservations", tags=["Reservations"])


@router.get("/pending", response_model=list[PendingReservationOut])
def get_pending_reservations(
    resource_id: int | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[PendingReservationOut]:
    return list_admin_pending_reservations(db, admin, resource_id=resource_id)