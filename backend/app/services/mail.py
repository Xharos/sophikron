"""Replaceable invitation delivery without persisting cleartext activation secrets."""

import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol
from urllib.parse import quote

import anyio

from app.core.auth_config import AuthSettings


class MailDeliveryError(Exception):
    """Indicate unsuccessful or uncertain delivery without exposing transport details."""


class InvitationMailer(Protocol):
    """Define the injectable asynchronous invitation delivery boundary."""

    @property
    def available(self) -> bool:
        """Return whether delivery has been explicitly configured."""
        ...

    async def send_invitation(self, recipient: str, token: str) -> None:
        """Deliver a 48-hour activation credential without logging it."""
        ...


class DisabledMailer:
    """Fail explicitly instead of silently discarding activation messages."""

    available = False

    async def send_invitation(self, recipient: str, token: str) -> None:
        """Reject delivery when no transport is configured."""
        raise MailDeliveryError("Delivery unavailable")


class SmtpMailer:
    """Send through any authenticated TLS SMTP service with bounded worker concurrency."""

    available = True

    def __init__(self, settings: AuthSettings) -> None:
        """Load optional SMTP credentials once without placing them in diagnostics."""
        self.settings = settings
        self.limiter = anyio.CapacityLimiter(2)
        self._password: str | None = None
        if settings.smtp_password_file:
            try:
                with settings.smtp_password_file.open("rb") as source:
                    raw = source.read(4097)
                self._password = raw.decode("utf-8").rstrip("\r\n")
                if (
                    len(raw) > 4096
                    or not self._password
                    or any(character in self._password for character in "\r\n\x00")
                ):
                    raise ValueError
            except (OSError, ValueError, UnicodeError):
                raise ValueError("Cannot load SMTP credential") from None

    async def send_invitation(self, recipient: str, token: str) -> None:
        """Send off the event loop, using a fragment to keep tokens out of URL access logs."""

        def send() -> None:
            """Build a plain-text message and require verified TLS before authentication."""
            settings = self.settings
            message = EmailMessage()
            message["From"] = settings.smtp_sender
            message["To"] = recipient
            message["Subject"] = "Votre invitation Sophikron"
            link = f"{settings.activation_url}#token={quote(token, safe='')}"
            message.set_content(
                "Vous êtes invité à activer votre compte Sophikron.\n\n"
                f"{link}\n\nCe lien est valable 48 heures et ne peut être utilisé qu’une fois.\n"
            )
            context = ssl.create_default_context()
            if settings.smtp_security == "tls":
                connection = smtplib.SMTP_SSL(
                    settings.smtp_host, settings.smtp_port, timeout=10, context=context
                )
            else:
                connection = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
            with connection:
                if settings.smtp_security == "starttls":
                    connection.starttls(context=context)
                if settings.smtp_username:
                    connection.login(settings.smtp_username, self._password or "")
                connection.send_message(message)

        try:
            await anyio.to_thread.run_sync(send, limiter=self.limiter)
        except (OSError, smtplib.SMTPException, ValueError):
            raise MailDeliveryError("Delivery unavailable") from None
