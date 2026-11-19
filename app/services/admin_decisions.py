from datetime import datetime, timezone
from app.models import Notification
from app.services.notifications import notify_training_completed

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import ensure_resource_admin
from app.models import (
    MaintenanceWindow,
    Reservation,
    ReservationStatus,
    Resource,
    ResourceStatus,
    User,
)

APPROVABLE_STATUSES = {
    ReservationStatus.PENDING,
    ReservationStatus.AWAITING_TRAINING,
}

OCCUPYING_STATUSES = {
    ReservationStatus.APPROVED,
    ReservationStatus.COMPLETED,
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _get_reservation_and_lock_resource(
    db: Session, reservation_id: int, admin: User
) -> tuple[Reservation, Resource]:
    reservation = db.get(Reservation, reservation_id)
    if reservation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reservation not found")

    resource = db.scalar(
        select(Resource).where(Resource.id == reservation.resource_id).with_for_update()
    )
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")

    ensure_resource_admin(resource, admin)
    return reservation, resource


def _peak_overlapping_bookings(
    db: Session,
    resource_id: int,
    start_at: datetime,
    end_at: datetime,
    exclude_reservation_id: int,
) -> int:
    range_start = _as_utc(start_at)
    range_end = _as_utc(end_at)

    existing = list(
        db.scalars(
            select(Reservation).where(
                Reservation.resource_id == resource_id,
                Reservation.id != exclude_reservation_id,
                Reservation.status.in_(OCCUPYING_STATUSES),
                Reservation.start_at < range_end,
                Reservation.end_at > range_start,
            )
        )
    )
    if not existing:
        return 0

    clamped: list[tuple[datetime, datetime]] = []
    boundaries = {range_start, range_end}
    for item in existing:
        s = max(_as_utc(item.start_at), range_start)
        e = min(_as_utc(item.end_at), range_end)
        if s < e:
            clamped.append((s, e))
            boundaries.add(s)
            boundaries.add(e)

    sorted_points = sorted(boundaries)
    peak = 0
    for i in range(len(sorted_points) - 1):
        seg_start, seg_end = sorted_points[i], sorted_points[i + 1]
        count = sum(1 for s, e in clamped if s < seg_end and seg_start < e)
        if count > peak:
            peak = count
    return peak


def _ensure_slot_can_be_blocked(
    db: Session, resource: Resource, reservation: Reservation
) -> None:
    if resource.status != ResourceStatus.ACTIVE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot approve reservation while resource is {resource.status.value}",
        )

    range_start = _as_utc(reservation.start_at)
    range_end = _as_utc(reservation.end_at)

    maintenance_conflict = db.scalar(
        select(MaintenanceWindow.id).where(
            MaintenanceWindow.resource_id == resource.id,
            MaintenanceWindow.cancelled_at.is_(None),
            MaintenanceWindow.start_at < range_end,
            MaintenanceWindow.end_at > range_start,
        )
    )
    if maintenance_conflict is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot approve reservation because the slot overlaps a maintenance window",
        )

    peak = _peak_overlapping_bookings(
        db, resource.id, range_start, range_end, reservation.id
    )
    if peak >= resource.max_concurrent_teams:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Slot is already full (maximum {resource.max_concurrent_teams} concurrent team(s))",
        )


def approve_reservation(
    db: Session, reservation_id: int, admin: User
) -> Reservation:
    reservation, resource = _get_reservation_and_lock_resource(db, reservation_id, admin)

    if reservation.status == ReservationStatus.CANCELLED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Reservation has already been cancelled and cannot be approved",
        )
    if reservation.status not in APPROVABLE_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot approve reservation in status {reservation.status.value}",
        )

    _ensure_slot_can_be_blocked(db, resource, reservation)

    reservation.status = ReservationStatus.APPROVED
    reservation.decided_by = admin.id
    reservation.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(reservation)
    return reservation


def reject_reservation(
    db: Session,
    reservation_id: int,
    admin: User,
    reason: str | None,
) -> Reservation:
    if reason is None or not reason.strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Rejection reason is required",
        )

    reservation, _ = _get_reservation_and_lock_resource(db, reservation_id, admin)

    if reservation.status == ReservationStatus.CANCELLED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Reservation has already been cancelled and cannot be rejected",
        )
    if reservation.status not in APPROVABLE_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot reject reservation in status {reservation.status.value}",
        )

    reservation.status = ReservationStatus.REJECTED
    reservation.rejection_reason = reason.strip()
    reservation.decided_by = admin.id
    reservation.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(reservation)
    return reservation


def mark_awaiting_training(
    db: Session, reservation_id: int, admin: User
) -> Reservation:
    reservation, _ = _get_reservation_and_lock_resource(db, reservation_id, admin)

    if reservation.status == ReservationStatus.CANCELLED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Reservation has already been cancelled",
        )
    if reservation.status != ReservationStatus.PENDING:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot move reservation in status {reservation.status.value} to AWAITING_TRAINING",
        )

    reservation.status = ReservationStatus.AWAITING_TRAINING
    reservation.decided_by = admin.id
    reservation.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(reservation)
    return reservation

def complete_training(
    db: Session, reservation_id: int, admin: User
) -> tuple[Reservation, Notification]:
    reservation, _ = _get_reservation_and_lock_resource(db, reservation_id, admin)

    if reservation.status == ReservationStatus.CANCELLED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Reservation has already been cancelled",
        )
    if reservation.status != ReservationStatus.AWAITING_TRAINING:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot complete training for reservation in status {reservation.status.value}",
        )

    reservation.status = ReservationStatus.PENDING
    reservation.decided_by = admin.id
    reservation.decided_at = datetime.now(timezone.utc)
    notification = notify_training_completed(db, reservation)
    db.commit()
    db.refresh(reservation)
    return reservation, notification