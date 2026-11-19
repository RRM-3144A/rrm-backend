from datetime import datetime, time

from app.models import (
    MaintenanceWindow,
    OperatingSchedule,
    Reservation,
    ReservationStatus,
    Resource,
    ResourceCategory,
    ResourceStatus,
)
from app.services.schedule import local_timezone
from tests.conftest import auth_headers


def _dt(hour: int, minute: int = 0) -> datetime:
    # 2026-11-23 is a Monday (weekday = 0)
    return datetime(2026, 11, 23, hour, minute, tzinfo=local_timezone())


def _setup_resource(
    db,
    *,
    resource_status: ResourceStatus = ResourceStatus.ACTIVE,
    max_concurrent_teams: int = 1,
    weekday: int = 0,
    start_time: time = time(8, 0),
    end_time: time = time(20, 0),
) -> Resource:
    category = ResourceCategory(name=f"Category-{id(db)}-{weekday}-{resource_status.value}")
    db.add(category)
    db.flush()

    resource = Resource(
        name="Oscilloscope Rig",
        category_id=category.id,
        status=resource_status,
        max_concurrent_teams=max_concurrent_teams,
    )
    db.add(resource)
    db.flush()

    schedule = OperatingSchedule(
        resource_id=resource.id,
        weekday=weekday,
        start_time=start_time,
        end_time=end_time,
    )
    db.add(schedule)
    db.commit()
    db.refresh(resource)
    return resource


def test_create_reservation_success(client, db, student):
    resource = _setup_resource(db)

    response = client.post(
        "/reservations",
        headers=auth_headers(student),
        json={
            "resource_id": resource.id,
            "start_at": _dt(10, 0).isoformat(),
            "end_at": _dt(11, 30).isoformat(),
            "purpose": "Signal measurements",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["resource_id"] == resource.id
    assert data["user_id"] == student.id
    assert data["status"] == "PENDING"
    assert data["purpose"] == "Signal measurements"


def test_create_reservation_unauthenticated(client, db):
    resource = _setup_resource(db)

    response = client.post(
        "/reservations",
        json={
            "resource_id": resource.id,
            "start_at": _dt(10, 0).isoformat(),
            "end_at": _dt(11, 0).isoformat(),
        },
    )
    assert response.status_code == 401


def test_create_reservation_resource_not_found(client, student):
    response = client.post(
        "/reservations",
        headers=auth_headers(student),
        json={
            "resource_id": 99999,
            "start_at": _dt(10, 0).isoformat(),
            "end_at": _dt(11, 0).isoformat(),
        },
    )
    assert response.status_code == 404


def test_create_reservation_maintenance_status(client, db, student):
    resource = _setup_resource(db, resource_status=ResourceStatus.MAINTENANCE)

    response = client.post(
        "/reservations",
        headers=auth_headers(student),
        json={
            "resource_id": resource.id,
            "start_at": _dt(10, 0).isoformat(),
            "end_at": _dt(11, 0).isoformat(),
        },
    )
    assert response.status_code == 422
    assert "maintenance" in response.json()["detail"].lower()


def test_create_reservation_scheduled_maintenance_window(client, db, student, admin):
    resource = _setup_resource(db)
    window = MaintenanceWindow(
        resource_id=resource.id,
        start_at=_dt(10, 30),
        end_at=_dt(12, 0),
        reason="Probe calibration",
        created_by=admin.id,
    )
    db.add(window)
    db.commit()

    response = client.post(
        "/reservations",
        headers=auth_headers(student),
        json={
            "resource_id": resource.id,
            "start_at": _dt(10, 0).isoformat(),
            "end_at": _dt(11, 0).isoformat(),
        },
    )
    assert response.status_code == 422
    assert "maintenance" in response.json()["detail"].lower()


def test_create_reservation_inactive_resource(client, db, student):
    resource = _setup_resource(db, resource_status=ResourceStatus.INACTIVE)

    response = client.post(
        "/reservations",
        headers=auth_headers(student),
        json={
            "resource_id": resource.id,
            "start_at": _dt(10, 0).isoformat(),
            "end_at": _dt(11, 0).isoformat(),
        },
    )
    assert response.status_code == 422


def test_create_reservation_outside_operating_schedule(client, db, student):
    resource = _setup_resource(db, weekday=0, start_time=time(9, 0), end_time=time(17, 0))

    response = client.post(
        "/reservations",
        headers=auth_headers(student),
        json={
            "resource_id": resource.id,
            "start_at": _dt(8, 0).isoformat(),
            "end_at": _dt(9, 30).isoformat(),
        },
    )
    assert response.status_code == 422
    assert "schedule" in response.json()["detail"].lower()


def test_create_reservation_invalid_30_min_slot(client, db, student):
    resource = _setup_resource(db)

    response = client.post(
        "/reservations",
        headers=auth_headers(student),
        json={
            "resource_id": resource.id,
            "start_at": _dt(10, 15).isoformat(),
            "end_at": _dt(11, 0).isoformat(),
        },
    )
    assert response.status_code == 422
    assert "30" in response.json()["detail"]


def test_create_reservation_slot_occupied_conflict(client, db, student, make_user):
    resource = _setup_resource(db)
    other_student = make_user()

    existing = Reservation(
        user_id=other_student.id,
        resource_id=resource.id,
        start_at=_dt(10, 0),
        end_at=_dt(11, 0),
        status=ReservationStatus.PENDING,
    )
    db.add(existing)
    db.commit()

    response = client.post(
        "/reservations",
        headers=auth_headers(student),
        json={
            "resource_id": resource.id,
            "start_at": _dt(10, 30).isoformat(),
            "end_at": _dt(11, 30).isoformat(),
        },
    )
    assert response.status_code == 409


def test_create_reservation_adjacent_slot_allowed(client, db, student, make_user):
    resource = _setup_resource(db)
    other_student = make_user()

    existing = Reservation(
        user_id=other_student.id,
        resource_id=resource.id,
        start_at=_dt(10, 0),
        end_at=_dt(11, 0),
        status=ReservationStatus.APPROVED,
    )
    db.add(existing)
    db.commit()

    response = client.post(
        "/reservations",
        headers=auth_headers(student),
        json={
            "resource_id": resource.id,
            "start_at": _dt(11, 0).isoformat(),
            "end_at": _dt(12, 0).isoformat(),
        },
    )
    assert response.status_code == 201