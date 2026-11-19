from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.models import OperatingSchedule, Resource, ResourceCategory
from app.services.schedule import is_within_schedule
from tests.conftest import auth_headers

TZ = ZoneInfo("Europe/Bucharest")
WEEKDAYS_9_TO_17 = [{"weekday": d, "start_time": "09:00", "end_time": "17:00"} for d in range(5)]


@pytest.fixture
def resource(db, admin):
    category = ResourceCategory(name="Imprimante 3D")
    resource = Resource(name="Prusa MK4", category=category, admins=[admin])
    db.add(resource)
    db.commit()
    return resource


def test_resource_admin_sets_and_reads_schedule(client, resource, admin, student):
    response = client.put(
        f"/resources/{resource.id}/schedule",
        json={"intervals": WEEKDAYS_9_TO_17},
        headers=auth_headers(admin),
    )
    assert response.status_code == 200

    schedule = client.get(f"/resources/{resource.id}/schedule", headers=auth_headers(student))
    assert len(schedule.json()) == 5
    assert schedule.json()[0] == {"weekday": 0, "start_time": "09:00:00", "end_time": "17:00:00"}


def test_put_replaces_previous_schedule(client, resource, admin):
    headers = auth_headers(admin)
    client.put(f"/resources/{resource.id}/schedule", json={"intervals": WEEKDAYS_9_TO_17}, headers=headers)

    client.put(
        f"/resources/{resource.id}/schedule",
        json={"intervals": [{"weekday": 5, "start_time": "10:00", "end_time": "12:00"}]},
        headers=headers,
    )

    schedule = client.get(f"/resources/{resource.id}/schedule", headers=headers).json()
    assert [s["weekday"] for s in schedule] == [5]


def test_student_cannot_change_schedule(client, resource, student):
    response = client.put(
        f"/resources/{resource.id}/schedule", json={"intervals": []}, headers=auth_headers(student)
    )

    assert response.status_code == 403


def test_admin_of_another_resource_cannot_change_schedule(client, resource, make_user):
    other_admin = make_user(role=resource.admins[0].role)

    response = client.put(
        f"/resources/{resource.id}/schedule", json={"intervals": []}, headers=auth_headers(other_admin)
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    "intervals",
    [
        [{"weekday": 0, "start_time": "12:00", "end_time": "09:00"}],
        [{"weekday": 0, "start_time": "09:15", "end_time": "10:00"}],
        [
            {"weekday": 0, "start_time": "09:00", "end_time": "12:00"},
            {"weekday": 0, "start_time": "11:00", "end_time": "13:00"},
        ],
        [{"weekday": 7, "start_time": "09:00", "end_time": "10:00"}],
    ],
    ids=["end-before-start", "not-on-30-min", "overlap", "bad-weekday"],
)
def test_invalid_intervals_are_422(client, resource, admin, intervals):
    response = client.put(
        f"/resources/{resource.id}/schedule", json={"intervals": intervals}, headers=auth_headers(admin)
    )

    assert response.status_code == 422


def _with_schedule(*intervals):
    resource = Resource(name="R")
    resource.schedules = [
        OperatingSchedule(weekday=w, start_time=time(*s), end_time=time(*e)) for w, s, e in intervals
    ]
    return resource


# 2026-11-16 is a Monday.
@pytest.mark.parametrize(
    "start, end, expected",
    [
        ((9, 0), (10, 0), True),
        ((16, 30), (17, 0), True),
        ((8, 30), (9, 30), False),
        ((16, 30), (17, 30), False),
        ((12, 0), (14, 0), True),
    ],
)
def test_is_within_schedule(start, end, expected):
    resource = _with_schedule((0, (9, 0), (12, 0)), (0, (12, 0), (17, 0)))
    start_at = datetime(2026, 11, 16, *start, tzinfo=TZ)
    end_at = datetime(2026, 11, 16, *end, tzinfo=TZ)

    assert is_within_schedule(resource, start_at, end_at) is expected


def test_closed_day_is_outside_schedule():
    resource = _with_schedule((0, (9, 0), (17, 0)))
    saturday = datetime(2026, 11, 21, 10, 0, tzinfo=TZ)

    assert not is_within_schedule(resource, saturday, saturday.replace(hour=11))


def test_gap_between_intervals_is_outside_schedule():
    resource = _with_schedule((0, (9, 0), (12, 0)), (0, (13, 0), (17, 0)))
    start_at = datetime(2026, 11, 16, 11, 30, tzinfo=TZ)

    assert not is_within_schedule(resource, start_at, start_at.replace(hour=13))


def test_utc_times_are_converted_to_local_time():
    resource = _with_schedule((0, (9, 0), (17, 0)))
    start_at = datetime(2026, 11, 16, 7, 0, tzinfo=ZoneInfo("UTC"))

    assert is_within_schedule(resource, start_at, start_at.replace(hour=8))
