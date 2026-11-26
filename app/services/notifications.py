"""E-mail notifications about reservations.

Usage from an endpoint (the e-mails go out after the response is sent):

    notifications = notify_new_request(db, reservation)
    db.commit()
    send_in_background(background_tasks, notifications)
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import (
    Notification,
    NotificationType,
    Reservation,
    ReservationStatus,
    User,
    WaitlistEntry,
)
from app.services.email import EmailSender, get_sender
from app.services.schedule import local_timezone

logger = logging.getLogger(__name__)

WEEKDAYS = ["luni", "marți", "miercuri", "joi", "vineri", "sâmbătă", "duminică"]


@dataclass(frozen=True)
class EmailContent:
    subject: str
    body: str


def _local(value: datetime) -> datetime:
    if value.tzinfo is None:  # SQLite returns naive UTC datetimes
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(local_timezone())


def format_interval(start_at: datetime, end_at: datetime) -> str:
    """E.g. 'luni, 23.11.2026, 09:00–10:30' in local time."""
    start, end = _local(start_at), _local(end_at)
    return f"{WEEKDAYS[start.weekday()]}, {start:%d.%m.%Y}, {start:%H:%M}–{end:%H:%M}"


def _footer() -> str:
    return f"\n\nDetalii în aplicație: {settings.frontend_url}\n\nResearch Resource Manager"


def new_request_email(reservation: Reservation, admin: User) -> EmailContent:
    requester = reservation.user
    interval = format_interval(reservation.start_at, reservation.end_at)
    lines = [
        f"Bună, {admin.first_name},",
        "",
        f"{requester.first_name} {requester.last_name} ({requester.email}) a trimis o cerere "
        f"de rezervare pentru {reservation.resource.name}.",
        "",
        f"Interval: {interval}",
    ]
    if reservation.team is not None:
        lines.append(f"Echipă: {reservation.team.name}")
    if reservation.purpose:
        lines.append(f"Scop: {reservation.purpose}")
    lines += ["", "Cererea așteaptă aprobarea ta."]
    return EmailContent(
        subject=f"Cerere nouă de rezervare: {reservation.resource.name}",
        body="\n".join(lines) + _footer(),
    )


def decision_email(reservation: Reservation) -> tuple[NotificationType, EmailContent]:
    """The e-mail for the requester after an administrator decided on the reservation."""
    resource = reservation.resource.name
    interval = format_interval(reservation.start_at, reservation.end_at)
    greeting = f"Bună, {reservation.user.first_name},\n\n"

    if reservation.status == ReservationStatus.APPROVED:
        return NotificationType.APPROVED, EmailContent(
            subject=f"Rezervare aprobată: {resource}",
            body=greeting + f"Rezervarea ta pentru {resource} ({interval}) a fost aprobată."
            + _footer(),
        )
    if reservation.status == ReservationStatus.REJECTED:
        reason = reservation.rejection_reason or "nu a fost precizat"
        return NotificationType.REJECTED, EmailContent(
            subject=f"Rezervare respinsă: {resource}",
            body=greeting + f"Rezervarea ta pentru {resource} ({interval}) a fost respinsă.\n"
            f"Motiv: {reason}" + _footer(),
        )
    if reservation.status == ReservationStatus.AWAITING_TRAINING:
        return NotificationType.TRAINING_REQUIRED, EmailContent(
            subject=f"Instruire necesară: {resource}",
            body=greeting + f"Pentru rezervarea ta la {resource} ({interval}) este necesară "
            "o instruire. Administratorul resursei te va contacta, iar cererea va fi reanalizată "
            "după instruire." + _footer(),
        )
    raise ValueError(f"No decision e-mail for reservation status {reservation.status.value}")


def _create(
    db: Session,
    user: User,
    reservation: Reservation | None,
    kind: NotificationType,
    content: EmailContent,
) -> Notification:
    notification = Notification(
        user_id=user.id,
        reservation_id=reservation.id if reservation is not None else None,
        type=kind,
        subject=content.subject,
        body=content.body,
    )
    db.add(notification)
    return notification


def notify_new_request(db: Session, reservation: Reservation) -> list[Notification]:
    """One notification for each administrator of the reserved resource."""
    notifications = []
    for admin in reservation.resource.admins:
        content = new_request_email(reservation, admin)
        notifications.append(
            _create(db, admin, reservation, NotificationType.NEW_REQUEST, content)
        )
    db.flush()
    return notifications


def notify_decision(db: Session, reservation: Reservation) -> Notification:
    """Notification for the requester: approved, rejected or training required."""
    kind, content = decision_email(reservation)
    notification = _create(db, reservation.user, reservation, kind, content)
    db.flush()
    return notification


def notify_training_completed(db: Session, reservation: Reservation) -> Notification:
    """Notification for the requester that training is completed and approval resumes."""
    resource = reservation.resource.name
    interval = format_interval(reservation.start_at, reservation.end_at)
    content = EmailContent(
        subject=f"Instruire finalizată: {resource}",
        body=(
            f"Bună, {reservation.user.first_name},\n\n"
            f"Instruirea pentru rezervarea ta la {resource} ({interval}) a fost marcată ca "
            f"finalizată. Cererea a revenit în analiză pentru aprobare." + _footer()
        ),
    )
    notification = _create(db, reservation.user, reservation, NotificationType.NEW_REQUEST, content)
    db.flush()
    return notification


def notify_waitlist_slot_available(db: Session, entry: WaitlistEntry) -> Notification:
    """Notification for a waitlisted user when an overlapping reservation is cancelled."""
    user = db.get(User, entry.user_id)
    resource = entry.resource.name
    interval = format_interval(entry.start_at, entry.end_at)
    content = EmailContent(
        subject=f"Slot disponibil: {resource}",
        body=(
            f"Bună, {user.first_name},\n\n"
            f"S-a eliberat un loc pentru {resource} în intervalul {interval}, "
            f"pentru care te-ai înscris pe lista de așteptare. Poți plasa acum o rezervare."
            + _footer()
        ),
    )
    notification = _create(db, user, None, NotificationType.NEW_REQUEST, content)
    db.flush()
    return notification


def deliver_with(db: Session, notification_ids: list[int], sender: EmailSender) -> None:
    """Sends the unsent notifications; a failed e-mail is logged and stays unsent."""
    notifications = db.scalars(
        select(Notification).where(
            Notification.id.in_(notification_ids), Notification.sent_at.is_(None)
        )
    )
    for notification in list(notifications):
        user = db.get(User, notification.user_id)
        try:
            sender.send(user.email, notification.subject, notification.body)
        except Exception:
            logger.exception("Could not send notification %s to %s", notification.id, user.email)
            continue
        notification.sent_at = datetime.now(timezone.utc)
        db.commit()


def deliver(
    notification_ids: list[int],
    sender: EmailSender | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
) -> None:
    """Background task: uses its own session, since the request's session is closed by then."""
    db = session_factory()
    try:
        deliver_with(db, notification_ids, sender or get_sender())
    finally:
        db.close()


def send_in_background(
    background_tasks: BackgroundTasks, notifications: list[Notification]
) -> None:
    """Schedules the e-mails to be sent after the response, so the API never waits on SMTP.

    Commit the notifications before the response is returned.
    """
    if notifications:
        background_tasks.add_task(deliver, [n.id for n in notifications])