"""Transactional verification email. No delivery or secret logging."""

import html
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "calendar_code.html"


@dataclass(frozen=True)
class SMTPSettings:
    host: str
    port: int
    username: str
    password: str = field(repr=False)
    sender: str
    sender_name: str = ""
    security: str = "starttls"

    def __post_init__(self):
        if not self.host or not self.sender or self.security not in {"starttls", "ssl"}:
            raise ValueError("Configura SMTP con remitente y TLS.")
        if not 1 <= self.port <= 65535:
            raise ValueError("El puerto SMTP no es válido.")
        for value in (self.sender, self.sender_name):
            if "\r" in value or "\n" in value:
                raise ValueError("El remitente debe ocupar una sola línea.")
        if parseaddr(self.sender)[1] != self.sender or "@" not in self.sender:
            raise ValueError("SMTP_FROM debe ser una dirección sin nombre visible.")
        if bool(self.username) != bool(self.password):
            raise ValueError("Configura ambos campos de autenticación SMTP.")


class SMTPMailer:
    def __init__(self, settings: SMTPSettings):
        self.settings = settings

    def build_message(
        self, email: str, name: str, code: str, minutes: int
    ) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = "Código de verificación"
        message["From"] = formataddr((self.settings.sender_name, self.settings.sender))
        message["To"] = email
        message.set_content(
            f"Código de verificación\n\n{code}\n\n"
            f"Este código caduca en {minutes} minutos y solo puede utilizarse una vez.\n\n"
            "Si no solicitaste este código, puedes ignorar este mensaje.\n\n"
            "Mensaje automático. No respondas a este correo.\n"
        )
        content = TEMPLATE.read_text(encoding="utf-8")
        # Only the code and its lifetime appear in this neutral transactional email.
        values = {
            "code": html.escape(code),
            "minutes": str(minutes),
        }
        content = re.sub(r"\{\{(code|minutes)\}\}", lambda m: values[m[1]], content)
        message.add_alternative(content, subtype="html")
        return message

    def send_code(self, email: str, name: str, code: str, minutes: int) -> None:
        message = self.build_message(email, name, code, minutes)
        settings = self.settings
        context = ssl.create_default_context()
        if settings.security == "ssl":
            connection = smtplib.SMTP_SSL(
                settings.host, settings.port, timeout=10, context=context
            )
        else:
            connection = smtplib.SMTP(settings.host, settings.port, timeout=10)
        with connection as smtp:
            if settings.security == "starttls":
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            if settings.username:
                smtp.login(settings.username, settings.password)
            if smtp.send_message(message):
                raise smtplib.SMTPException("El servidor no aceptó el destinatario.")
