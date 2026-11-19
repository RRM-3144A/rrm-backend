from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models import (
    MaintenanceWindow,
    OperatingSchedule,
    Reservation,
    ReservationStatus,
    Resource,
    ResourceCategory,
    ResourceStatus,
)
from tests.conftest import auth_headers

TZ = ZoneInfo("Europe/Bucharest")
MONDAY = "2026-11-23"


def _utc(hour: int, minute: int = 0, day: int = 23) -> datetime:
    """Local time on 2026-11-<day>, stored in UTC like the API does."""
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ).astimezone(timezone.utc)


@pytest.fixture
def resource(db, admin):
    category = ResourceCategory(name="Microscoape")
    resource = Resource(name="Zeiss Axio", category=category, admins=[admin])
    resource.schedules = [
        OperatingSchedule(weekday=d, start_time=time(9, 0), end_time=time(12, 0)) for d in range(5)
    ]
    db.add(resource)
    db.commit()
    return resource


def _reserve(db, resource, user, start, end, status=ReservationStatus.APPROVED):
    db.add(
        Reservation(user_id=user.id, resource_id=resource.id, start_at=start, end_at=end, status=status)
    )
    db.commit()


def _availability(client, resource, user, start=MONDAY, end=MONDAY):
    response = client.get(
        f"/resources/{resource.id}/availability",
        params={"start_date": start, "end_date": end},
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _statuses(slots):
    return [slot["status"] for slot in slots]


def test_returns_free_30_minute_slots_within_schedule(client, resource, student):
    slots = _availability(client, resource, student)

    assert len(slots) == 6
    assert slots[0] == {
        "start_at": "2026-11-23T09:00:00+02:00",
        "end_at": "2026-11-23T09:30:00+02:00",
        "status": "FREE",
        "free_places": 1,
    }
    assert slots[-1]["end_at"] == "2026-11-23T12:00:00+02:00"
    assert set(_statuses(slots)) == {"FREE"}


def test_range_spans_several_days_and_skips_closed_days(client, resource, student):
    # Friday 20 -> Monday 23: the weekend has no operating hours.
    slots = _availability(client, resource, student, start="2026-11-20", end=MONDAY)

    assert len(slots) == 12
    assert {slot["start_at"][:10] for slot in slots} == {"2026-11-20", MONDAY}


def test_pending_and_approved_reservations_mark_slots(client, db, resource, student):
    _reserve(db, resource, student, _utc(9), _utc(10), ReservationStatus.APPROVED)
    _reserve(db, resource, student, _utc(10), _utc(10, 30), ReservationStatus.PENDING)
    _reserve(db, resource, student, _utc(10, 30), _utc(11), ReservationStatus.AWAITING_TRAINING)

    slots = _availability(client, resource, student)

    assert _statuses(slots) == ["APPROVED", "APPROVED", "PENDING", "PENDING", "FREE", "FREE"]
    assert slots[0]["free_places"] == 0


@pytest.mark.parametrize("status", [ReservationStatus.CANCELLED, ReservationStatus.REJECTED])
def test_cancelled_and_rejected_reservations_free_the_slot(client, db, resource, student, status):
    _reserve(db, resource, student, _utc(9), _utc(12), status)

    assert set(_statuses(_availability(client, resource, student))) == {"FREE"}


def test_shared_resource_stays_free_until_capacity_is_filled(client, db, resource, student, make_user):
    resource.max_concurrent_teams = 2
    db.commit()
    other = make_user()
    _reserve(db, resource, student, _utc(9), _utc(10), ReservationStatus.APPROVED)
    _reserve(db, resource, other, _utc(9), _utc(9, 30), ReservationStatus.APPROVED)
    _reserve(db, resource, other, _utc(9, 30), _utc(10), ReservationStatus.PENDING)

    slots = _availability(client, resource, student)

    assert _statuses(slots[:3]) == ["APPROVED", "PENDING", "FREE"]
    assert [slot["free_places"] for slot in slots[:3]] == [0, 0, 2]


def test_maintenance_window_overrides_reservations(client, db, resource, student, admin):
    _reserve(db, resource, student, _utc(9), _utc(10))
    db.add_all(
        [
            MaintenanceWindow(
                resource_id=resource.id, start_at=_utc(9, 30), end_at=_utc(11), reason="Calibrare"
            ),
            MaintenanceWindow(
                resource_id=resource.id,
                start_at=_utc(11),
                end_at=_utc(12),
                reason="Anulată",
                cancelled_at=datetime.now(timezone.utc),
            ),
        ]
    )
    db.commit()

    slots = _availability(client, resource, student)

    assert _statuses(slots) == [
        "APPROVED", "MAINTENANCE", "MAINTENANCE", "MAINTENANCE", "FREE", "FREE"
    ]


def test_reservations_on_other_resources_are_ignored(client, db, resource, student):
    other = Resource(name="Alt microscop", category=resource.category)
    db.add(other)
    db.commit()
    _reserve(db, other, student, _utc(9), _utc(12))

    assert set(_statuses(_availability(client, resource, student))) == {"FREE"}


def test_resource_in_maintenance_has_only_maintenance_slots(client, db, resource, student):
    resource.status = ResourceStatus.MAINTENANCE
    db.commit()

    assert set(_statuses(_availability(client, resource, student))) == {"MAINTENANCE"}


def test_inactive_resource_has_no_slots(client, db, resource, student):
    resource.status = ResourceStatus.INACTIVE
    db.commit()

    assert _availability(client, resource, student) == []


@pytest.mark.parametrize(
    "params",
    [
        {"start_date": "2026-11-24", "end_date": "2026-11-23"},
        {"start_date": "2026-11-01", "end_date": "2026-12-02"},
        {"start_date": "2026-11-23"},
        {"start_date": "23.11.2026", "end_date": "2026-11-23"},
    ],
    ids=["end-before-start", "longer-than-31-days", "missing-end", "bad-date"],
)
def test_invalid_range_is_422(client, resource, student, params):
    response = client.get(
        f"/resources/{resource.id}/availability", params=params, headers=auth_headers(student)
    )

    assert response.status_code == 422


def test_unknown_resource_is_404(client, student):
    response = client.get(
        "/resources/999/availability",
        params={"start_date": MONDAY, "end_date": MONDAY},
        headers=auth_headers(student),
    )

    assert response.status_code == 404


def test_requires_sign_in(client, resource):
    response = client.get(
        f"/resources/{resource.id}/availability",
        params={"start_date": MONDAY, "end_date": MONDAY},
    )

    assert response.status_code == 401
