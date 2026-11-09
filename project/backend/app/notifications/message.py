"""Render the verification email shared by Gmail and SMTP."""

import html
import re
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "templates" / "verification_code.html"


def build_code_message(
    sender: str, sender_name: str, email: str, code: str, minutes: int
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Código de verificación"
    message["From"] = formataddr((sender_name, sender))
    message["To"] = email
    message.set_content(
        f"Código de verificación\n\n{code}\n\n"
        f"Este código caduca en {minutes} minutos y solo puede utilizarse una vez.\n\n"
        "Si no solicitaste este código, puedes ignorar este mensaje.\n\n"
        "Mensaje automático. No respondas a este correo.\n"
    )
    content = TEMPLATE.read_text(encoding="utf-8")
    values = {"code": html.escape(code), "minutes": str(minutes)}
    content = re.sub(r"\{\{(code|minutes)\}\}", lambda m: values[m[1]], content)
    message.add_alternative(content, subtype="html")
    return message
