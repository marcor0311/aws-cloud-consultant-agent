"""Select the transactional email adapter from backend configuration."""

import os

from app.notifications.gmail import GmailMailer, GmailSettings
from app.notifications.smtp import SMTPMailer, SMTPSettings


class EnvironmentMailer:
    """Load the selected provider only after checking the client registry."""

    def send_code(self, email: str, name: str, code: str, minutes: int):
        provider = os.getenv("CALENDAR_MAIL_PROVIDER", "smtp").strip().lower()
        if provider == "gmail":
            GmailMailer(GmailSettings.from_environment()).send_code(
                email, name, code, minutes
            )
            return
        if provider != "smtp":
            raise ValueError("El proveedor de correo no es válido.")
        settings = SMTPSettings(
            host=os.getenv("CALENDAR_SMTP_HOST", ""),
            port=int(os.getenv("CALENDAR_SMTP_PORT", "587")),
            username=os.getenv("CALENDAR_SMTP_USERNAME", ""),
            password=os.getenv("CALENDAR_SMTP_PASSWORD", ""),
            sender=os.getenv("CALENDAR_SMTP_FROM", ""),
            sender_name=os.getenv("CALENDAR_SMTP_SENDER_NAME", ""),
            security=os.getenv("CALENDAR_SMTP_SECURITY", "starttls"),
        )
        SMTPMailer(settings).send_code(email, name, code, minutes)
