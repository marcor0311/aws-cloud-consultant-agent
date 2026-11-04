"""Backend configuration: one explicit file, independent of the working directory."""

from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_DIR / ".env"


def load_environment() -> None:
    # Deployment environment variables take precedence over local configuration.
    load_dotenv(ENV_FILE, override=False)


def project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_DIR / path
