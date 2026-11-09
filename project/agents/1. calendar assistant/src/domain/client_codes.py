"""Structural normalization and pronunciation of client codes, never authentication."""

import re
import unicodedata

PHONETIC = dict(
    zip(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        (
            "Alfa",
            "Bravo",
            "Charlie",
            "Delta",
            "Echo",
            "Foxtrot",
            "Golf",
            "Hotel",
            "India",
            "Juliett",
            "Kilo",
            "Lima",
            "Mike",
            "November",
            "Oscar",
            "Papa",
            "Quebec",
            "Romeo",
            "Sierra",
            "Tango",
            "Uniform",
            "Victor",
            "Whiskey",
            "X-ray",
            "Yankee",
            "Zulu",
        ),
    )
)
DIGITS = (
    "cero",
    "uno",
    "dos",
    "tres",
    "cuatro",
    "cinco",
    "seis",
    "siete",
    "ocho",
    "nueve",
)


def normalize_client_code(value: str) -> str:
    # Ñ must never become N when removing accents from phonetic words.
    if "ñ" in value.lower():
        raise ValueError("El código de cliente no admite Ñ.")
    value = "".join(
        c
        for c in unicodedata.normalize("NFD", value.lower())
        if not unicodedata.combining(c)
    )
    value = value.replace("x-ray", "xray")
    compact = re.sub(r"[\s,.-]", "", value).upper()
    if re.fullmatch(r"[A-Z]{4}[0-9]{4}", compact, flags=re.ASCII):
        return f"{compact[:4]}-{compact[4:]}"
    letters = {
        word.lower().replace("-", ""): letter for letter, word in PHONETIC.items()
    }
    letters.update({"alpha": "A", "juliet": "J", "whisky": "W"})
    tokens = re.split(r"[\s,.-]+", value.strip())
    parts = []
    for token in tokens:
        if token in letters:
            parts.append(letters[token])
        elif token in DIGITS:
            parts.append(str(DIGITS.index(token)))
        elif re.fullmatch(r"[a-z]|[0-9]+", token, flags=re.ASCII):
            parts.append(token.upper())
        else:
            raise ValueError("No pude reconocer el código de cliente.")
    compact = "".join(parts)
    if not re.fullmatch(r"[A-Z]{4}[0-9]{4}", compact, flags=re.ASCII):
        raise ValueError("No pude reconocer el código de cliente.")
    return f"{compact[:4]}-{compact[4:]}"


def prepare_client_confirmation(value: str) -> dict[str, str]:
    try:
        code = normalize_client_code(value)
    except ValueError:
        return {
            "estado": "invalido",
            "codigo_normalizado": "",
            "respuesta_para_decir": "No pude reconocer el código. Por favor, indique su código de cliente usando el alfabeto fonético internacional.",
        }
    spelling = f"Letras: {', '.join(PHONETIC[c] for c in code[:4])}. Números: {', '.join(DIGITS[int(c)] for c in code[5:])}"
    return {
        "estado": "pendiente_confirmacion",
        "codigo_normalizado": code,
        "deletreo_fonetico": spelling,
        "respuesta_para_decir": f"{spelling}. ¿Es correcto?",
    }
