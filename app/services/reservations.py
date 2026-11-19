from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import ensure_resource_admin
from app.models import Reservation, ReservationStatus, Role, User

ALLOWED_TRANSITIONS: dict[ReservationStatus, set[ReservationStatus]] = {
    ReservationStatus.PENDING: {
        ReservationStatus.APPROVED,
        ReservationStatus.REJECTED,
        ReservationStatus.AWAITING_TRAINING,
        ReservationStatus.CANCELLED,
    },
    ReservationStatus.AWAITING_TRAINING: {
        ReservationStatus.APPROVED,
        ReservationStatus.REJECTED,
        ReservationStatus.CANCELLED,
    },
    ReservationStatus.APPROVED: {
        ReservationStatus.COMPLETED,
        ReservationStatus.CANCELLED,
    },
    ReservationStatus.REJECTED: set(),
    ReservationStatus.CANCELLED: set(),
    ReservationStatus.COMPLETED: set(),
}

ADMIN_DECISION_STATUSES = {
    ReservationStatus.APPROVED,
    ReservationStatus.REJECTED,
    ReservationStatus.AWAITING_TRAINING,
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_resource_admin(reservation: Reservation, user: User) -> bool:
    return user.role == Role.ADMIN and user in reservation.resource.admins


def get_reservation_or_404(db: Session, reservation_id: int) -> Reservation:
    reservation = db.get(Reservation, reservation_id)
    if reservation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reservation not found")
    return reservation


def validate_transition(
    current_status: ReservationStatus, target_status: ReservationStatus
) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise HTTPException(
            422,
            f"Illegal reservation status transition from {current_status.value} to {target_status.value}",
        )


def cancel_reservation(
    db: Session,
    reservation: Reservation,
    user: User,
    *,
    now: datetime | None = None,
) -> Reservation:
    validate_transition(reservation.status, ReservationStatus.CANCELLED)

    if not _is_resource_admin(reservation, user):
        if reservation.user_id != user.id:
            ensure_resource_admin(reservation.resource, user)

        current_time = _as_utc(now or datetime.now(timezone.utc))
        if current_time >= _as_utc(reservation.start_at):
            raise HTTPException(
                422,
                "Users can only cancel a reservation before its start time",
            )

    reservation.status = ReservationStatus.CANCELLED
    db.commit()
    db.refresh(reservation)
    return reservation


def transition_reservation(
    db: Session,
    reservation: Reservation,
    user: User,
    target_status: ReservationStatus,
    *,
    rejection_reason: str | None = None,
    now: datetime | None = None,
) -> Reservation:
    if target_status == ReservationStatus.CANCELLED:
        return cancel_reservation(db, reservation, user, now=now)

    ensure_resource_admin(reservation.resource, user)
    validate_transition(reservation.status, target_status)

    if target_status == ReservationStatus.REJECTED:
        if not rejection_reason or not rejection_reason.strip():
            raise HTTPException(422, "Rejection reason is required")
        reservation.rejection_reason = rejection_reason.strip()

    if target_status in ADMIN_DECISION_STATUSES:
        reservation.decided_by = user.id
        reservation.decided_at = _as_utc(now or datetime.now(timezone.utc))

    reservation.status = target_status
    db.commit()
    db.refresh(reservation)
    return reservation