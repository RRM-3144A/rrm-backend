from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.config import settings
from app.models import OperatingSchedule, Resource
from app.schemas import ScheduleInterval

SLOT_MINUTES = 30


class ScheduleError(ValueError):
    """Raised when a set of operating intervals is not valid."""


def _on_slot_boundary(value: time) -> bool:
    return value.second == 0 and value.microsecond == 0 and value.minute % SLOT_MINUTES == 0


def validate_intervals(intervals: list[ScheduleInterval]) -> None:
    by_day: dict[int, list[ScheduleInterval]] = {}
    for interval in intervals:
        if interval.start_time >= interval.end_time:
            raise ScheduleError("Each interval must end after it starts")
        if not (_on_slot_boundary(interval.start_time) and _on_slot_boundary(interval.end_time)):
            raise ScheduleError("Intervals must start and end on a :00 or :30 boundary")
        by_day.setdefault(interval.weekday, []).append(interval)

    for day_intervals in by_day.values():
        day_intervals.sort(key=lambda i: i.start_time)
        for previous, current in zip(day_intervals, day_intervals[1:]):
            if current.start_time < previous.end_time:
                raise ScheduleError("Intervals on the same day must not overlap")


def local_timezone() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def is_within_schedule(resource: Resource, start: datetime, end: datetime) -> bool:
    """True when [start, end) lies entirely inside the resource's operating hours.

    Times are compared in the configured local timezone. A booking may span adjacent
    intervals of the same day (e.g. 08:00-12:00 and 12:00-16:00) but never crosses midnight,
    since no interval can end at 24:00.
    """
    tz = local_timezone()
    local_start, local_end = start.astimezone(tz), end.astimezone(tz)
    if local_start.date() != local_end.date():
        return False

    intervals = sorted(
        (s for s in resource.schedules if s.weekday == local_start.weekday()),
        key=lambda s: s.start_time,
    )
    cursor = local_start.time()
    for interval in intervals:
        if interval.start_time <= cursor < interval.end_time:
            cursor = interval.end_time
            if cursor >= local_end.time():
                return True
    return False


def replace_schedule(resource: Resource, intervals: list[ScheduleInterval]) -> None:
    validate_intervals(intervals)
    resource.schedules = [
        OperatingSchedule(
            weekday=interval.weekday,
            start_time=interval.start_time,
            end_time=interval.end_time,
        )
        for interval in intervals
    ]
