import os
from pathlib import Path

from src import config


def test_config_uses_shared_project_env():
    assert Path(__file__).resolve().parents[2] / ".env" == config.ENV_FILE


def test_agent_loads_only_its_settings_and_respects_environment(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "LIVEKIT_URL=wss://file.example.test\n"
        "CALENDAR_ACCESS_SERVICE_KEY=agent-key\n"
        "CALENDAR_ACCESS_CODE_SECRET=backend-only\n"
        "CALENDAR_WHITELIST_API_KEY=backend-only\n"
        "CALENDAR_SMTP_PASSWORD=backend-only\n"
        "GOOGLE_ACCOUNT_EMAIL=sender@example.com\n"
    )
    keys = (
        "LIVEKIT_URL",
        "CALENDAR_ACCESS_SERVICE_KEY",
        "CALENDAR_ACCESS_CODE_SECRET",
        "CALENDAR_WHITELIST_API_KEY",
        "CALENDAR_SMTP_PASSWORD",
        "GOOGLE_ACCOUNT_EMAIL",
    )
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LIVEKIT_URL", "wss://environment.example.test")
    monkeypatch.setattr(config, "ENV_FILE", env)
    monkeypatch.chdir(tmp_path.parent)
    config.load_environment()
    assert os.environ["LIVEKIT_URL"] == "wss://environment.example.test"
    assert os.environ["CALENDAR_ACCESS_SERVICE_KEY"] == "agent-key"
    assert os.environ["GOOGLE_ACCOUNT_EMAIL"] == "sender@example.com"
    for key in (
        "CALENDAR_ACCESS_CODE_SECRET",
        "CALENDAR_WHITELIST_API_KEY",
        "CALENDAR_SMTP_PASSWORD",
    ):
        assert key not in os.environ
