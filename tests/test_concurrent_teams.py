from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects import postgresql

from app.models import (
    Reservation,
    ReservationStatus,
    Resource,
    ResourceCategory,
    Team,
)
from app.services.sharing import build_resource_lock_query
from tests.conftest import auth_headers


def _make_shared_resource(db, admin, *, max_concurrent_teams: int = 2) -> Resource:
    category = ResourceCategory(name=f"SharedCat-{id(db)}-{max_concurrent_teams}")
    db.add(category)
    db.flush()

    resource = Resource(
        name="Oscilloscope Bench",
        category_id=category.id,
        max_concurrent_teams=max_concurrent_teams,
        admins=[admin],
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource


def _make_team_student(db, make_user, team_name: str):
    team = Team(name=team_name)
    db.add(team)
    db.flush()
    user = make_user()
    user.team_id = team.id
    db.commit()
    db.refresh(user)
    return user


def test_postgresql_lock_query_uses_for_update():
    stmt = build_resource_lock_query(42)
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in compiled


def test_two_teams_can_book_same_slot_third_is_rejected(client, db, admin, make_user):
    resource = _make_shared_resource(db, admin, max_concurrent_teams=2)
    student_1 = _make_team_student(db, make_user, "Team Alpha")
    student_2 = _make_team_student(db, make_user, "Team Beta")
    student_3 = _make_team_student(db, make_user, "Team Gamma")

    start_at = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    end_at = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()

    r1 = client.post(
        "/reservations",
        headers=auth_headers(student_1),
        json={"resource_id": resource.id, "start_at": start_at, "end_at": end_at},
    )
    assert r1.status_code == 201

    r2 = client.post(
        "/reservations",
        headers=auth_headers(student_2),
        json={"resource_id": resource.id, "start_at": start_at, "end_at": end_at},
    )
    assert r2.status_code == 201

    r3 = client.post(
        "/reservations",
        headers=auth_headers(student_3),
        json={"resource_id": resource.id, "start_at": start_at, "end_at": end_at},
    )
    assert r3.status_code == 409
    assert "2 concurrent team" in r3.json()["detail"]


def test_partial_overlap_reaching_three_teams_is_rejected(client, db, admin, make_user):
    resource = _make_shared_resource(db, admin, max_concurrent_teams=2)
    s1 = _make_team_student(db, make_user, "Team 1")
    s2 = _make_team_student(db, make_user, "Team 2")
    s3 = _make_team_student(db, make_user, "Team 3")

    base = datetime.now(timezone.utc) + timedelta(hours=5)

    # Team 1: 00:00 -> 01:00
    assert (
        client.post(
            "/reservations",
            headers=auth_headers(s1),
            json={
                "resource_id": resource.id,
                "start_at": base.isoformat(),
                "end_at": (base + timedelta(hours=1)).isoformat(),
            },
        ).status_code
        == 201
    )

    # Team 2: 00:30 -> 01:30
    assert (
        client.post(
            "/reservations",
            headers=auth_headers(s2),
            json={
                "resource_id": resource.id,
                "start_at": (base + timedelta(minutes=30)).isoformat(),
                "end_at": (base + timedelta(hours=1, minutes=30)).isoformat(),
            },
        ).status_code
        == 201
    )

    # Team 3: 00:00 -> 02:00 (overlaps both Team 1 and Team 2 between 00:30 and 01:00 -> 3 teams)
    r3 = client.post(
        "/reservations",
        headers=auth_headers(s3),
        json={
            "resource_id": resource.id,
            "start_at": base.isoformat(),
            "end_at": (base + timedelta(hours=2)).isoformat(),
        },
    )
    assert r3.status_code == 409


def test_sequential_non_overlapping_bookings_succeed(client, db, admin, make_user):
    resource = _make_shared_resource(db, admin, max_concurrent_teams=2)
    s1 = _make_team_student(db, make_user, "Seq Team 1")
    s2 = _make_team_student(db, make_user, "Seq Team 2")
    s3 = _make_team_student(db, make_user, "Seq Team 3")

    base = datetime.now(timezone.utc) + timedelta(hours=6)

    # Team 1: 00:00 -> 00:30
    assert (
        client.post(
            "/reservations",
            headers=auth_headers(s1),
            json={
                "resource_id": resource.id,
                "start_at": base.isoformat(),
                "end_at": (base + timedelta(minutes=30)).isoformat(),
            },
        ).status_code
        == 201
    )

    # Team 2: 00:30 -> 01:00 (adjacent, does not overlap Team 1)
    assert (
        client.post(
            "/reservations",
            headers=auth_headers(s2),
            json={
                "resource_id": resource.id,
                "start_at": (base + timedelta(minutes=30)).isoformat(),
                "end_at": (base + timedelta(hours=1)).isoformat(),
            },
        ).status_code
        == 201
    )

    # Team 3: 00:00 -> 01:00 (at most 2 concurrent teams at any moment -> allowed)
    assert (
        client.post(
            "/reservations",
            headers=auth_headers(s3),
            json={
                "resource_id": resource.id,
                "start_at": base.isoformat(),
                "end_at": (base + timedelta(hours=1)).isoformat(),
            },
        ).status_code
        == 201
    )


def test_single_team_resource_rejects_second_overlapping_team(client, db, admin, make_user):
    resource = _make_shared_resource(db, admin, max_concurrent_teams=1)
    s1 = _make_team_student(db, make_user, "Solo Team 1")
    s2 = _make_team_student(db, make_user, "Solo Team 2")

    start_at = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    end_at = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()

    assert (
        client.post(
            "/reservations",
            headers=auth_headers(s1),
            json={"resource_id": resource.id, "start_at": start_at, "end_at": end_at},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/reservations",
            headers=auth_headers(s2),
            json={"resource_id": resource.id, "start_at": start_at, "end_at": end_at},
        ).status_code
        == 409
    )


def test_approving_third_overlapping_reservation_is_refused(client, db, admin, make_user):
    resource = _make_shared_resource(db, admin, max_concurrent_teams=2)
    s1 = _make_team_student(db, make_user, "App Team 1")
    s2 = _make_team_student(db, make_user, "App Team 2")
    s3 = _make_team_student(db, make_user, "App Team 3")

    start_at = datetime.now(timezone.utc) + timedelta(hours=7)
    end_at = start_at + timedelta(hours=1)

    res1 = Reservation(
        user_id=s1.id,
        resource_id=resource.id,
        team_id=s1.team_id,
        start_at=start_at,
        end_at=end_at,
        status=ReservationStatus.PENDING,
    )
    res2 = Reservation(
        user_id=s2.id,
        resource_id=resource.id,
        team_id=s2.team_id,
        start_at=start_at,
        end_at=end_at,
        status=ReservationStatus.PENDING,
    )
    res3 = Reservation(
        user_id=s3.id,
        resource_id=resource.id,
        team_id=s3.team_id,
        start_at=start_at,
        end_at=end_at,
        status=ReservationStatus.PENDING,
    )
    db.add_all([res1, res2, res3])
    db.commit()

    # Approving 1st and 2nd succeeds
    assert (
        client.patch(
            f"/reservations/{res1.id}/status",
            headers=auth_headers(admin),
            json={"status": "APPROVED"},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/reservations/{res2.id}/status",
            headers=auth_headers(admin),
            json={"status": "APPROVED"},
        ).status_code
        == 200
    )

    # Approving 3rd overlapping reservation is refused with 409
    r3 = client.patch(
        f"/reservations/{res3.id}/status",
        headers=auth_headers(admin),
        json={"status": "APPROVED"},
    )
    assert r3.status_code == 409
    db.refresh(res3)
    assert res3.status == ReservationStatus.PENDING