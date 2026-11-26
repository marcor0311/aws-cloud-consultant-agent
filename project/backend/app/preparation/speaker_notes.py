"""Compose a local speaking draft from the approved slides, without inference."""

import hashlib
import json

from app.preparation.models import ExecutivePackage


def presentation_digest(package):
    return hashlib.sha256(
        json.dumps(package["presentation"], sort_keys=True).encode()
    ).hexdigest()


def compose_speaker_notes(package: ExecutivePackage) -> str:
    slides = package.presentation
    if not slides or any(not slide.title.strip() for slide in slides):
        raise ValueError(
            "El guion requiere una presentación con diapositivas tituladas."
        )

    def sentence(text):
        text = text.strip()
        return text if not text or text[-1] in ".!?…:;" else text + "."

    sections = [
        "## Apertura\n\n"
        f"Gracias por el espacio. Hoy presentaremos {sentence(slides[0].title)} "
        "Recorreremos el planteamiento y dejaremos un espacio final para preguntas.",
    ]
    for index, slide in enumerate(slides, 1):
        points = "\n\n".join(
            sentence(point) for point in slide.bullets if point.strip()
        )
        sections.append(
            f"## Diapositiva {index} — {slide.title}\n\n"
            f"{sentence(slide.title)}\n\n{points}\n\n"
            "[Pausa para enfatizar el mensaje y comprobar si hay preguntas.]"
        )
    sections.append(
        "## Cierre\n\n"
        "Con esto concluye la presentación. Abrimos el espacio para preguntas y "
        "comentarios; cualquier dato que requiera validación quedará como pendiente."
    )
    return "\n\n".join(sections)
