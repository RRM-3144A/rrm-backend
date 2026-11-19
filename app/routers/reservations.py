from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Reservation, User
from app.schemas import ReservationCreate, ReservationOut
from app.services.reservations import create_reservation_request

router = APIRouter(prefix="/reservations", tags=["Reservations"])


@router.post("", response_model=ReservationOut, status_code=status.HTTP_201_CREATED)
def create_reservation(
    body: ReservationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Reservation:
    return create_reservation_request(db, user, body)