from datetime import datetime, time, timezone

from app.models import (
    Notification,
    OperatingSchedule,
    Reservation,
    ReservationStatus,
    Resource,
    ResourceCategory,
    Role,
    User,
    WaitlistEntry,
)
from app.routers import reservations as reservations_router
from app.services.schedule import local_timezone
from tests.conftest import auth_headers


def _setup_resource(db, admin, max_concurrent_teams: int = 1) -> Resource:
    category = ResourceCategory(name=f"WaitCat-{id(db)}-{max_concurrent_teams}")
    db.add(category)
    db.flush()

    resource = Resource(
        name="Laser Cutter",
        category_id=category.id,
        max_concurrent_teams=max_concurrent_teams,
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


def _make_second_student(db) -> User:
    user = User(
        google_sub="sub-student-two",
        email="student2@student.usv.ro",
        first_name="Ioana",
        last_name="Ionescu",
        role=Role.STUDENT,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _utc_slot(hour: int, minute: int = 0) -> datetime:
    tz = local_timezone()
    return datetime(2027, 4, 15, hour, minute, tzinfo=tz).astimezone(timezone.utc)


def test_join_waitlist_when_full_and_notify_on_cancellation(
    client, db, student, admin, monkeypatch
):
    scheduled = []
    monkeypatch.setattr(
        reservations_router,
        "send_in_background",
        lambda _bg, items: scheduled.extend(items),
    )

    resource = _setup_resource(db, admin, max_concurrent_teams=1)
    second_student = _make_second_student(db)

    start_at = _utc_slot(10, 0)
    end_at = _utc_slot(11, 0)

    reservation = Reservation(
        user_id=student.id,
        resource_id=resource.id,
        start_at=start_at,
        end_at=end_at,
        status=ReservationStatus.APPROVED,
    )
    db.add(reservation)
    db.commit()

    # Al doilea student se înscrie pe lista de așteptare pentru slotul ocupat
    join_res = client.post(
        "/waitlist",
        json={
            "resource_id": resource.id,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
        },
        headers=auth_headers(second_student),
    )
    assert join_res.status_code == 201
    entry_id = join_res.json()["id"]
    assert join_res.json()["notified_at"] is None

    # Listare listă de așteptare proprie
    list_res = client.get("/waitlist", headers=auth_headers(second_student))
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1
    assert list_res.json()[0]["id"] == entry_id

    # Primul student își anulează rezervarea -> al doilea este notificat automat
    cancel_res = client.post(
        f"/reservations/{reservation.id}/cancel",
        headers=auth_headers(student),
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    entry = db.get(WaitlistEntry, entry_id)
    db.refresh(entry)
    assert entry.notified_at is not None

    notif = (
        db.query(Notification)
        .filter(Notification.user_id == second_student.id)
        .first()
    )
    assert notif is not None
    assert "Slot disponibil" in notif.subject
    assert len(scheduled) == 1
    assert scheduled[0].id == notif.id


def test_join_waitlist_rejects_available_slot_and_duplicates(client, db, student, admin):
    resource = _setup_resource(db, admin, max_concurrent_teams=1)
    second_student = _make_second_student(db)

    start_at = _utc_slot(12, 0)
    end_at = _utc_slot(13, 0)

    # Slotul este liber -> 409 (se poate rezerva direct)
    free_res = client.post(
        "/waitlist",
        json={
            "resource_id": resource.id,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
        },
        headers=auth_headers(second_student),
    )
    assert free_res.status_code == 409

    # Ocupăm slotul
    db.add(
        Reservation(
            user_id=student.id,
            resource_id=resource.id,
            start_at=start_at,
            end_at=end_at,
            status=ReservationStatus.PENDING,
        )
    )
    db.commit()

    ok_res = client.post(
        "/waitlist",
        json={
            "resource_id": resource.id,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
        },
        headers=auth_headers(second_student),
    )
    assert ok_res.status_code == 201
    entry_id = ok_res.json()["id"]

    # Duplicat -> 409
    dup_res = client.post(
        "/waitlist",
        json={
            "resource_id": resource.id,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
        },
        headers=auth_headers(second_student),
    )
    assert dup_res.status_code == 409

    # Alt utilizator nu poate șterge înscrierea -> 403
    forbidden_del = client.delete(
        f"/waitlist/{entry_id}",
        headers=auth_headers(student),
    )
    assert forbidden_del.status_code == 403

    # Proprietarul o poate șterge -> 204
    del_res = client.delete(
        f"/waitlist/{entry_id}",
        headers=auth_headers(second_student),
    )
    assert del_res.status_code == 204