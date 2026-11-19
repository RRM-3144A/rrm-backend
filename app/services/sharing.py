from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.dependencies import ensure_resource_admin
from app.models import (
    Reservation,
    ReservationStatus,
    Resource,
    ResourceStatus,
    User,
)
from app.schemas import ReservationCreate

MAX_CONCURRENT_TEAMS_LIMIT = 2

BLOCKING_STATUSES = {
    ReservationStatus.PENDING,
    ReservationStatus.AWAITING_TRAINING,
    ReservationStatus.APPROVED,
    ReservationStatus.COMPLETED,
}

APPROVED_STATUSES = {
    ReservationStatus.APPROVED,
    ReservationStatus.COMPLETED,
}

APPROVABLE_STATUSES = {
    ReservationStatus.PENDING,
    ReservationStatus.AWAITING_TRAINING,
}


class CapacityConflictError(Exception):
    """Raised when adding/approving a reservation exceeds max_concurrent_teams."""


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def build_resource_lock_query(resource_id: int) -> Select[tuple[Resource]]:
    """Builds a SELECT ... FOR UPDATE query to serialize bookings per resource in PostgreSQL."""
    return select(Resource).where(Resource.id == resource_id).with_for_update()


def lock_resource_for_booking(db: Session, resource_id: int) -> Resource:
    resource = db.scalar(build_resource_lock_query(resource_id))
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")
    return resource


def peak_concurrent_reservations(
    existing_intervals: list[tuple[datetime, datetime]],
    start_at: datetime,
    end_at: datetime,
) -> int:
    """Returns the maximum number of overlapping reservations at any instant in [start_at, end_at)."""
    target_start = _as_utc(start_at)
    target_end = _as_utc(end_at)
    if target_start >= target_end:
        return 0

    clamped: list[tuple[datetime, datetime]] = []
    boundaries = {target_start, target_end}
    for raw_start, raw_end in existing_intervals:
        s = max(_as_utc(raw_start), target_start)
        e = min(_as_utc(raw_end), target_end)
        if s < e:
            clamped.append((s, e))
            boundaries.add(s)
            boundaries.add(e)

    if not clamped:
        return 0

    sorted_points = sorted(boundaries)
    peak = 0
    for idx in range(len(sorted_points) - 1):
        seg_start = sorted_points[idx]
        seg_end = sorted_points[idx + 1]
        active_count = sum(1 for s, e in clamped if s < seg_end and seg_start < e)
        if active_count > peak:
            peak = active_count
    return peak


def ensure_capacity_available(
    db: Session,
    resource: Resource,
    start_at: datetime,
    end_at: datetime,
    *,
    statuses: set[ReservationStatus] = BLOCKING_STATUSES,
    exclude_reservation_id: int | None = None,
) -> None:
    """Checks inside the active DB transaction that concurrent overlapping bookings stay <= limit."""
    limit = min(resource.max_concurrent_teams, MAX_CONCURRENT_TEAMS_LIMIT)
    range_start = _as_utc(start_at)
    range_end = _as_utc(end_at)

    query = select(Reservation).where(
        Reservation.resource_id == resource.id,
        Reservation.status.in_(statuses),
        Reservation.start_at < range_end,
        Reservation.end_at > range_start,
    )
    if exclude_reservation_id is not None:
        query = query.where(Reservation.id != exclude_reservation_id)

    overlapping = list(db.scalars(query))
    peak = peak_concurrent_reservations(
        [(r.start_at, r.end_at) for r in overlapping],
        range_start,
        range_end,
    )
    if peak >= limit:
        raise CapacityConflictError(
            f"Resource '{resource.name}' allows at most {limit} concurrent team(s) on this interval"
        )


def create_reservation_checked(
    db: Session,
    user: User,
    data: ReservationCreate,
) -> Reservation:
    start_at = _as_utc(data.start_at)
    end_at = _as_utc(data.end_at)
    if start_at >= end_at:
        raise HTTPException(422, "start_at must be before end_at")

    resource = lock_resource_for_booking(db, data.resource_id)
    if resource.status != ResourceStatus.ACTIVE:
        raise HTTPException(422, "Resource is not active for reservations")

    ensure_capacity_available(db, resource, start_at, end_at, statuses=BLOCKING_STATUSES)

    reservation = Reservation(
        user_id=user.id,
        resource_id=resource.id,
        team_id=data.team_id if data.team_id is not None else user.team_id,
        start_at=start_at,
        end_at=end_at,
        purpose=data.purpose,
        status=ReservationStatus.PENDING,
    )
    db.add(reservation)
    db.commit()
    db.refresh(reservation)
    return reservation


def approve_reservation_checked(
    db: Session,
    reservation_id: int,
    admin: User,
) -> Reservation:
    reservation = db.get(Reservation, reservation_id)
    if reservation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reservation not found")

    resource = lock_resource_for_booking(db, reservation.resource_id)
    ensure_resource_admin(resource, admin)

    if reservation.status not in APPROVABLE_STATUSES:
        raise HTTPException(
            422,
            f"Cannot approve reservation in status {reservation.status.value}",
        )

    ensure_capacity_available(
        db,
        resource,
        reservation.start_at,
        reservation.end_at,
        statuses=APPROVED_STATUSES,
        exclude_reservation_id=reservation.id,
    )

    reservation.status = ReservationStatus.APPROVED
    reservation.decided_by = admin.id
    reservation.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(reservation)
    return reservation