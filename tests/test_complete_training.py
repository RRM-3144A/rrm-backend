from datetime import datetime, time, timezone

from app.models import (
    Notification,
    OperatingSchedule,
    Reservation,
    ReservationStatus,
    Resource,
    ResourceCategory,
)
from app.routers import reservations as reservations_router
from app.services.schedule import local_timezone
from tests.conftest import auth_headers


def _setup_training_resource(db, admin) -> Resource:
    category = ResourceCategory(name=f"TrainCat-{id(db)}")
    db.add(category)
    db.flush()

    resource = Resource(
        name="3D Printer Resin",
        category_id=category.id,
        requires_training=True,
        max_concurrent_teams=1,
        admins=[admin],
    )
    db.add(resource)
    db.flush()

    for weekday in range(7):
        db.add(
            OperatingSchedule(
                resource_id=resource.id,
                weekday=weekday,
                start_time=time(8, 0),
                end_time=time(18, 0),
            )
        )
    db.commit()
    db.refresh(resource)
    return resource


def _utc_slot(hour: int, minute: int = 0) -> datetime:
    tz = local_timezone()
    return datetime(2027, 3, 10, hour, minute, tzinfo=tz).astimezone(timezone.utc)


def test_complete_training_moves_to_pending_notifies_user_and_allows_approval(
    client, db, student, admin, monkeypatch
):
    scheduled = []
    monkeypatch.setattr(
        reservations_router,
        "send_in_background",
        lambda _bg, items: scheduled.extend(items),
    )

    resource = _setup_training_resource(db, admin)
    reservation = Reservation(
        user_id=student.id,
        resource_id=resource.id,
        start_at=_utc_slot(10, 0),
        end_at=_utc_slot(11, 0),
        status=ReservationStatus.AWAITING_TRAINING,
    )
    db.add(reservation)
    db.commit()

    res = client.post(
        f"/reservations/{reservation.id}/complete-training",
        headers=auth_headers(admin),
    )
    assert res.status_code == 200
    assert res.json()["status"] == "PENDING"

    notif = (
        db.query(Notification)
        .filter(
            Notification.reservation_id == reservation.id,
            Notification.user_id == student.id,
        )
        .first()
    )
    assert notif is not None
    assert "Instruire finalizată" in notif.subject
    assert len(scheduled) == 1
    assert scheduled[0].id == notif.id

    approve_res = client.post(
        f"/reservations/{reservation.id}/approve",
        headers=auth_headers(admin),
    )
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == "APPROVED"


def test_complete_training_rejects_non_awaiting_training_status(client, db, student, admin):
    resource = _setup_training_resource(db, admin)
    reservation = Reservation(
        user_id=student.id,
        resource_id=resource.id,
        start_at=_utc_slot(12, 0),
        end_at=_utc_slot(13, 0),
        status=ReservationStatus.PENDING,
    )
    db.add(reservation)
    db.commit()

    res = client.post(
        f"/reservations/{reservation.id}/complete-training",
        headers=auth_headers(admin),
    )
    assert res.status_code == 409