from datetime import datetime, timezone

import pytest
from fastapi import BackgroundTasks
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import (
    Notification,
    NotificationType,
    Reservation,
    ReservationStatus,
    Resource,
    ResourceCategory,
    Role,
    Team,
)
from app.services import email as email_service
from app.services.email import LogSender, SmtpSender, get_sender
from app.services.notifications import (
    deliver,
    deliver_with,
    format_interval,
    notify_decision,
    notify_new_request,
    send_in_background,
)


class FakeSender:
    def __init__(self, fail_for: set[str] = frozenset()):
        self.sent: list[tuple[str, str, str]] = []
        self.fail_for = fail_for

    def send(self, to: str, subject: str, body: str) -> None:
        if to in self.fail_for:
            raise OSError("SMTP down")
        self.sent.append((to, subject, body))


@pytest.fixture
def admins(make_user):
    return [
        make_user(Role.ADMIN, first_name="Ana", email="ana@student.usv.ro"),
        make_user(Role.ADMIN, first_name="Mihai", email="mihai@student.usv.ro"),
    ]


@pytest.fixture
def reservation(db, admins, make_user):
    student = make_user(first_name="Ioana", last_name="Pop", email="ioana@student.usv.ro")
    resource = Resource(
        name="Imprimantă 3D Prusa", category=ResourceCategory(name="Imprimante"), admins=admins
    )
    reservation = Reservation(
        user=student,
        resource=resource,
        team=Team(name="Echipa Robotică"),
        # 09:00–10:30 in Bucharest (UTC+2 in November).
        start_at=datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 11, 23, 8, 30, tzinfo=timezone.utc),
        purpose="Prototip carcasă senzor",
    )
    db.add(reservation)
    db.commit()
    return reservation


def test_format_interval_uses_local_time_and_romanian_weekday():
    start = datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)
    end = datetime(2026, 11, 23, 8, 30, tzinfo=timezone.utc)

    assert format_interval(start, end) == "luni, 23.11.2026, 09:00–10:30"


def test_new_request_notifies_every_resource_admin(db, reservation, admins):
    notifications = notify_new_request(db, reservation)

    assert sorted(n.user_id for n in notifications) == sorted(a.id for a in admins)
    first = notifications[0]
    assert first.type == NotificationType.NEW_REQUEST
    assert first.reservation_id == reservation.id
    assert first.subject == "Cerere nouă de rezervare: Imprimantă 3D Prusa"
    for text in ["Ioana Pop", "ioana@student.usv.ro", "luni, 23.11.2026, 09:00–10:30",
                 "Echipa Robotică", "Prototip carcasă senzor"]:
        assert text in first.body
    assert first.sent_at is None


def test_approved_reservation_notifies_the_requester(db, reservation):
    reservation.status = ReservationStatus.APPROVED

    notification = notify_decision(db, reservation)

    assert notification.user_id == reservation.user_id
    assert notification.type == NotificationType.APPROVED
    assert notification.subject == "Rezervare aprobată: Imprimantă 3D Prusa"
    assert "a fost aprobată" in notification.body


def test_rejected_reservation_includes_the_reason(db, reservation):
    reservation.status = ReservationStatus.REJECTED
    reservation.rejection_reason = "Resursa este rezervată pentru un curs"

    notification = notify_decision(db, reservation)

    assert notification.type == NotificationType.REJECTED
    assert "Motiv: Resursa este rezervată pentru un curs" in notification.body


def test_training_required_notification(db, reservation):
    reservation.status = ReservationStatus.AWAITING_TRAINING

    assert notify_decision(db, reservation).type == NotificationType.TRAINING_REQUIRED


@pytest.mark.parametrize("status", [ReservationStatus.PENDING, ReservationStatus.CANCELLED])
def test_no_decision_email_for_other_statuses(db, reservation, status):
    reservation.status = status

    with pytest.raises(ValueError):
        notify_decision(db, reservation)


def test_deliver_sends_and_marks_as_sent(db, reservation):
    notifications = notify_new_request(db, reservation)
    db.commit()
    sender = FakeSender()

    deliver_with(db, [n.id for n in notifications], sender)

    assert sorted(to for to, _, _ in sender.sent) == ["ana@student.usv.ro", "mihai@student.usv.ro"]
    assert all(db.get(Notification, n.id).sent_at is not None for n in notifications)


def test_deliver_skips_notifications_already_sent(db, reservation):
    notifications = notify_new_request(db, reservation)
    db.commit()
    ids = [n.id for n in notifications]
    deliver_with(db, ids, FakeSender())
    sender = FakeSender()

    deliver_with(db, ids, sender)

    assert sender.sent == []


def test_failed_email_stays_unsent_and_others_still_go_out(db, reservation, admins):
    notifications = notify_new_request(db, reservation)
    db.commit()
    sender = FakeSender(fail_for={"ana@student.usv.ro"})

    deliver_with(db, [n.id for n in notifications], sender)

    assert [to for to, _, _ in sender.sent] == ["mihai@student.usv.ro"]
    sent_at = {n.user_id: db.get(Notification, n.id).sent_at for n in notifications}
    assert sent_at[admins[0].id] is None
    assert sent_at[admins[1].id] is not None


def test_deliver_opens_its_own_session(db, reservation):
    notification = notify_decision(db, _approve(reservation))
    db.commit()
    sender = FakeSender()

    deliver([notification.id], sender, sessionmaker(bind=db.get_bind()))

    assert [to for to, _, _ in sender.sent] == ["ioana@student.usv.ro"]


def test_emails_are_sent_in_the_background(db, reservation):
    notifications = notify_new_request(db, reservation)
    tasks = BackgroundTasks()

    send_in_background(tasks, notifications)

    assert len(tasks.tasks) == 1
    assert tasks.tasks[0].func is deliver
    assert tasks.tasks[0].args == ([n.id for n in notifications],)


def test_nothing_is_scheduled_without_notifications():
    tasks = BackgroundTasks()

    send_in_background(tasks, [])

    assert tasks.tasks == []


def test_log_sender_is_used_without_smtp_host(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")

    assert isinstance(get_sender(), LogSender)


def test_smtp_sender_logs_in_and_sends(monkeypatch):
    calls = []

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            calls.append(("starttls",))

        def login(self, username, password):
            calls.append(("login", username, password))

        def send_message(self, message):
            calls.append(("send", message["To"], message["Subject"], message["From"]))

    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSmtp)
    for name, value in {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "rrm",
        "smtp_password": "secret",
        "smtp_use_tls": True,
        "mail_from": "RRM <rrm@example.com>",
    }.items():
        monkeypatch.setattr(settings, name, value)

    sender = get_sender()
    sender.send("ioana@student.usv.ro", "Subiect", "Text")

    assert isinstance(sender, SmtpSender)
    assert calls == [
        ("connect", "smtp.example.com", 587),
        ("starttls",),
        ("login", "rrm", "secret"),
        ("send", "ioana@student.usv.ro", "Subiect", "RRM <rrm@example.com>"),
    ]


def _approve(reservation: Reservation) -> Reservation:
    reservation.status = ReservationStatus.APPROVED
    return reservation
