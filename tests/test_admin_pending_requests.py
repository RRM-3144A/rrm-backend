from datetime import datetime, timedelta, timezone

from app.models import (
    Reservation,
    ReservationStatus,
    Resource,
    ResourceCategory,
    ResourceTraining,
    Role,
    Team,
)
from tests.conftest import auth_headers


def _setup_resources(db, admin_1, admin_2):
    category = ResourceCategory(name="Lab Equipment")
    db.add(category)
    db.flush()

    res_a = Resource(
        name="Prusa MK4",
        category_id=category.id,
        location="Corp C, C203",
        requires_training=True,
        admins=[admin_1],
    )
    res_b = Resource(
        name="Zeiss Microscope",
        category_id=category.id,
        location="Corp A, A105",
        requires_training=False,
        admins=[admin_2],
    )
    db.add_all([res_a, res_b])
    db.commit()
    db.refresh(res_a)
    db.refresh(res_b)
    return res_a, res_b


def test_student_cannot_list_admin_pending_requests(client, student):
    response = client.get("/reservations/pending", headers=auth_headers(student))
    assert response.status_code == 403


def test_admin_sees_only_pending_requests_for_own_resources_with_details(
    client, db, admin, student, make_user
):
    other_admin = make_user(Role.ADMIN, first_name="Radu", email="radu.admin@student.usv.ro")
    res_a, res_b = _setup_resources(db, admin, other_admin)

    team = Team(name="Echipa Robotică")
    db.add(team)
    db.flush()
    student.team_id = team.id

    base = datetime.now(timezone.utc) + timedelta(hours=3)

    # Pending on res_a (should appear)
    pending_mine = Reservation(
        user_id=student.id,
        resource_id=res_a.id,
        team_id=team.id,
        start_at=base,
        end_at=base + timedelta(hours=1),
        purpose="Imprimare carcasă senzor",
        status=ReservationStatus.PENDING,
    )
    # Approved on res_a (should NOT appear)
    approved_mine = Reservation(
        user_id=student.id,
        resource_id=res_a.id,
        team_id=team.id,
        start_at=base + timedelta(hours=2),
        end_at=base + timedelta(hours=3),
        purpose="Deja aprobată",
        status=ReservationStatus.APPROVED,
    )
    # Pending on res_b administered by other_admin (should NOT appear for `admin`)
    pending_other_resource = Reservation(
        user_id=student.id,
        resource_id=res_b.id,
        team_id=team.id,
        start_at=base,
        end_at=base + timedelta(hours=1),
        purpose="Analiză probe",
        status=ReservationStatus.PENDING,
    )
    db.add_all([pending_mine, approved_mine, pending_other_resource])
    db.commit()

    response = client.get("/reservations/pending", headers=auth_headers(admin))
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1

    item = items[0]
    assert item["id"] == pending_mine.id
    assert item["status"] == "PENDING"
    assert item["purpose"] == "Imprimare carcasă senzor"
    assert item["user"]["email"] == student.email
    assert item["resource"]["name"] == "Prusa MK4"
    assert item["resource"]["location"] == "Corp C, C203"
    assert item["team"]["name"] == "Echipa Robotică"
    assert item["is_first_reservation"] is True
    assert item["has_completed_training"] is False


def test_is_first_reservation_reflects_requester_history_per_resource(
    client, db, admin, make_user
):
    other_admin = make_user(Role.ADMIN, first_name="Elena", email="elena.admin@student.usv.ro")
    res_a, res_b = _setup_resources(db, admin, other_admin)

    new_student = make_user(first_name="Ioana", email="ioana.new@student.usv.ro")
    returning_student = make_user(first_name="Andrei", email="andrei.ret@student.usv.ro")

    base = datetime.now(timezone.utc) + timedelta(hours=4)

    # returning_student had a COMPLETED reservation on res_a in the past
    past_on_a = Reservation(
        user_id=returning_student.id,
        resource_id=res_a.id,
        start_at=base - timedelta(days=2),
        end_at=base - timedelta(days=2) + timedelta(hours=1),
        status=ReservationStatus.COMPLETED,
    )
    # new_student had a COMPLETED reservation on res_b, NOT on res_a
    past_on_b = Reservation(
        user_id=new_student.id,
        resource_id=res_b.id,
        start_at=base - timedelta(days=1),
        end_at=base - timedelta(days=1) + timedelta(hours=1),
        status=ReservationStatus.COMPLETED,
    )
    db.add_all([past_on_a, past_on_b])
    db.flush()

    db.add(ResourceTraining(user_id=returning_student.id, resource_id=res_a.id))

    req_new_on_a = Reservation(
        user_id=new_student.id,
        resource_id=res_a.id,
        start_at=base,
        end_at=base + timedelta(hours=1),
        purpose="Prima mea rezervare pe Prusa",
        status=ReservationStatus.PENDING,
    )
    req_ret_on_a = Reservation(
        user_id=returning_student.id,
        resource_id=res_a.id,
        start_at=base + timedelta(hours=1),
        end_at=base + timedelta(hours=2),
        purpose="A doua rezervare pe Prusa",
        status=ReservationStatus.PENDING,
    )
    db.add_all([req_new_on_a, req_ret_on_a])
    db.commit()

    response = client.get("/reservations/pending", headers=auth_headers(admin))
    assert response.status_code == 200
    by_user = {item["user"]["email"]: item for item in response.json()}

    assert by_user["ioana.new@student.usv.ro"]["is_first_reservation"] is True
    assert by_user["ioana.new@student.usv.ro"]["has_completed_training"] is False

    assert by_user["andrei.ret@student.usv.ro"]["is_first_reservation"] is False
    assert by_user["andrei.ret@student.usv.ro"]["has_completed_training"] is True