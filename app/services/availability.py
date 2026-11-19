from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    MaintenanceWindow,
    OperatingSchedule,
    Reservation,
    ReservationStatus,
    Resource,
    ResourceStatus,
)
from app.schemas import AvailabilitySlot, SlotStatus
from app.services.schedule import SLOT_MINUTES, local_timezone

MAX_RANGE_DAYS = 31

PENDING_STATUSES = {ReservationStatus.PENDING, ReservationStatus.AWAITING_TRAINING}
APPROVED_STATUSES = {ReservationStatus.APPROVED, ReservationStatus.COMPLETED}

Interval = tuple[datetime, datetime]


@dataclass(frozen=True)
class Booking:
    start_at: datetime
    end_at: datetime
    approved: bool


def _as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes (stored in UTC); PostgreSQL returns aware ones."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _overlaps(first: Interval, second: Interval) -> bool:
    return first[0] < second[1] and second[0] < first[1]


def schedule_slots(
    schedules: list[OperatingSchedule], start_date: date, end_date: date, tz: tzinfo
) -> list[Interval]:
    """30-minute slots inside the operating hours, from start_date to end_date inclusive.

    Slots follow the local wall clock, so a 09:00 opening stays 09:00 across DST changes.
    """
    step = timedelta(minutes=SLOT_MINUTES)
    slots: list[Interval] = []
    day = start_date
    while day <= end_date:
        intervals = sorted(
            (s for s in schedules if s.weekday == day.weekday()), key=lambda s: s.start_time
        )
        for interval in intervals:
            cursor = datetime.combine(day, interval.start_time)
            closing = datetime.combine(day, interval.end_time)
            while cursor + step <= closing:
                slots.append((cursor.replace(tzinfo=tz), (cursor + step).replace(tzinfo=tz)))
                cursor += step
        day += timedelta(days=1)
    return slots


def classify_slots(
    slots: list[Interval],
    capacity: int,
    bookings: list[Booking],
    maintenance: list[Interval],
    under_maintenance: bool = False,
) -> list[AvailabilitySlot]:
    """Gives each slot a status.

    MAINTENANCE wins over everything. Otherwise a slot is APPROVED when approved bookings
    fill the capacity, PENDING when approved and pending bookings together fill it (a
    rejection could still free it), and FREE while at least one team can still book it.
    """
    result = []
    for slot in slots:
        if under_maintenance or any(_overlaps(slot, window) for window in maintenance):
            status, free_places = SlotStatus.MAINTENANCE, 0
        else:
            overlapping = [b for b in bookings if _overlaps(slot, (b.start_at, b.end_at))]
            approved = sum(1 for b in overlapping if b.approved)
            if approved >= capacity:
                status = SlotStatus.APPROVED
            elif len(overlapping) >= capacity:
                status = SlotStatus.PENDING
            else:
                status = SlotStatus.FREE
            free_places = max(capacity - len(overlapping), 0)
        result.append(
            AvailabilitySlot(
                start_at=slot[0], end_at=slot[1], status=status, free_places=free_places
            )
        )
    return result


def get_availability(
    db: Session, resource: Resource, start_date: date, end_date: date
) -> list[AvailabilitySlot]:
    if resource.status == ResourceStatus.INACTIVE:
        return []

    slots = schedule_slots(resource.schedules, start_date, end_date, local_timezone())
    if not slots:
        return []
    # Query in UTC: SQLite compares the stored wall-clock text, which is UTC.
    range_start, range_end = _as_utc(slots[0][0]), _as_utc(slots[-1][1])

    reservations = db.scalars(
        select(Reservation).where(
            Reservation.resource_id == resource.id,
            Reservation.status.in_(PENDING_STATUSES | APPROVED_STATUSES),
            Reservation.start_at < range_end,
            Reservation.end_at > range_start,
        )
    )
    bookings = [
        Booking(_as_utc(r.start_at), _as_utc(r.end_at), r.status in APPROVED_STATUSES)
        for r in reservations
    ]

    windows = db.scalars(
        select(MaintenanceWindow).where(
            MaintenanceWindow.resource_id == resource.id,
            MaintenanceWindow.cancelled_at.is_(None),
            MaintenanceWindow.start_at < range_end,
            MaintenanceWindow.end_at > range_start,
        )
    )
    maintenance = [(_as_utc(w.start_at), _as_utc(w.end_at)) for w in windows]

    return classify_slots(
        slots,
        resource.max_concurrent_teams,
        bookings,
        maintenance,
        under_maintenance=resource.status == ResourceStatus.MAINTENANCE,
    )
