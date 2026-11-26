from datetime import datetime, time, timedelta

from app.models import (
    OperatingSchedule,
    Resource,
    ResourceCategory,
    Team,
)
from app.services.schedule import local_timezone
from tests.conftest import auth_headers


def _dt(hour: int, minute: int = 0, day_offset: int = 0) -> datetime:
    # 2026-11-23 is a Monday (weekday = 0)
    return datetime(2026, 11, 23 + day_offset, hour, minute, tzinfo=local_timezone())


def _setup_resource(
    db,
    *,
    max_duration_min: int | None = None,
    max_concurrent_teams: int = 1,
) -> Resource:
    category = ResourceCategory(name=f"RulesCat-{id(db)}-{max_duration_min}-{max_concurrent_teams}")
    db.add(category)
    db.flush()

    resource = Resource(
        name="3D Printer Pro",
        category_id=category.id,
        max_duration_min=max_duration_min,
        max_concurrent_teams=max_concurrent_teams,
    )
    db.add(resource)
    db.flush()

    for weekday in range(7):
        db.add(
            OperatingSchedule(
                resource_id=resource.id,
                weekday=weekday,
                start_time=time(8, 0),
                end_time=time(20, 0),
            )
        )
    db.commit()
    db.refresh(resource)
    return resource


def test_create_reservation_exceeds_max_duration(client, db, student):
    resource = _setup_resource(db, max_duration_min=90)

    response = client.post(
        "/reservations",
        headers=auth_headers(student),
        json={
            "resource_id": resource.id,
            "start_at": _dt(10, 0).isoformat(),
            "end_at": _dt(12, 0).isoformat(),
        },
    )
    assert response.status_code == 422
    assert "maximum duration" in response.json()["detail"].lower()


def test_create_reservation_same_team_duplicate_overlap_rejected(client, db, make_user):
    resource = _setup_resource(db, max_concurrent_teams=2)
    team = Team(name="Echipa Alpha")
    db.add(team)
    db.flush()

    member_1 = make_user()
    member_2 = make_user()
    member_1.team_id = team.id
    member_2.team_id = team.id
    db.commit()

    first = client.post(
        "/reservations",
        headers=auth_headers(member_1),
        json={
            "resource_id": resource.id,
            "start_at": _dt(10, 0).isoformat(),
            "end_at": _dt(11, 0).isoformat(),
        },
    )
    assert first.status_code == 201

    # Alt membru din aceeași echipă nu poate rezerva peste același interval, chiar dacă mai e 1 loc
    second = client.post(
        "/reservations",
        headers=auth_headers(member_2),
        json={
            "resource_id": resource.id,
            "start_at": _dt(10, 30).isoformat(),
            "end_at": _dt(11, 30).isoformat(),
        },
    )
    assert second.status_code == 409
    assert "team already" in second.json()["detail"].lower()


def test_create_reservation_rejects_inverted_and_multiday_intervals(client, db, student):
    resource = _setup_resource(db)

    # start_at >= end_at -> 422
    inverted = client.post(
        "/reservations",
        headers=auth_headers(student),
        json={
            "resource_id": resource.id,
            "start_at": _dt(12, 0).isoformat(),
            "end_at": _dt(11, 0).isoformat(),
        },
    )
    assert inverted.status_code == 422

    # Interval pe două zile -> 422
    multiday = client.post(
        "/reservations",
        headers=auth_headers(student),
        json={
            "resource_id": resource.id,
            "start_at": _dt(18, 0, day_offset=0).isoformat(),
            "end_at": (_dt(10, 0, day_offset=1) + timedelta(minutes=0)).isoformat(),
        },
    )
    assert multiday.status_code == 422
    assert "same day" in multiday.json()["detail"].lower()