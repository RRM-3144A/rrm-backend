from datetime import date, timezone

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models import (
    MaintenanceWindow,
    Reservation,
    ReservationStatus,
    Resource,
    ResourceCategory,
    ResourceStatus,
    Role,
    Team,
    User,
    WaitlistEntry,
)
from app.seed import RESOURCES, USERS, next_monday, seed
from app.services.schedule import is_within_schedule
from tests.conftest import auth_headers

TODAY = date(2026, 11, 19)  # a Thursday; the seeded week starts on Monday 2026-11-23
ACTIVE_STATUSES = {
    ReservationStatus.PENDING,
    ReservationStatus.AWAITING_TRAINING,
    ReservationStatus.APPROVED,
}


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


@pytest.fixture
def seeded(db, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "")
    seed(db, today=TODAY)
    return db


def test_next_monday_is_in_the_following_week():
    assert next_monday(date(2026, 11, 19)) == date(2026, 11, 23)
    assert next_monday(date(2026, 11, 23)) == date(2026, 11, 30)
    assert next_monday(date(2026, 11, 22)) == date(2026, 11, 23)


def test_seed_loads_every_kind_of_data(seeded):
    db = seeded
    assert _count(db, User) == len(USERS)
    assert _count(db, Team) == 3
    assert _count(db, ResourceCategory) == 4
    assert _count(db, Resource) == len(RESOURCES)
    assert _count(db, MaintenanceWindow) == 2
    assert _count(db, WaitlistEntry) == 1
    statuses = set(db.scalars(select(Reservation.status)))
    assert statuses == set(ReservationStatus)


def test_users_have_university_emails_and_students_have_teams(seeded):
    for user in seeded.scalars(select(User)):
        assert user.email.endswith("@student.usv.ro")
        if user.role == Role.STUDENT:
            assert user.team is not None


def test_every_resource_has_admins_and_a_schedule(seeded):
    for resource in seeded.scalars(select(Resource)):
        assert resource.admins and all(a.role == Role.ADMIN for a in resource.admins)
        assert resource.schedules
    statuses = set(seeded.scalars(select(Resource.status)))
    assert statuses == set(ResourceStatus)


def test_reservations_respect_schedule_and_capacity(seeded):
    reservations = list(seeded.scalars(select(Reservation)))
    for reservation in reservations:
        start, end = _utc(reservation.start_at), _utc(reservation.end_at)
        assert is_within_schedule(reservation.resource, start, end), reservation.purpose

    active = [r for r in reservations if r.status in ACTIVE_STATUSES]
    for reservation in active:
        overlapping = [
            other for other in active
            if other.resource_id == reservation.resource_id
            and other.start_at < reservation.end_at
            and reservation.start_at < other.end_at
        ]
        assert len(overlapping) <= reservation.resource.max_concurrent_teams


def test_rejected_reservation_has_a_reason(seeded):
    rejected = seeded.scalar(
        select(Reservation).where(Reservation.status == ReservationStatus.REJECTED)
    )
    assert rejected.rejection_reason


def test_running_seed_twice_does_not_duplicate(seeded):
    before = {model: _count(seeded, model) for model in (User, Resource, Reservation)}

    seed(seeded, today=TODAY)

    assert {model: _count(seeded, model) for model in before} == before


def test_admin_emails_become_admins_of_every_resource(db, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "damaris.polocoser@student.usv.ro")

    seed(db, today=TODAY)

    me = db.scalar(select(User).where(User.email == "damaris.polocoser@student.usv.ro"))
    assert me.role == Role.ADMIN
    assert all(me in resource.admins for resource in db.scalars(select(Resource)))


def test_seeded_week_shows_up_in_availability(client, seeded):
    student = seeded.scalar(select(User).where(User.email == "maria.lungu@student.usv.ro"))
    zeiss = seeded.scalar(select(Resource).where(Resource.name == "Microscop Zeiss Axio"))

    slots = client.get(
        f"/resources/{zeiss.id}/availability",
        params={"start_date": "2026-11-23", "end_date": "2026-11-23"},
        headers=auth_headers(student),
    ).json()

    # 09:00–11:00 approved for Maria, the rest of the day free.
    assert [s["status"] for s in slots[:5]] == ["APPROVED"] * 4 + ["FREE"]
