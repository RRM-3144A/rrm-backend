from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Notification,
    Reservation,
    Resource,
    ResourceStatus,
    User,
    WaitlistEntry,
)
from app.schemas import WaitlistCreate
from app.services.availability import PENDING_STATUSES, APPROVED_STATUSES, _as_utc, _overlaps
from app.services.notifications import notify_waitlist_slot_available
from app.services.reservations import (
    _ensure_no_maintenance_overlap,
    _validate_operating_schedule,
    _validate_slot_interval,
)
from app.services.schedule import local_timezone
from app.services.sharing import (
    BLOCKING_STATUSES,
    CapacityConflictError,
    ensure_capacity_available,
    lock_resource_for_booking,
)


def join_waitlist(db: Session, user: User, body: WaitlistCreate) -> WaitlistEntry:
    start_utc = _as_utc(body.start_at)
    end_utc = _as_utc(body.end_at)

    tz = local_timezone()
    local_start = start_utc.astimezone(tz)
    local_end = end_utc.astimezone(tz)

    _validate_slot_interval(local_start, local_end)

    resource = lock_resource_for_booking(db, body.resource_id)

    if resource.status != ResourceStatus.ACTIVE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Resource is not active",
        )

    if resource.max_duration_min is not None:
        duration_min = int((end_utc - start_utc).total_seconds()) // 60
        if duration_min > resource.max_duration_min:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Interval exceeds maximum duration of {resource.max_duration_min} minutes",
            )

    _ensure_no_maintenance_overlap(db, resource.id, start_utc, end_utc)
    _validate_operating_schedule(db, resource.id, local_start, local_end)

    # Nu permitem înscrierea dacă utilizatorul are deja o rezervare pe acest slot
    user_reservations = list(
        db.scalars(
            select(Reservation).where(
                Reservation.resource_id == resource.id,
                Reservation.user_id == user.id,
                Reservation.status.in_(PENDING_STATUSES | APPROVED_STATUSES),
            )
        )
    )
    if any(
        _overlaps((start_utc, end_utc), (_as_utc(res.start_at), _as_utc(res.end_at)))
        for res in user_reservations
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You already have a reservation overlapping this slot",
        )

    # Lista de așteptare se folosește doar când slotul este ocupat complet
    try:
        ensure_capacity_available(
            db,
            resource,
            start_utc,
            end_utc,
            statuses=BLOCKING_STATUSES,
        )
    except CapacityConflictError:
        pass
    else:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Slot is currently available and can be reserved directly",
        )

    existing = db.scalar(
        select(WaitlistEntry).where(
            WaitlistEntry.user_id == user.id,
            WaitlistEntry.resource_id == resource.id,
            WaitlistEntry.start_at == start_utc,
            WaitlistEntry.end_at == end_utc,
        )
    )
    if existing is not None:
        if existing.notified_at is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "You are already on the waitlist for this slot",
            )
        existing.notified_at = None
        db.commit()
        db.refresh(existing)
        return existing

    entry = WaitlistEntry(
        user_id=user.id,
        resource_id=resource.id,
        start_at=start_utc,
        end_at=end_utc,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_my_waitlist(db: Session, user: User) -> list[WaitlistEntry]:
    return list(
        db.scalars(
            select(WaitlistEntry)
            .where(WaitlistEntry.user_id == user.id)
            .order_by(WaitlistEntry.start_at.asc(), WaitlistEntry.id.asc())
        )
    )


def leave_waitlist(db: Session, entry_id: int, user: User) -> None:
    entry = db.get(WaitlistEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Waitlist entry not found")
    if entry.user_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can only remove your own waitlist entries",
        )
    db.delete(entry)
    db.commit()


def notify_waitlist_on_cancellation(
    db: Session,
    reservation: Reservation,
    *,
    now: datetime | None = None,
) -> list[Notification]:
    """Notifies active waitlist entries whose slot overlaps the cancelled reservation and now has free capacity."""
    resource = db.get(Resource, reservation.resource_id)
    if resource is None or resource.status != ResourceStatus.ACTIVE:
        return []

    res_start = _as_utc(reservation.start_at)
    res_end = _as_utc(reservation.end_at)
    current_time = _as_utc(now or datetime.now(timezone.utc))

    candidates = list(
        db.scalars(
            select(WaitlistEntry)
            .where(
                WaitlistEntry.resource_id == reservation.resource_id,
                WaitlistEntry.notified_at.is_(None),
            )
            .order_by(WaitlistEntry.created_at.asc(), WaitlistEntry.id.asc())
        )
    )

    notifications: list[Notification] = []
    for entry in candidates:
        entry_start = _as_utc(entry.start_at)
        entry_end = _as_utc(entry.end_at)
        if not _overlaps((res_start, res_end), (entry_start, entry_end)):
            continue
        if entry_end <= current_time:
            continue

        try:
            ensure_capacity_available(
                db,
                resource,
                entry_start,
                entry_end,
                statuses=BLOCKING_STATUSES,
            )
        except CapacityConflictError:
            continue

        entry.notified_at = current_time
        notifications.append(notify_waitlist_slot_available(db, entry))

    return notifications