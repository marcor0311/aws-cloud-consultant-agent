"""Backend configuration rooted in project/, independent of the caller directory."""

from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parents[3]
BACKEND_DIR = PROJECT_DIR / "backend"
REFERENCE_DIR = PROJECT_DIR.parent / "references"
ENV_FILE = PROJECT_DIR / ".env"


def load_environment() -> None:
    # Deployment environment variables take precedence over local configuration.
    load_dotenv(ENV_FILE, override=False)


def project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_DIR / path
