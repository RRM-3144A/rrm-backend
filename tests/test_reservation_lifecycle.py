from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    Reservation,
    ReservationStatus,
    Resource,
    ResourceCategory,
)
from tests.conftest import auth_headers


def _make_reservation(
    db,
    user,
    admin,
    *,
    status: ReservationStatus = ReservationStatus.PENDING,
    offset_hours: int = 2,
) -> Reservation:
    category = ResourceCategory(name=f"Cat-{id(db)}-{status.value}-{offset_hours}")
    db.add(category)
    db.flush()

    resource = Resource(
        name="3D Printer Lab",
        category_id=category.id,
        admins=[admin],
    )
    db.add(resource)
    db.flush()

    start_at = datetime.now(timezone.utc) + timedelta(hours=offset_hours)
    end_at = start_at + timedelta(hours=1)
    reservation = Reservation(
        user_id=user.id,
        resource_id=resource.id,
        start_at=start_at,
        end_at=end_at,
        status=status,
    )
    db.add(reservation)
    db.commit()
    db.refresh(reservation)
    return reservation


@pytest.mark.parametrize(
    ("initial", "target", "reason"),
    [
        (ReservationStatus.PENDING, ReservationStatus.APPROVED, None),
        (ReservationStatus.PENDING, ReservationStatus.REJECTED, "Slot reserved for lab class"),
        (ReservationStatus.PENDING, ReservationStatus.AWAITING_TRAINING, None),
        (ReservationStatus.PENDING, ReservationStatus.CANCELLED, None),
        (ReservationStatus.AWAITING_TRAINING, ReservationStatus.APPROVED, None),
        (ReservationStatus.AWAITING_TRAINING, ReservationStatus.REJECTED, "Failed safety check"),
        (ReservationStatus.AWAITING_TRAINING, ReservationStatus.CANCELLED, None),
        (ReservationStatus.APPROVED, ReservationStatus.COMPLETED, None),
        (ReservationStatus.APPROVED, ReservationStatus.CANCELLED, None),
    ],
)
def test_legal_transitions_succeed(client, db, student, admin, initial, target, reason):
    reservation = _make_reservation(db, student, admin, status=initial)

    payload = {"status": target.value}
    if reason is not None:
        payload["rejection_reason"] = reason

    response = client.patch(
        f"/reservations/{reservation.id}/status",
        headers=auth_headers(admin),
        json=payload,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == target.value
    if reason is not None:
        assert data["rejection_reason"] == reason


@pytest.mark.parametrize(
    ("initial", "target"),
    [
        (ReservationStatus.PENDING, ReservationStatus.COMPLETED),
        (ReservationStatus.PENDING, ReservationStatus.PENDING),
        (ReservationStatus.AWAITING_TRAINING, ReservationStatus.PENDING),
        (ReservationStatus.AWAITING_TRAINING, ReservationStatus.COMPLETED),
        (ReservationStatus.APPROVED, ReservationStatus.PENDING),
        (ReservationStatus.APPROVED, ReservationStatus.AWAITING_TRAINING),
        (ReservationStatus.APPROVED, ReservationStatus.REJECTED),
        (ReservationStatus.REJECTED, ReservationStatus.APPROVED),
        (ReservationStatus.REJECTED, ReservationStatus.CANCELLED),
        (ReservationStatus.CANCELLED, ReservationStatus.APPROVED),
        (ReservationStatus.CANCELLED, ReservationStatus.PENDING),
        (ReservationStatus.COMPLETED, ReservationStatus.CANCELLED),
        (ReservationStatus.COMPLETED, ReservationStatus.APPROVED),
    ],
)
def test_illegal_transitions_rejected(client, db, student, admin, initial, target):
    reservation = _make_reservation(db, student, admin, status=initial)

    response = client.patch(
        f"/reservations/{reservation.id}/status",
        headers=auth_headers(admin),
        json={"status": target.value, "rejection_reason": "test"},
    )
    assert response.status_code == 422


def test_student_can_cancel_before_start(client, db, student, admin):
    reservation = _make_reservation(
        db, student, admin, status=ReservationStatus.APPROVED, offset_hours=3
    )

    response = client.post(
        f"/reservations/{reservation.id}/cancel",
        headers=auth_headers(student),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_student_cannot_cancel_after_slot_started(client, db, student, admin):
    reservation = _make_reservation(
        db, student, admin, status=ReservationStatus.APPROVED, offset_hours=-1
    )

    response = client.delete(
        f"/reservations/{reservation.id}",
        headers=auth_headers(student),
    )
    assert response.status_code == 422
    assert "before" in response.json()["detail"].lower()


def test_admin_can_cancel_anytime_even_after_start(client, db, student, admin):
    reservation = _make_reservation(
        db, student, admin, status=ReservationStatus.APPROVED, offset_hours=-2
    )

    response = client.post(
        f"/reservations/{reservation.id}/cancel",
        headers=auth_headers(admin),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_other_student_cannot_cancel_reservation(client, db, student, admin, make_user):
    other_student = make_user()
    reservation = _make_reservation(
        db, student, admin, status=ReservationStatus.PENDING, offset_hours=2
    )

    response = client.post(
        f"/reservations/{reservation.id}/cancel",
        headers=auth_headers(other_student),
    )
    assert response.status_code == 403


def test_student_cannot_approve_own_reservation(client, db, student, admin):
    reservation = _make_reservation(
        db, student, admin, status=ReservationStatus.PENDING, offset_hours=2
    )

    response = client.patch(
        f"/reservations/{reservation.id}/status",
        headers=auth_headers(student),
        json={"status": "APPROVED"},
    )
    assert response.status_code == 403