from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Reservation,
    ReservationStatus,
    ResourceTraining,
    User,
    resource_admins,
)
from app.schemas import (
    PendingReservationOut,
    ReservationResourceSummary,
    TeamOut,
    UserOut,
)


def list_admin_pending_reservations(
    db: Session,
    admin: User,
    *,
    resource_id: int | None = None,
) -> list[PendingReservationOut]:
    """Returns PENDING reservations for resources administered by `admin`, with history flags."""
    administered_resource_ids = select(resource_admins.c.resource_id).where(
        resource_admins.c.user_id == admin.id
    )

    query = (
        select(Reservation)
        .options(
            joinedload(Reservation.user).joinedload(User.team),
            joinedload(Reservation.resource),
            joinedload(Reservation.team),
        )
        .where(
            Reservation.status == ReservationStatus.PENDING,
            Reservation.resource_id.in_(administered_resource_ids),
        )
        .order_by(Reservation.start_at.asc(), Reservation.created_at.asc(), Reservation.id.asc())
    )
    if resource_id is not None:
        query = query.where(Reservation.resource_id == resource_id)

    reservations = list(db.scalars(query).unique())
    if not reservations:
        return []

    user_ids = {r.user_id for r in reservations}
    resource_ids = {r.resource_id for r in reservations}

    first_rows = db.execute(
        select(
            Reservation.user_id,
            Reservation.resource_id,
            func.min(Reservation.id),
        )
        .where(
            Reservation.user_id.in_(user_ids),
            Reservation.resource_id.in_(resource_ids),
        )
        .group_by(Reservation.user_id, Reservation.resource_id)
    ).all()
    first_reservation_ids = {(uid, rid): min_id for uid, rid, min_id in first_rows}

    trained_pairs = set(
        db.execute(
            select(ResourceTraining.user_id, ResourceTraining.resource_id).where(
                ResourceTraining.user_id.in_(user_ids),
                ResourceTraining.resource_id.in_(resource_ids),
            )
        ).all()
    )

    result: list[PendingReservationOut] = []
    for r in reservations:
        is_first = first_reservation_ids.get((r.user_id, r.resource_id)) == r.id
        has_training = (r.user_id, r.resource_id) in trained_pairs
        result.append(
            PendingReservationOut(
                id=r.id,
                user_id=r.user_id,
                resource_id=r.resource_id,
                team_id=r.team_id,
                start_at=r.start_at,
                end_at=r.end_at,
                purpose=r.purpose,
                status=r.status,
                needs_review=r.needs_review,
                created_at=r.created_at,
                user=UserOut.model_validate(r.user),
                resource=ReservationResourceSummary.model_validate(r.resource),
                team=TeamOut.model_validate(r.team) if r.team is not None else None,
                is_first_reservation=is_first,
                has_completed_training=has_training,
            )
        )
    return result