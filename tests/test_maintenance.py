from datetime import time

import pytest

from app.models import MaintenanceWindow, OperatingSchedule, Resource, ResourceCategory, Role
from tests.conftest import auth_headers


def _window(start: str, end: str, reason: str = "Calibrare") -> dict:
    """Local (Bucharest, UTC+2 in November) times on Monday 2026-11-23."""
    return {
        "start_at": f"2026-11-23T{start}:00+02:00",
        "end_at": f"2026-11-23T{end}:00+02:00",
        "reason": reason,
    }


@pytest.fixture
def resource(db, admin):
    category = ResourceCategory(name="Centrifuge")
    resource = Resource(name="Eppendorf 5430", category=category, admins=[admin])
    db.add(resource)
    db.commit()
    return resource


def _create(client, resource, user, body):
    return client.post(
        f"/resources/{resource.id}/maintenance", json=body, headers=auth_headers(user)
    )


def _list(client, resource, user, **params):
    response = client.get(
        f"/resources/{resource.id}/maintenance", params=params, headers=auth_headers(user)
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_resource_admin_creates_maintenance_window(client, resource, admin):
    response = _create(client, resource, admin, _window("09:00", "11:00"))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["start_at"] == "2026-11-23T09:00:00+02:00"
    assert body["end_at"] == "2026-11-23T11:00:00+02:00"
    assert body["reason"] == "Calibrare"
    assert body["created_by"] == admin.id
    assert body["cancelled_at"] is None


def test_utc_input_is_returned_in_local_time(client, resource, admin):
    body = {"start_at": "2026-11-23T07:00:00Z", "end_at": "2026-11-23T08:00:00Z", "reason": "X"}

    response = _create(client, resource, admin, body)

    assert response.json()["start_at"] == "2026-11-23T09:00:00+02:00"


def test_student_cannot_create_maintenance(client, resource, student):
    assert _create(client, resource, student, _window("09:00", "10:00")).status_code == 403


def test_admin_of_another_resource_cannot_create_maintenance(client, resource, make_user):
    other_admin = make_user(Role.ADMIN)

    assert _create(client, resource, other_admin, _window("09:00", "10:00")).status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        _window("11:00", "09:00"),
        _window("09:00", "09:00"),
        {"start_at": "2026-11-23T09:00:00", "end_at": "2026-11-23T10:00:00", "reason": "X"},
        _window("09:00", "10:00", reason="   "),
        {"start_at": "2026-11-23T09:00:00+02:00", "end_at": "2026-11-23T10:00:00+02:00"},
    ],
    ids=["end-before-start", "empty-interval", "no-timezone", "blank-reason", "missing-reason"],
)
def test_invalid_window_is_422(client, resource, admin, body):
    assert _create(client, resource, admin, body).status_code == 422


@pytest.mark.parametrize(
    "start, end",
    [("10:00", "12:00"), ("08:00", "09:30"), ("09:30", "10:30"), ("08:00", "12:00")],
    ids=["overlaps-end", "overlaps-start", "inside", "covers"],
)
def test_overlapping_window_is_409_with_adjust_message(client, resource, admin, start, end):
    _create(client, resource, admin, _window("09:00", "11:00"))

    response = _create(client, resource, admin, _window(start, end))

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "23.11.2026 09:00" in detail and "23.11.2026 11:00" in detail
    assert "adjust" in detail


def test_adjacent_windows_are_allowed(client, resource, admin):
    _create(client, resource, admin, _window("09:00", "11:00"))

    assert _create(client, resource, admin, _window("11:00", "12:00")).status_code == 201
    assert _create(client, resource, admin, _window("08:00", "09:00")).status_code == 201


def test_cancelled_window_does_not_block_a_new_one(client, db, resource, admin):
    window_id = _create(client, resource, admin, _window("09:00", "11:00")).json()["id"]
    client.delete(f"/resources/{resource.id}/maintenance/{window_id}", headers=auth_headers(admin))

    assert _create(client, resource, admin, _window("09:00", "11:00")).status_code == 201


def test_windows_of_other_resources_do_not_overlap(client, db, resource, admin):
    other = Resource(name="Alta centrifugă", category=resource.category, admins=[admin])
    db.add(other)
    db.commit()
    _create(client, other, admin, _window("09:00", "11:00"))

    assert _create(client, resource, admin, _window("09:00", "11:00")).status_code == 201


def test_list_is_sorted_and_hides_cancelled_by_default(client, resource, admin, student):
    later = _create(client, resource, admin, _window("14:00", "15:00")).json()["id"]
    earlier = _create(client, resource, admin, _window("09:00", "10:00")).json()["id"]
    cancelled = _create(client, resource, admin, _window("11:00", "12:00")).json()["id"]
    client.delete(f"/resources/{resource.id}/maintenance/{cancelled}", headers=auth_headers(admin))

    assert [w["id"] for w in _list(client, resource, student)] == [earlier, later]
    with_cancelled = _list(client, resource, student, include_cancelled=True)
    assert [w["id"] for w in with_cancelled] == [earlier, cancelled, later]
    assert with_cancelled[1]["cancelled_at"] is not None


def test_cancel_keeps_the_window_with_cancelled_at(client, db, resource, admin):
    window_id = _create(client, resource, admin, _window("09:00", "10:00")).json()["id"]

    response = client.delete(
        f"/resources/{resource.id}/maintenance/{window_id}", headers=auth_headers(admin)
    )

    assert response.status_code == 204
    assert db.get(MaintenanceWindow, window_id).cancelled_at is not None


def test_student_cannot_cancel_maintenance(client, resource, admin, student):
    window_id = _create(client, resource, admin, _window("09:00", "10:00")).json()["id"]

    response = client.delete(
        f"/resources/{resource.id}/maintenance/{window_id}", headers=auth_headers(student)
    )

    assert response.status_code == 403


def test_cancel_window_of_another_resource_is_404(client, db, resource, admin):
    other = Resource(name="Alta centrifugă", category=resource.category, admins=[admin])
    db.add(other)
    db.commit()
    window_id = _create(client, other, admin, _window("09:00", "10:00")).json()["id"]

    response = client.delete(
        f"/resources/{resource.id}/maintenance/{window_id}", headers=auth_headers(admin)
    )

    assert response.status_code == 404


def test_cancel_unknown_window_is_404(client, resource, admin):
    response = client.delete(f"/resources/{resource.id}/maintenance/999", headers=auth_headers(admin))

    assert response.status_code == 404


def test_unknown_resource_is_404(client, admin):
    response = client.get("/resources/999/maintenance", headers=auth_headers(admin))

    assert response.status_code == 404


def test_requires_sign_in(client, resource):
    assert client.get(f"/resources/{resource.id}/maintenance").status_code == 401


def test_new_window_shows_up_in_availability(client, db, resource, admin, student):
    resource.schedules = [OperatingSchedule(weekday=0, start_time=time(9), end_time=time(10))]
    db.commit()
    _create(client, resource, admin, _window("09:30", "10:00"))

    slots = client.get(
        f"/resources/{resource.id}/availability",
        params={"start_date": "2026-11-23", "end_date": "2026-11-23"},
        headers=auth_headers(student),
    ).json()

    assert [slot["status"] for slot in slots] == ["FREE", "MAINTENANCE"]
