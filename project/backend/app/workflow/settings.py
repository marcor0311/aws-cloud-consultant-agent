"""Explicit configuration for the worker; never reuse client/OTP storage."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.core.config import private_path, project_path


@dataclass(frozen=True)
class WorkflowSettings:
    database_url: str
    checkpoint_url: str
    enabled: bool = False
    manager_id: str = "engagement-manager"
    manager_token: str = ""
    openai_key: str = ""
    openai_model: str = ""
    inference_enabled: bool = False
    slack_token: str = ""
    slack_user_id: str = ""
    google_token_file: Path | None = None
    pubsub_topic: str = ""
    pubsub_subscription: str = ""
    push_audience: str = ""
    push_service_account: str = ""
    github_secret: str = ""
    github_repositories: tuple[str, ...] = ()
    calendar_id: str = "primary"
    mode: str = "live"
    mock_dir: Path | None = None
    calendar_webhook_url: str = ""
    post_call_dir: Path | None = None
    transcript_token: str = ""

    @classmethod
    def from_environment(cls):
        mode = os.getenv("WORKFLOW_MODE", "mock")
        if mode not in {"mock", "live"}:
            raise ValueError("WORKFLOW_MODE debe ser mock o live.")
        mock_dir = None
        if mode == "mock":
            configured = os.getenv("WORKFLOW_MOCK_DIR", "")
            active = project_path("data/mock-workflow/active.json")
            mock_dir = (
                project_path(configured)
                if configured
                else (
                    Path(json.loads(active.read_text())["directory"])
                    if active.exists()
                    else project_path("data/mock-workflow/empty")
                )
            )
        database = os.getenv("WORKFLOW_DATABASE_URL", "").strip()
        if mode == "mock":
            database = f"sqlite:///{mock_dir / 'workflow.sqlite3'}"
        if not database:
            database = f"sqlite:///{project_path('data/workflow.sqlite3')}"
        if database.startswith("postgresql://"):
            database = database.replace("postgresql://", "postgresql+psycopg://", 1)
        checkpoint = os.getenv("WORKFLOW_CHECKPOINT_URL", "").strip()
        if mode == "mock":
            checkpoint = str(mock_dir / "checkpoints.sqlite3")
        if not checkpoint:
            checkpoint = (
                database.replace("postgresql+psycopg://", "postgresql://", 1)
                if database.startswith("postgresql+")
                else str(project_path("data/preparation.sqlite3"))
            )
        token_path = os.getenv("WORKFLOW_GOOGLE_TOKEN_FILE", "").strip()
        return cls(
            database_url=database,
            checkpoint_url=checkpoint,
            enabled=os.getenv("WORKFLOW_ENABLED", "0") == "1",
            manager_id=os.getenv(
                "WORKFLOW_MANAGER_ID",
                "stuart" if mode == "mock" else "engagement-manager",
            ),
            manager_token=os.getenv("WORKFLOW_MANAGER_TOKEN", ""),
            openai_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("WORKFLOW_OPENAI_MODEL", ""),
            inference_enabled=os.getenv("WORKFLOW_INFERENCE_ENABLED", "0") == "1",
            slack_token=os.getenv("SLACK_BOT_TOKEN", ""),
            slack_user_id=os.getenv("SLACK_EM_USER_ID", ""),
            google_token_file=private_path(token_path) if token_path else None,
            pubsub_topic="projects/mock/topics/meet"
            if mode == "mock"
            else os.getenv("WORKFLOW_PUBSUB_TOPIC", ""),
            pubsub_subscription=os.getenv("WORKFLOW_PUBSUB_SUBSCRIPTION", ""),
            push_audience=os.getenv("WORKFLOW_PUSH_AUDIENCE", ""),
            push_service_account=os.getenv("WORKFLOW_PUSH_SERVICE_ACCOUNT", ""),
            github_secret=os.getenv("WORKFLOW_GITHUB_WEBHOOK_SECRET", ""),
            github_repositories=tuple(
                filter(None, os.getenv("WORKFLOW_GITHUB_REPOSITORIES", "").split(","))
            ),
            calendar_id="primary"
            if mode == "mock"
            else os.getenv("GOOGLE_CALENDAR_ID", "primary"),
            mode=mode,
            mock_dir=mock_dir,
            calendar_webhook_url=os.getenv("WORKFLOW_CALENDAR_WEBHOOK_URL", ""),
            post_call_dir=project_path("data/post-call") if mode == "live" else None,
            transcript_token=os.getenv("WORKFLOW_TRANSCRIPT_TOKEN", ""),
        )

    def availability(self):
        if self.mode == "mock":
            return {
                "mode": "mock",
                "external_connections": False,
                "credentials_required": False,
                "time_source": "simulated",
                "providers": {
                    "calendar": "mock",
                    "meet": "mock",
                    "mail": "mock",
                    "model": "scripted_mock",
                    "slack": "mock",
                },
            }
        return {
            "mode": self.mode,
            "external_connections": self.mode != "mock",
            "enabled": self.enabled,
            "model": bool(
                self.openai_key and self.openai_model and self.inference_enabled
            ),
            "inference_enabled": self.inference_enabled,
            "slack": bool(self.slack_token and self.slack_user_id),
            "google": bool(self.google_token_file and self.google_token_file.is_file()),
            "pubsub_pull": bool(self.pubsub_subscription),
            "push_auth": bool(self.push_audience and self.push_service_account),
            "manager_access": len(self.manager_token) >= 32,
            "postgresql": self.database_url.startswith("postgresql+"),
            "calendar_webhook": bool(self.calendar_webhook_url),
            "post_call_delivery": self.post_call_dir is not None,
            "transcript_capture": len(self.transcript_token) >= 32,
        }
