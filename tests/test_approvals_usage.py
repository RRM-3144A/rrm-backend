from datetime import date, datetime, time, timezone

from app.models import (
    Reservation,
    ReservationStatus,
    Resource,
    ResourceCategory,
    Role,
    Team,
    User,
)
from app.services.schedule import local_timezone
from tests.conftest import auth_headers


def _utc(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=local_timezone()).astimezone(
        timezone.utc
    )


def _setup_data(db, admin):
    other_admin = User(
        google_sub="sub-other-admin",
        email="other.admin@student.usv.ro",
        first_name="Radu",
        last_name="Admin",
        role=Role.ADMIN,
    )
    team_robotics = Team(name="Echipa Robotică")
    team_iot = Team(name="Echipa IoT")
    category = ResourceCategory(name=f"UsageCat-{id(db)}")
    db.add_all([other_admin, team_robotics, team_iot, category])
    db.flush()

    managed_res = Resource(
        name="Prusa MK4",
        category_id=category.id,
        admins=[admin],
    )
    other_res = Resource(
        name="Microscop Zeiss",
        category_id=category.id,
        admins=[other_admin],
    )
    db.add_all([managed_res, other_res])
    db.flush()

    u_rob = User(
        google_sub="sub-rob-1",
        email="rob1@student.usv.ro",
        first_name="Ioana",
        last_name="Popescu",
        role=Role.STUDENT,
        team_id=team_robotics.id,
    )
    u_iot = User(
        google_sub="sub-iot-1",
        email="iot1@student.usv.ro",
        first_name="Bianca",
        last_name="Tanase",
        role=Role.STUDENT,
        team_id=team_iot.id,
    )
    db.add_all([u_rob, u_iot])
    db.commit()
    return other_admin, team_robotics, team_iot, managed_res, other_res, u_rob, u_iot


def test_approvals_usage_counts_only_approved_and_completed_for_managed_resources(
    client, db, admin
):
    _, team_robotics, team_iot, managed_res, other_res, u_rob, u_iot = _setup_data(db, admin)
    day_1 = date(2026, 11, 23)
    day_2 = date(2026, 11, 24)

    db.add_all(
        [
            # Numărate pentru Echipa Robotică (2h APPROVED + 1.5h COMPLETED = 3.5h, 2 rezervări)
            Reservation(
                user_id=u_rob.id,
                resource_id=managed_res.id,
                team_id=team_robotics.id,
                start_at=_utc(day_1, 9, 0),
                end_at=_utc(day_1, 11, 0),
                status=ReservationStatus.APPROVED,
            ),
            Reservation(
                user_id=u_rob.id,
                resource_id=managed_res.id,
                team_id=team_robotics.id,
                start_at=_utc(day_2, 10, 0),
                end_at=_utc(day_2, 11, 30),
                status=ReservationStatus.COMPLETED,
            ),
            # Numărată pentru Echipa IoT (1h APPROVED)
            Reservation(
                user_id=u_iot.id,
                resource_id=managed_res.id,
                team_id=team_iot.id,
                start_at=_utc(day_1, 13, 0),
                end_at=_utc(day_1, 14, 0),
                status=ReservationStatus.APPROVED,
            ),
            # Ignorate: PENDING, REJECTED, CANCELLED, AWAITING_TRAINING
            Reservation(
                user_id=u_iot.id,
                resource_id=managed_res.id,
                team_id=team_iot.id,
                start_at=_utc(day_1, 14, 0),
                end_at=_utc(day_1, 16, 0),
                status=ReservationStatus.PENDING,
            ),
            Reservation(
                user_id=u_iot.id,
                resource_id=managed_res.id,
                team_id=team_iot.id,
                start_at=_utc(day_2, 8, 0),
                end_at=_utc(day_2, 10, 0),
                status=ReservationStatus.REJECTED,
            ),
            Reservation(
                user_id=u_rob.id,
                resource_id=managed_res.id,
                team_id=team_robotics.id,
                start_at=_utc(day_2, 14, 0),
                end_at=_utc(day_2, 16, 0),
                status=ReservationStatus.CANCELLED,
            ),
            Reservation(
                user_id=u_rob.id,
                resource_id=managed_res.id,
                team_id=team_robotics.id,
                start_at=_utc(day_2, 16, 0),
                end_at=_utc(day_2, 17, 0),
                status=ReservationStatus.AWAITING_TRAINING,
            ),
            # Ignorată: resursă administrată de alt admin
            Reservation(
                user_id=u_iot.id,
                resource_id=other_res.id,
                team_id=team_iot.id,
                start_at=_utc(day_1, 9, 0),
                end_at=_utc(day_1, 13, 0),
                status=ReservationStatus.APPROVED,
            ),
        ]
    )
    db.commit()

    response = client.get(
        "/approvals/usage",
        params={"start_date": "2026-11-23", "end_date": "2026-11-25"},
        headers=auth_headers(admin),
    )
    assert response.status_code == 200
    assert response.json() == [
        {
            "team_id": team_robotics.id,
            "team_name": "Echipa Robotică",
            "reservations_count": 2,
            "reserved_hours": 3.5,
        },
        {
            "team_id": team_iot.id,
            "team_name": "Echipa IoT",
            "reservations_count": 1,
            "reserved_hours": 1.0,
        },
    ]


def test_approvals_usage_date_filter_and_permissions(client, db, admin, student):
    _, team_robotics, _, managed_res, other_res, u_rob, _ = _setup_data(db, admin)
    day_1 = date(2026, 11, 23)
    day_2 = date(2026, 11, 25)

    db.add_all(
        [
            Reservation(
                user_id=u_rob.id,
                resource_id=managed_res.id,
                team_id=team_robotics.id,
                start_at=_utc(day_1, 9, 0),
                end_at=_utc(day_1, 10, 0),
                status=ReservationStatus.APPROVED,
            ),
            Reservation(
                user_id=u_rob.id,
                resource_id=managed_res.id,
                team_id=team_robotics.id,
                start_at=_utc(day_2, 9, 0),
                end_at=_utc(day_2, 11, 0),
                status=ReservationStatus.COMPLETED,
            ),
        ]
    )
    db.commit()

    # Filtrare doar pe day_2
    filtered = client.get(
        "/approvals/usage",
        params={"start_date": "2026-11-25", "end_date": "2026-11-25"},
        headers=auth_headers(admin),
    )
    assert filtered.status_code == 200
    assert filtered.json() == [
        {
            "team_id": team_robotics.id,
            "team_name": "Echipa Robotică",
            "reservations_count": 1,
            "reserved_hours": 2.0,
        }
    ]

    # Student -> 403
    assert (
        client.get("/approvals/usage", headers=auth_headers(student)).status_code == 403
    )

    # Resursă administrată de alt admin -> 403
    assert (
        client.get(
            "/approvals/usage",
            params={"resource_id": other_res.id},
            headers=auth_headers(admin),
        ).status_code
        == 403
    )

    # Interval invalid -> 422
    assert (
        client.get(
            "/approvals/usage",
            params={"start_date": "2026-11-25", "end_date": "2026-11-23"},
            headers=auth_headers(admin),
        ).status_code
        == 422
    )