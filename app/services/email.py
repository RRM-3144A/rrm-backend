import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.config import settings

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpSender:
    """Sends plain-text e-mails through the SMTP server from the settings."""

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = settings.mail_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)


class LogSender:
    """Development sender: writes the e-mail to the log instead of sending it."""

    def send(self, to: str, subject: str, body: str) -> None:
        logger.info("E-mail to %s: %s\n%s", to, subject, body)


def get_sender() -> EmailSender:
    return SmtpSender() if settings.smtp_host else LogSender()
