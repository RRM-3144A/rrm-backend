from fastapi import APIRouter, BackgroundTasks, Body, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import Reservation, User
from app.schemas import (
    MyReservationOut,
    PendingReservationOut,
    ReservationCreate,
    ReservationOut,
    ReservationRejectRequest,
    ReservationRescheduleRequest,
    ReservationStatusUpdate,
)
from app.services.admin_decisions import (
    approve_reservation,
    complete_training,
    mark_awaiting_training,
    reject_reservation,
)
from app.services.admin_requests import list_admin_pending_reservations
from app.services.notifications import send_in_background
from app.services.reservations import (
    cancel_reservation_with_notifications,
    create_reservation_request,
    get_reservation_or_404,
    list_reservations_needing_review,
    reschedule_reservation,
    transition_reservation_with_notifications,
)

router = APIRouter(prefix="/reservations", tags=["Reservations"])


@router.get("/me", response_model=list[MyReservationOut])
def get_my_reservations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Reservation]:
    """The signed-in user's reservations ("Rezervările mele"), newest first."""
    return list(
        db.scalars(
            select(Reservation)
            .options(joinedload(Reservation.resource), joinedload(Reservation.team))
            .where(Reservation.user_id == user.id)
            .order_by(Reservation.start_at.desc(), Reservation.id.desc())
        ).unique()
    )


@router.get("/pending", response_model=list[PendingReservationOut])
def get_pending_reservations(
    resource_id: int | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[PendingReservationOut]:
    return list_admin_pending_reservations(db, admin, resource_id=resource_id)


@router.get("/needs-review", response_model=list[ReservationOut])
def get_reservations_needing_review(
    resource_id: int | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[Reservation]:
    return list_reservations_needing_review(db, admin, resource_id=resource_id)


@router.post("", response_model=ReservationOut, status_code=status.HTTP_201_CREATED)
def create_reservation(
    body: ReservationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Reservation:
    return create_reservation_request(db, user, body)


@router.patch("/{reservation_id}/status", response_model=ReservationOut)
def update_reservation_status(
    reservation_id: int,
    body: ReservationStatusUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Reservation:
    reservation = get_reservation_or_404(db, reservation_id)
    updated, notifications = transition_reservation_with_notifications(
        db,
        reservation,
        user,
        body.status,
        rejection_reason=body.rejection_reason,
    )
    send_in_background(background_tasks, notifications)
    return updated


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


@router.post("/{reservation_id}/complete-training", response_model=ReservationOut)
def complete_training_endpoint(
    reservation_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
) -> Reservation:
    reservation, notification = complete_training(db, reservation_id, admin)
    send_in_background(background_tasks, [notification])
    return reservation


@router.post("/{reservation_id}/reschedule", response_model=ReservationOut)
def reschedule_reservation_endpoint(
    reservation_id: int,
    body: ReservationRescheduleRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
) -> Reservation:
    return reschedule_reservation(db, reservation_id, admin, body)


@router.post("/{reservation_id}/cancel", response_model=ReservationOut)
def cancel_reservation_action(
    reservation_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Reservation:
    reservation = get_reservation_or_404(db, reservation_id)
    cancelled, notifications = cancel_reservation_with_notifications(db, reservation, user)
    send_in_background(background_tasks, notifications)
    return cancelled


@router.delete("/{reservation_id}", response_model=ReservationOut)
def delete_reservation(
    reservation_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Reservation:
    reservation = get_reservation_or_404(db, reservation_id)
    cancelled, notifications = cancel_reservation_with_notifications(db, reservation, user)
    send_in_background(background_tasks, notifications)
    return cancelled