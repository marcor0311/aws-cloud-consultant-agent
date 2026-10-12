from uuid import uuid4


def prepare_secret_identity_request(superhero: str) -> dict[str, str]:
    """Prepare a traceable request for ChatGPT to answer from its own knowledge."""
    subject = superhero.strip()
    if not subject:
        raise ValueError("superhero must not be empty")

    return {
        "subject": subject,
        "verification_id": str(uuid4()),
    }


def get_batman_identity() -> dict[str, str]:
    """Return a test fact with a unique ID that proves this backend was called."""
    return {
        "subject": "Batman",
        "secret_identity": "Bruce Wayne",
        "verification_id": str(uuid4()),
    }
