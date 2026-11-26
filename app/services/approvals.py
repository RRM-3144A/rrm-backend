from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.dependencies import ensure_resource_admin
from app.models import (
    Reservation,
    ReservationStatus,
    Resource,
    User,
    resource_admins,
)
from app.schemas import TeamUsageOut
from app.services.availability import _as_utc
from app.services.schedule import local_timezone

COUNTED_USAGE_STATUSES = {
    ReservationStatus.APPROVED,
    ReservationStatus.COMPLETED,
}


def get_team_resource_usage(
    db: Session,
    admin: User,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    resource_id: int | None = None,
) -> list[TeamUsageOut]:
    """Returns approved/completed reservation counts and hours per team for resources managed by `admin`."""
    if start_date is not None and end_date is not None and end_date < start_date:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "end_date must not be before start_date",
        )

    if resource_id is not None:
        resource = db.get(Resource, resource_id)
        if resource is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")
        ensure_resource_admin(resource, admin)
        target_resource_ids = [resource.id]
    else:
        target_resource_ids = list(
            db.scalars(
                select(resource_admins.c.resource_id).where(
                    resource_admins.c.user_id == admin.id
                )
            )
        )
        if not target_resource_ids:
            return []

    query = (
        select(Reservation)
        .options(joinedload(Reservation.team))
        .where(
            Reservation.resource_id.in_(target_resource_ids),
            Reservation.status.in_(COUNTED_USAGE_STATUSES),
        )
    )

    tz = local_timezone()
    range_start_utc = (
        datetime.combine(start_date, time.min, tzinfo=tz).astimezone(timezone.utc)
        if start_date is not None
        else None
    )
    range_end_utc = (
        datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=tz).astimezone(
            timezone.utc
        )
        if end_date is not None
        else None
    )

    if range_start_utc is not None:
        query = query.where(Reservation.end_at > range_start_utc)
    if range_end_utc is not None:
        query = query.where(Reservation.start_at < range_end_utc)

    reservations = list(db.scalars(query).unique())

    aggregated: dict[tuple[int | None, str], dict[str, float | int]] = {}
    for res in reservations:
        eff_start = _as_utc(res.start_at)
        eff_end = _as_utc(res.end_at)
        if range_start_utc is not None and eff_start < range_start_utc:
            eff_start = range_start_utc
        if range_end_utc is not None and eff_end > range_end_utc:
            eff_end = range_end_utc

        duration_seconds = (eff_end - eff_start).total_seconds()
        if duration_seconds <= 0:
            continue

        team_id = res.team_id
        team_name = res.team.name if res.team is not None else "Fără echipă"
        key = (team_id, team_name)
        if key not in aggregated:
            aggregated[key] = {"count": 0, "seconds": 0.0}
        aggregated[key]["count"] += 1
        aggregated[key]["seconds"] += duration_seconds

    usage = [
        TeamUsageOut(
            team_id=team_id,
            team_name=team_name,
            reservations_count=int(stats["count"]),
            reserved_hours=round(float(stats["seconds"]) / 3600.0, 2),
        )
        for (team_id, team_name), stats in aggregated.items()
    ]
    usage.sort(key=lambda item: (-item.reserved_hours, -item.reservations_count, item.team_name))
    return usage