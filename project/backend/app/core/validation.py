"""Shared backend validation for client records and transactional email."""

import re


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not re.fullmatch(
        r"[a-z0-9._%+-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}", email
    ):
        raise ValueError("El correo no tiene un formato válido.")
    local, domain = email.rsplit("@", 1)
    if (
        len(local) > 64
        or local.startswith(".")
        or local.endswith(".")
        or ".." in email
        or any(part.startswith("-") or part.endswith("-") for part in domain.split("."))
    ):
        raise ValueError("El correo no tiene un formato válido.")
    return email
