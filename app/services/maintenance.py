from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MaintenanceWindow, Resource, User
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
    return window


def cancel_window(window: MaintenanceWindow) -> None:
    """Cancelling keeps the row for history; cancelling twice keeps the first time."""
    if window.cancelled_at is None:
        window.cancelled_at = datetime.now(timezone.utc)
