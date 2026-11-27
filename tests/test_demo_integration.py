from datetime import datetime, time, timedelta, timezone

import pytest

from app.config import settings
from app.models import (
    OperatingSchedule,
    Reservation,
    ReservationStatus,
    Resource,
    ResourceCategory,
)
from tests.conftest import auth_headers


def _resource(db, admin, **fields) -> Resource:
    category = ResourceCategory(name=fields.pop("category", "Săli"))
    db.add(category)
    db.flush()
    resource = Resource(name=fields.pop("name", "Lab C201"), category_id=category.id, admins=[admin])
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource


@pytest.fixture
def demo_enabled(monkeypatch):
    monkeypatch.setattr(settings, "demo_login", True)


def test_demo_login_is_disabled_by_default(client, student):
    response = client.post("/auth/demo", json={"email": student.email})
    assert response.status_code == 404


def test_demo_login_returns_token_for_existing_user(client, student, demo_enabled):
    response = client.post("/auth/demo", json={"email": student.email.upper()})
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["id"] == student.id
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == student.email


def test_demo_login_applies_domain_rule(client, demo_enabled):
    response = client.post("/auth/demo", json={"email": "ion.popescu@gmail.com"})
    assert response.status_code == 401


def test_demo_login_rejects_unknown_account(client, demo_enabled):
    response = client.post("/auth/demo", json={"email": "nobody@student.usv.ro"})
    assert response.status_code == 401


def test_my_reservations_lists_only_own_with_resource(client, db, admin, student, make_user):
    resource = _resource(db, admin)
    other = make_user()
    start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=2)
    mine_old = Reservation(
        user_id=student.id, resource_id=resource.id, start_at=start,
        end_at=start + timedelta(minutes=30), status=ReservationStatus.APPROVED,
    )
    mine_new = Reservation(
        user_id=student.id, resource_id=resource.id, start_at=start + timedelta(days=1),
        end_at=start + timedelta(days=1, minutes=30), status=ReservationStatus.PENDING,
    )
    theirs = Reservation(
        user_id=other.id, resource_id=resource.id, start_at=start + timedelta(hours=2),
        end_at=start + timedelta(hours=2, minutes=30), status=ReservationStatus.PENDING,
    )
    db.add_all([mine_old, mine_new, theirs])
    db.commit()

    response = client.get("/reservations/me", headers=auth_headers(student))
    assert response.status_code == 200
    items = response.json()
    assert [item["id"] for item in items] == [mine_new.id, mine_old.id]
    assert items[0]["resource"]["name"] == "Lab C201"


def test_my_reservations_requires_sign_in(client):
    assert client.get("/reservations/me").status_code == 401


def test_pending_requests_include_awaiting_training(client, db, admin, student):
    resource = _resource(db, admin)
    start = datetime.now(timezone.utc) + timedelta(days=2)
    reservation = Reservation(
        user_id=student.id, resource_id=resource.id, start_at=start,
        end_at=start + timedelta(minutes=30), status=ReservationStatus.AWAITING_TRAINING,
    )
    db.add(reservation)
    db.commit()

    response = client.get("/reservations/pending", headers=auth_headers(admin))
    assert response.status_code == 200
    assert [item["status"] for item in response.json()] == ["AWAITING_TRAINING"]


def test_resource_includes_operating_schedule(client, db, admin, student):
    resource = _resource(db, admin)
    db.add(OperatingSchedule(resource_id=resource.id, weekday=0, start_time=time(8), end_time=time(16)))
    db.commit()

    response = client.get(f"/resources/{resource.id}", headers=auth_headers(student))
    assert response.status_code == 200
    assert response.json()["schedules"] == [
        {"weekday": 0, "start_time": "08:00:00", "end_time": "16:00:00"}
    ]
