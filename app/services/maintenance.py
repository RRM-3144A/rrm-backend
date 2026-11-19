from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MaintenanceWindow, Reservation, ReservationStatus, Resource, User
from app.schemas import MaintenanceCreate, MaintenanceOut
from app.services.schedule import local_timezone


class MaintenanceConflict(Exception):
    """Raised when a new window overlaps an active maintenance window of the same resource."""

    def __init__(self, existing: MaintenanceWindow):
        self.existing = existing
        start, end = to_local(existing.start_at), to_local(existing.end_at)
        super().__init__(
            f"Overlaps the maintenance from {start:%d.%m.%Y %H:%M} to {end:%d.%m.%Y %H:%M}; "
            "please adjust the interval"
        )


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes (stored in UTC); PostgreSQL returns aware ones."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_local(value: datetime) -> datetime:
    return as_utc(value).astimezone(local_timezone())


def to_out(window: MaintenanceWindow) -> MaintenanceOut:
    return MaintenanceOut(
        id=window.id,
        resource_id=window.resource_id,
        start_at=to_local(window.start_at),
        end_at=to_local(window.end_at),
        reason=window.reason,
        created_by=window.created_by,
        cancelled_at=to_local(window.cancelled_at) if window.cancelled_at else None,
    )


def list_windows(
    db: Session, resource: Resource, include_cancelled: bool = False
) -> list[MaintenanceWindow]:
    query = (
        select(MaintenanceWindow)
        .where(MaintenanceWindow.resource_id == resource.id)
        .order_by(MaintenanceWindow.start_at)
    )
    if not include_cancelled:
        query = query.where(MaintenanceWindow.cancelled_at.is_(None))
    return list(db.scalars(query))


def find_overlap(
    db: Session, resource: Resource, start_at: datetime, end_at: datetime
) -> MaintenanceWindow | None:
    """First active window of the resource that overlaps [start_at, end_at).

    Windows that only touch (one ends exactly when the other starts) do not overlap.
    """
    return db.scalars(
        select(MaintenanceWindow)
        .where(
            MaintenanceWindow.resource_id == resource.id,
            MaintenanceWindow.cancelled_at.is_(None),
            MaintenanceWindow.start_at < as_utc(end_at),
            MaintenanceWindow.end_at > as_utc(start_at),
        )
        .order_by(MaintenanceWindow.start_at)
        .limit(1)
    ).first()


def mark_overlapping_reservations_for_review(
    db: Session, resource_id: int, start_at: datetime, end_at: datetime
) -> list[Reservation]:
    """Flags existing APPROVED reservations overlapping [start_at, end_at) with needs_review=True."""
    range_start = as_utc(start_at)
    range_end = as_utc(end_at)

    approved = list(
        db.scalars(
            select(Reservation).where(
                Reservation.resource_id == resource_id,
                Reservation.status == ReservationStatus.APPROVED,
            )
        )
    )
    flagged: list[Reservation] = []
    for reservation in approved:
        if as_utc(reservation.start_at) < range_end and as_utc(reservation.end_at) > range_start:
            reservation.needs_review = True
            flagged.append(reservation)
    return flagged


def clear_resolved_review_flags(db: Session, resource_id: int) -> None:
    """Clears needs_review on APPROVED reservations no longer overlapping any active maintenance."""
    active_windows = list(
        db.scalars(
            select(MaintenanceWindow).where(
                MaintenanceWindow.resource_id == resource_id,
                MaintenanceWindow.cancelled_at.is_(None),
            )
        )
    )
    flagged_reservations = list(
        db.scalars(
            select(Reservation).where(
                Reservation.resource_id == resource_id,
                Reservation.status == ReservationStatus.APPROVED,
                Reservation.needs_review.is_(True),
            )
        )
    )
    for reservation in flagged_reservations:
        res_start = as_utc(reservation.start_at)
        res_end = as_utc(reservation.end_at)
        still_affected = any(
            as_utc(w.start_at) < res_end and as_utc(w.end_at) > res_start
            for w in active_windows
        )
        if not still_affected:
            reservation.needs_review = False


def create_window(
    db: Session, resource: Resource, user: User, body: MaintenanceCreate
) -> MaintenanceWindow:
    existing = find_overlap(db, resource, body.start_at, body.end_at)
    if existing is not None:
        raise MaintenanceConflict(existing)
    # Stored in UTC so that SQLite (tests) and PostgreSQL compare the same values.
    window = MaintenanceWindow(
        resource_id=resource.id,
        start_at=as_utc(body.start_at),
        end_at=as_utc(body.end_at),
        reason=body.reason,
        created_by=user.id,
    )
    db.add(window)
    mark_overlapping_reservations_for_review(db, resource.id, body.start_at, body.end_at)
    return window


def cancel_window(window: MaintenanceWindow) -> None:
    """Cancelling keeps the row for history; cancelling twice keeps the first time."""
    if window.cancelled_at is None:
        window.cancelled_at = datetime.now(timezone.utc)