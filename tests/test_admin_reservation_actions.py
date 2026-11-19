from datetime import datetime, time, timezone

from app.models import (
    OperatingSchedule,
    Reservation,
    ReservationStatus,
    Resource,
    ResourceCategory,
    Role,
)
from app.services.schedule import local_timezone
from tests.conftest import auth_headers


def _make_resource_and_reservation(
    db,
    student,
    admin,
    *,
    status: ReservationStatus = ReservationStatus.PENDING,
    max_concurrent_teams: int = 1,
) -> tuple[Resource, Reservation]:
    category = ResourceCategory(name=f"DecisionCat-{id(db)}-{status.value}")
    db.add(category)
    db.flush()

    resource = Resource(
        name="CNC Milling Machine",
        category_id=category.id,
        max_concurrent_teams=max_concurrent_teams,
        requires_training=True,
        admins=[admin],
    )
    db.add(resource)
    db.flush()

    # Fixed future Monday 10:00 - 11:00 local time, stored in UTC for SQLite compatibility
    tz = local_timezone()
    base_day = datetime(2027, 1, 11, tzinfo=tz)
    db.add(
        OperatingSchedule(
            resource_id=resource.id,
            weekday=base_day.weekday(),
            start_time=time(8, 0),
            end_time=time(18, 0),
        )
    )

    start_at = base_day.replace(hour=10, minute=0).astimezone(timezone.utc)
    end_at = base_day.replace(hour=11, minute=0).astimezone(timezone.utc)
    reservation = Reservation(
        user_id=student.id,
        resource_id=resource.id,
        start_at=start_at,
        end_at=end_at,
        purpose="Prelucrare piesă aluminiu",
        status=status,
    )
    db.add(reservation)
    db.commit()
    db.refresh(resource)
    db.refresh(reservation)
    return resource, reservation


def test_approve_blocks_slot_and_sets_decided_metadata(client, db, student, admin):
    resource, reservation = _make_resource_and_reservation(
        db, student, admin, status=ReservationStatus.PENDING, max_concurrent_teams=1
    )

    response = client.post(
        f"/reservations/{reservation.id}/approve",
        headers=auth_headers(admin),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "APPROVED"
    assert body["decided_by"] == admin.id
    assert body["decided_at"] is not None

    # Availability endpoint confirms the 10:00-11:00 slots are now blocked (APPROVED)
    avail = client.get(
        f"/resources/{resource.id}/availability",
        headers=auth_headers(student),
        params={"start_date": "2027-01-11", "end_date": "2027-01-11"},
    )
    assert avail.status_code == 200
    blocked = [
        slot
        for slot in avail.json()
        if "10:00:00" in slot["start_at"] or "10:30:00" in slot["start_at"]
    ]
    assert len(blocked) == 2
    assert all(slot["status"] == "APPROVED" and slot["free_places"] == 0 for slot in blocked)


def test_approve_cancelled_reservation_returns_clear_error(client, db, student, admin):
    _, reservation = _make_resource_and_reservation(
        db, student, admin, status=ReservationStatus.CANCELLED
    )

    response = client.post(
        f"/reservations/{reservation.id}/approve",
        headers=auth_headers(admin),
    )
    assert response.status_code == 409
    assert "cancelled" in response.json()["detail"].lower()


def test_reject_without_reason_returns_400(client, db, student, admin):
    _, reservation = _make_resource_and_reservation(
        db, student, admin, status=ReservationStatus.PENDING
    )

    # Empty body
    res_no_body = client.post(
        f"/reservations/{reservation.id}/reject",
        headers=auth_headers(admin),
    )
    assert res_no_body.status_code == 400
    assert "reason" in res_no_body.json()["detail"].lower()

    # Blank whitespace reason
    res_blank = client.post(
        f"/reservations/{reservation.id}/reject",
        headers=auth_headers(admin),
        json={"reason": "   "},
    )
    assert res_blank.status_code == 400


def test_reject_with_reason_succeeds(client, db, student, admin):
    _, reservation = _make_resource_and_reservation(
        db, student, admin, status=ReservationStatus.PENDING
    )

    response = client.post(
        f"/reservations/{reservation.id}/reject",
        headers=auth_headers(admin),
        json={"reason": "Echipamentul este rezervat pentru curs"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "REJECTED"
    assert data["rejection_reason"] == "Echipamentul este rezervat pentru curs"
    assert data["decided_by"] == admin.id


def test_reject_cancelled_reservation_returns_clear_error(client, db, student, admin):
    _, reservation = _make_resource_and_reservation(
        db, student, admin, status=ReservationStatus.CANCELLED
    )

    response = client.post(
        f"/reservations/{reservation.id}/reject",
        headers=auth_headers(admin),
        json={"reason": "Motiv oarecare"},
    )
    assert response.status_code == 409
    assert "cancelled" in response.json()["detail"].lower()


def test_awaiting_training_and_subsequent_approval(client, db, student, admin):
    _, reservation = _make_resource_and_reservation(
        db, student, admin, status=ReservationStatus.PENDING
    )

    res_train = client.post(
        f"/reservations/{reservation.id}/awaiting-training",
        headers=auth_headers(admin),
    )
    assert res_train.status_code == 200
    assert res_train.json()["status"] == "AWAITING_TRAINING"

    # After training is completed, admin can approve it
    res_approve = client.post(
        f"/reservations/{reservation.id}/approve",
        headers=auth_headers(admin),
    )
    assert res_approve.status_code == 200
    assert res_approve.json()["status"] == "APPROVED"


def test_non_resource_admin_and_student_forbidden(client, db, student, admin, make_user):
    _, reservation = _make_resource_and_reservation(
        db, student, admin, status=ReservationStatus.PENDING
    )
    other_admin = make_user(Role.ADMIN, email="alt.admin@student.usv.ro")

    assert (
        client.post(
            f"/reservations/{reservation.id}/approve",
            headers=auth_headers(student),
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/reservations/{reservation.id}/approve",
            headers=auth_headers(other_admin),
        ).status_code
        == 403
    )