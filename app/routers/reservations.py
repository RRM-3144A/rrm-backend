from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Reservation, User
from app.schemas import ReservationOut, ReservationRejectRequest
from app.services.admin_decisions import (
    approve_reservation,
    mark_awaiting_training,
    reject_reservation,
)

router = APIRouter(prefix="/reservations", tags=["Reservations"])


@router.post("/{reservation_id}/approve", response_model=ReservationOut)
def approve_reservation_endpoint(
    reservation_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
) -> Reservation:
    return approve_reservation(db, reservation_id, admin)


@router.post("/{reservation_id}/reject", response_model=ReservationOut)
def reject_reservation_endpoint(
    reservation_id: int,
    body: ReservationRejectRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
) -> Reservation:
    reason = body.effective_reason if body is not None else None
    return reject_reservation(db, reservation_id, admin, reason)


@router.post("/{reservation_id}/awaiting-training", response_model=ReservationOut)
def awaiting_training_endpoint(
    reservation_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
) -> Reservation:
    return mark_awaiting_training(db, reservation_id, admin)