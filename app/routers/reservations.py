from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Reservation, ReservationStatus, User
from app.schemas import ReservationCreate, ReservationOut, ReservationStatusUpdate
from app.services.sharing import (
    CapacityConflictError,
    approve_reservation_checked,
    create_reservation_checked,
)

router = APIRouter(prefix="/reservations", tags=["Reservations"])


@router.post("", response_model=ReservationOut, status_code=status.HTTP_201_CREATED)
def create_reservation(
    body: ReservationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Reservation:
    try:
        return create_reservation_checked(db, user, body)
    except CapacityConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.patch("/{reservation_id}/status", response_model=ReservationOut)
def update_reservation_status(
    reservation_id: int,
    body: ReservationStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Reservation:
    if body.status != ReservationStatus.APPROVED:
        raise HTTPException(422, "Only APPROVED status transition is handled here")
    try:
        return approve_reservation_checked(db, reservation_id, user)
    except CapacityConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc