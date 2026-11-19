from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import ensure_resource_admin
from app.models import (
    MaintenanceWindow,
    OperatingSchedule,
    Reservation,
    ReservationStatus,
    Resource,
    ResourceStatus,
    Role,
    Team,
    User,
)
from app.schemas import ReservationCreate, ReservationRescheduleRequest
from app.services.availability import APPROVED_STATUSES, PENDING_STATUSES, _as_utc, _overlaps
from app.services.schedule import SLOT_MINUTES, local_timezone
from app.services.sharing import (
    BLOCKING_STATUSES,
    CapacityConflictError,
    ensure_capacity_available,
    lock_resource_for_booking,
)

ALLOWED_TRANSITIONS: dict[ReservationStatus, set[ReservationStatus]] = {
    ReservationStatus.PENDING: {
        ReservationStatus.APPROVED,
        ReservationStatus.REJECTED,
        ReservationStatus.AWAITING_TRAINING,
        ReservationStatus.CANCELLED,
    },
    ReservationStatus.AWAITING_TRAINING: {
        ReservationStatus.APPROVED,
        ReservationStatus.REJECTED,
        ReservationStatus.CANCELLED,
    },
    ReservationStatus.APPROVED: {
        ReservationStatus.COMPLETED,
        ReservationStatus.CANCELLED,
    },
    ReservationStatus.REJECTED: set(),
    ReservationStatus.CANCELLED: set(),
    ReservationStatus.COMPLETED: set(),
}

ADMIN_DECISION_STATUSES = {
    ReservationStatus.APPROVED,
    ReservationStatus.REJECTED,
    ReservationStatus.AWAITING_TRAINING,
}

RESCHEDULABLE_STATUSES = {
    ReservationStatus.PENDING,
    ReservationStatus.AWAITING_TRAINING,
    ReservationStatus.APPROVED,
}


def _validate_slot_interval(local_start: datetime, local_end: datetime) -> None:
    if local_start >= local_end:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "start_at must be before end_at",
        )

    if (
        local_start.second != 0
        or local_start.microsecond != 0
        or local_end.second != 0
        or local_end.microsecond != 0
        or local_start.minute % SLOT_MINUTES != 0
        or local_end.minute % SLOT_MINUTES != 0
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Reservation start and end times must be aligned to 30-minute slots",
        )

    duration_seconds = int((local_end - local_start).total_seconds())
    if duration_seconds <= 0 or duration_seconds % (SLOT_MINUTES * 60) != 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Reservation interval must be a multiple of 30 minutes",
        )


def _validate_operating_schedule(
    db: Session, resource_id: int, local_start: datetime, local_end: datetime
) -> None:
    if local_start.date() != local_end.date():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Reservation must start and end on the same day within operating hours",
        )

    schedules = list(
        db.scalars(
            select(OperatingSchedule).where(
                OperatingSchedule.resource_id == resource_id,
                OperatingSchedule.weekday == local_start.weekday(),
            )
        )
    )

    req_start = local_start.time()
    req_end = local_end.time()
    in_schedule = any(
        schedule.start_time <= req_start and req_end <= schedule.end_time
        for schedule in schedules
    )
    if not in_schedule:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Requested slot is outside the resource operating schedule",
        )


def _ensure_no_maintenance_overlap(
    db: Session, resource_id: int, start_utc: datetime, end_utc: datetime
) -> None:
    windows = list(
        db.scalars(
            select(MaintenanceWindow).where(
                MaintenanceWindow.resource_id == resource_id,
                MaintenanceWindow.cancelled_at.is_(None),
            )
        )
    )
    for window in windows:
        if _overlaps((start_utc, end_utc), (_as_utc(window.start_at), _as_utc(window.end_at))):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Resource is scheduled for maintenance during this slot: {window.reason}",
            )


def create_reservation_request(
    db: Session, user: User, body: ReservationCreate
) -> Reservation:
    start_utc = _as_utc(body.start_at)
    end_utc = _as_utc(body.end_at)

    tz = local_timezone()
    local_start = start_utc.astimezone(tz)
    local_end = end_utc.astimezone(tz)

    _validate_slot_interval(local_start, local_end)

    # Row-level lock on resource (SELECT ... FOR UPDATE in PostgreSQL)
    resource = lock_resource_for_booking(db, body.resource_id)

    if resource.status == ResourceStatus.MAINTENANCE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Resource is currently under maintenance and cannot be reserved",
        )

    if resource.status != ResourceStatus.ACTIVE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Resource is not active",
        )

    if resource.max_duration_min is not None:
        duration_min = int((end_utc - start_utc).total_seconds()) // 60
        if duration_min > resource.max_duration_min:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Reservation exceeds maximum duration of {resource.max_duration_min} minutes",
            )

    _ensure_no_maintenance_overlap(db, resource.id, start_utc, end_utc)
    _validate_operating_schedule(db, resource.id, local_start, local_end)

    team_id = body.team_id if body.team_id is not None else user.team_id
    if team_id is not None and db.get(Team, team_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Team not found")

    try:
        ensure_capacity_available(
            db,
            resource,
            start_utc,
            end_utc,
            statuses=BLOCKING_STATUSES,
        )
    except CapacityConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    existing = list(
        db.scalars(
            select(Reservation).where(
                Reservation.resource_id == resource.id,
                Reservation.status.in_(PENDING_STATUSES | APPROVED_STATUSES),
            )
        )
    )
    overlapping = [
        res
        for res in existing
        if _overlaps((start_utc, end_utc), (_as_utc(res.start_at), _as_utc(res.end_at)))
    ]

    if any(
        res.user_id == user.id or (team_id is not None and res.team_id == team_id)
        for res in overlapping
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You or your team already have a reservation overlapping this slot",
        )

    reservation = Reservation(
        user_id=user.id,
        resource_id=resource.id,
        team_id=team_id,
        start_at=start_utc,
        end_at=end_utc,
        purpose=body.purpose,
        status=ReservationStatus.PENDING,
    )
    db.add(reservation)
    db.commit()
    db.refresh(reservation)
    return reservation


def _is_resource_admin(reservation: Reservation, user: User) -> bool:
    return user.role == Role.ADMIN and user in reservation.resource.admins


def get_reservation_or_404(db: Session, reservation_id: int) -> Reservation:
    reservation = db.get(Reservation, reservation_id)
    if reservation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reservation not found")
    return reservation


def validate_transition(
    current_status: ReservationStatus, target_status: ReservationStatus
) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise HTTPException(
            422,
            f"Illegal reservation status transition from {current_status.value} to {target_status.value}",
        )


def cancel_reservation(
    db: Session,
    reservation: Reservation,
    user: User,
    *,
    now: datetime | None = None,
) -> Reservation:
    validate_transition(reservation.status, ReservationStatus.CANCELLED)

    if not _is_resource_admin(reservation, user):
        if reservation.user_id != user.id:
            ensure_resource_admin(reservation.resource, user)

        current_time = _as_utc(now or datetime.now(timezone.utc))
        if current_time >= _as_utc(reservation.start_at):
            raise HTTPException(
                422,
                "Users can only cancel a reservation before its start time",
            )

    reservation.status = ReservationStatus.CANCELLED
    reservation.needs_review = False
    db.commit()
    db.refresh(reservation)
    return reservation


def transition_reservation(
    db: Session,
    reservation: Reservation,
    user: User,
    target_status: ReservationStatus,
    *,
    rejection_reason: str | None = None,
    now: datetime | None = None,
) -> Reservation:
    if target_status == ReservationStatus.CANCELLED:
        return cancel_reservation(db, reservation, user, now=now)

    ensure_resource_admin(reservation.resource, user)
    validate_transition(reservation.status, target_status)

    if target_status == ReservationStatus.APPROVED:
        resource = lock_resource_for_booking(db, reservation.resource_id)
        _ensure_no_maintenance_overlap(
            db, resource.id, _as_utc(reservation.start_at), _as_utc(reservation.end_at)
        )
        try:
            ensure_capacity_available(
                db,
                resource,
                reservation.start_at,
                reservation.end_at,
                statuses=APPROVED_STATUSES,
                exclude_reservation_id=reservation.id,
            )
        except CapacityConflictError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    if target_status == ReservationStatus.REJECTED:
        if not rejection_reason or not rejection_reason.strip():
            raise HTTPException(422, "Rejection reason is required")
        reservation.rejection_reason = rejection_reason.strip()

    if target_status in ADMIN_DECISION_STATUSES:
        reservation.decided_by = user.id
        reservation.decided_at = _as_utc(now or datetime.now(timezone.utc))

    reservation.status = target_status
    db.commit()
    db.refresh(reservation)
    return reservation


def list_reservations_needing_review(
    db: Session, admin: User, resource_id: int | None = None
) -> list[Reservation]:
    managed_ids = list(
        db.scalars(
            select(Resource.id).where(Resource.admins.any(User.id == admin.id))
        )
    )
    if not managed_ids:
        return []

    if resource_id is not None:
        if resource_id not in managed_ids:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You are not an administrator of this resource",
            )
        target_ids = [resource_id]
    else:
        target_ids = managed_ids

    return list(
        db.scalars(
            select(Reservation)
            .where(
                Reservation.resource_id.in_(target_ids),
                Reservation.needs_review.is_(True),
                Reservation.status == ReservationStatus.APPROVED,
            )
            .order_by(Reservation.start_at.asc(), Reservation.id.asc())
        )
    )


def reschedule_reservation(
    db: Session,
    reservation_id: int,
    admin: User,
    body: ReservationRescheduleRequest,
) -> Reservation:
    reservation = get_reservation_or_404(db, reservation_id)
    resource = lock_resource_for_booking(db, reservation.resource_id)
    ensure_resource_admin(resource, admin)

    if reservation.status not in RESCHEDULABLE_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot reschedule reservation in status {reservation.status.value}",
        )

    start_utc = _as_utc(body.start_at)
    end_utc = _as_utc(body.end_at)
    tz = local_timezone()
    local_start = start_utc.astimezone(tz)
    local_end = end_utc.astimezone(tz)

    _validate_slot_interval(local_start, local_end)

    if resource.status != ResourceStatus.ACTIVE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Resource is not active",
        )

    if resource.max_duration_min is not None:
        duration_min = int((end_utc - start_utc).total_seconds()) // 60
        if duration_min > resource.max_duration_min:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Reservation exceeds maximum duration of {resource.max_duration_min} minutes",
            )

    _ensure_no_maintenance_overlap(db, resource.id, start_utc, end_utc)
    _validate_operating_schedule(db, resource.id, local_start, local_end)

    statuses_to_check = (
        APPROVED_STATUSES if reservation.status == ReservationStatus.APPROVED else BLOCKING_STATUSES
    )
    try:
        ensure_capacity_available(
            db,
            resource,
            start_utc,
            end_utc,
            statuses=statuses_to_check,
            exclude_reservation_id=reservation.id,
        )
    except CapacityConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    reservation.start_at = start_utc
    reservation.end_at = end_utc
    reservation.needs_review = False
    reservation.decided_by = admin.id
    reservation.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(reservation)
    return reservation