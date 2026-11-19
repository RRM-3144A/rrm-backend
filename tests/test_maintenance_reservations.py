from datetime import datetime, time, timezone

from app.models import (
    OperatingSchedule,
    Reservation,
    ReservationStatus,
    Resource,
    ResourceCategory,
)
from app.services.schedule import local_timezone
from tests.conftest import auth_headers


def _setup_resource(db, admin) -> Resource:
    category = ResourceCategory(name=f"MaintResCat-{id(db)}")
    db.add(category)
    db.flush()

    resource = Resource(
        name="Laser Cutter Pro",
        category_id=category.id,
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


def _local_dt(hour: int, minute: int = 0, day_offset: int = 0) -> datetime:
    tz = local_timezone()
    base = datetime(2027, 2, 15 + day_offset, hour, minute, tzinfo=tz)
    return base.astimezone(timezone.utc)


def test_maintenance_blocks_new_reservations_and_marks_slots_unavailable(
    client, db, student, admin
):
    resource = _setup_resource(db, admin)
    maint_start = _local_dt(10, 0)
    maint_end = _local_dt(12, 0)

    res_maint = client.post(
        f"/resources/{resource.id}/maintenance",
        headers=auth_headers(admin),
        json={
            "start_at": maint_start.isoformat(),
            "end_at": maint_end.isoformat(),
            "reason": "Calibrare optică",
        },
    )
    assert res_maint.status_code == 201

    # Availability endpoint shows slots in 10:00-12:00 as MAINTENANCE with 0 free places
    avail = client.get(
        f"/resources/{resource.id}/availability",
        headers=auth_headers(student),
        params={"start_date": "2027-02-15", "end_date": "2027-02-15"},
    )
    assert avail.status_code == 200
    maint_slots = [s for s in avail.json() if s["status"] == "MAINTENANCE"]
    assert len(maint_slots) == 4
    assert all(s["free_places"] == 0 for s in maint_slots)

    # New reservation request overlapping maintenance is blocked with 422
    res_book = client.post(
        "/reservations",
        headers=auth_headers(student),
        json={
            "resource_id": resource.id,
            "start_at": _local_dt(10, 30).isoformat(),
            "end_at": _local_dt(11, 30).isoformat(),
        },
    )
    assert res_book.status_code == 422
    assert "maintenance" in res_book.json()["detail"].lower()


def test_creating_maintenance_flags_overlapping_approved_reservations_for_review(
    client, db, student, admin, make_user
):
    resource = _setup_resource(db, admin)
    other_student = make_user()

    overlapping_approved = Reservation(
        user_id=student.id,
        resource_id=resource.id,
        start_at=_local_dt(10, 0),
        end_at=_local_dt(11, 0),
        status=ReservationStatus.APPROVED,
    )
    non_overlapping_approved = Reservation(
        user_id=other_student.id,
        resource_id=resource.id,
        start_at=_local_dt(14, 0),
        end_at=_local_dt(15, 0),
        status=ReservationStatus.APPROVED,
    )
    overlapping_pending = Reservation(
        user_id=other_student.id,
        resource_id=resource.id,
        start_at=_local_dt(11, 0),
        end_at=_local_dt(12, 0),
        status=ReservationStatus.PENDING,
    )
    db.add_all([overlapping_approved, non_overlapping_approved, overlapping_pending])
    db.commit()

    res_maint = client.post(
        f"/resources/{resource.id}/maintenance",
        headers=auth_headers(admin),
        json={
            "start_at": _local_dt(9, 30).isoformat(),
            "end_at": _local_dt(12, 30).isoformat(),
            "reason": "Revizie tehnică",
        },
    )
    assert res_maint.status_code == 201

    db.refresh(overlapping_approved)
    db.refresh(non_overlapping_approved)
    db.refresh(overlapping_pending)

    assert overlapping_approved.needs_review is True
    assert non_overlapping_approved.needs_review is False
    assert overlapping_pending.needs_review is False

    # Admin can query reservations flagged for review
    review_list = client.get(
        "/reservations/needs-review",
        headers=auth_headers(admin),
        params={"resource_id": resource.id},
    )
    assert review_list.status_code == 200
    items = review_list.json()
    assert len(items) == 1
    assert items[0]["id"] == overlapping_approved.id
    assert items[0]["needs_review"] is True


def test_admin_can_cancel_flagged_reservation(client, db, student, admin):
    resource = _setup_resource(db, admin)
    reservation = Reservation(
        user_id=student.id,
        resource_id=resource.id,
        start_at=_local_dt(10, 0),
        end_at=_local_dt(11, 0),
        status=ReservationStatus.APPROVED,
        needs_review=True,
    )
    db.add(reservation)
    db.commit()

    res = client.post(
        f"/reservations/{reservation.id}/cancel",
        headers=auth_headers(admin),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "CANCELLED"
    assert body["needs_review"] is False


def test_admin_can_reschedule_flagged_reservation_to_valid_slot(client, db, student, admin):
    resource = _setup_resource(db, admin)
    reservation = Reservation(
        user_id=student.id,
        resource_id=resource.id,
        start_at=_local_dt(10, 0),
        end_at=_local_dt(11, 0),
        status=ReservationStatus.APPROVED,
        needs_review=True,
    )
    db.add(reservation)
    db.commit()

    # Schedule maintenance on 10:00 - 12:00
    assert (
        client.post(
            f"/resources/{resource.id}/maintenance",
            headers=auth_headers(admin),
            json={
                "start_at": _local_dt(10, 0).isoformat(),
                "end_at": _local_dt(12, 0).isoformat(),
                "reason": "Mentenanță dimineață",
            },
        ).status_code
        == 201
    )

    # Rescheduling into maintenance window is rejected
    bad_reschedule = client.post(
        f"/reservations/{reservation.id}/reschedule",
        headers=auth_headers(admin),
        json={
            "start_at": _local_dt(11, 0).isoformat(),
            "end_at": _local_dt(12, 0).isoformat(),
        },
    )
    assert bad_reschedule.status_code == 422

    # Rescheduling to afternoon slot 15:00 - 16:00 succeeds and clears needs_review
    new_start = _local_dt(15, 0)
    new_end = _local_dt(16, 0)
    ok_reschedule = client.post(
        f"/reservations/{reservation.id}/reschedule",
        headers=auth_headers(admin),
        json={
            "start_at": new_start.isoformat(),
            "end_at": new_end.isoformat(),
        },
    )
    assert ok_reschedule.status_code == 200
    data = ok_reschedule.json()
    assert data["status"] == "APPROVED"
    assert data["needs_review"] is False
    assert datetime.fromisoformat(data["start_at"]).replace(tzinfo=timezone.utc) == new_start
    assert datetime.fromisoformat(data["end_at"]).replace(tzinfo=timezone.utc) == new_end