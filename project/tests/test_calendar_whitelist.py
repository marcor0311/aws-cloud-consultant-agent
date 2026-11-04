import pytest

from app import config
from app.routes.calendar_access_routes import get_access_service
from app.services.calendar_access import CalendarAccessService
from app.services.calendar_whitelist import (
    HTTPWhitelist,
    MarkdownWhitelist,
    RegisteredContact,
    WhitelistUnavailable,
    configured_whitelist,
)

HEADER = "# Whitelist\n\n| email | name | enabled |\n| --- | --- | --- |\n"


def write_whitelist(path, rows):
    path.write_text(HEADER + rows, encoding="utf-8")
    return MarkdownWhitelist(path)


def test_markdown_records_normalize_email_and_preserve_enabled_state(tmp_path):
    repository = write_whitelist(
        tmp_path / "whitelist.md",
        "| First@example.com | Persona uno | true |\n"
        "| second@example.com | Persona dos | false |\n",
    )
    assert repository.lookup(" FIRST@example.com ") == RegisteredContact(
        "Persona uno", True
    )
    assert repository.lookup("second@example.com") == RegisteredContact(
        "Persona dos", False
    )
    assert repository.lookup("unknown@example.com") is None


def test_empty_table_allows_no_contacts(tmp_path):
    assert (
        write_whitelist(tmp_path / "whitelist.md", "").lookup("a@example.com") is None
    )


@pytest.mark.parametrize(
    "content",
    [
        "",
        "# No table\n",
        HEADER + "| invalid-email | Persona | true |\n",
        HEADER + "| a@example.com | Persona | yes |\n",
        HEADER + "| a@example.com | | true |\n",
        HEADER + "| a@example.com | Persona | true\n",
        HEADER + "| a@example.com | Persona | true | extra |\n",
        HEADER
        + "| a@example.com | Persona | true |\n| A@example.com | Otra | false |\n",
    ],
)
def test_invalid_file_fails_closed(tmp_path, content):
    path = tmp_path / "whitelist.md"
    path.write_text(content)
    with pytest.raises(WhitelistUnavailable):
        MarkdownWhitelist(path).lookup("a@example.com")


def test_missing_file_is_unavailable(tmp_path):
    with pytest.raises(WhitelistUnavailable):
        MarkdownWhitelist(tmp_path / "missing.md").lookup("a@example.com")


def test_access_flow_uses_file_and_revokes_after_record_disabled(tmp_path):
    path = tmp_path / "whitelist.md"
    repository = write_whitelist(path, "| a@example.com | Persona | true |\n")
    sent = []

    class Mailer:
        def send_code(self, email, name, code, minutes):
            sent.append(code)

    service = CalendarAccessService(
        tmp_path / "sessions.sqlite3", "x" * 40, Mailer(), repository
    )
    session = "session-whitelist"
    assert (
        service.start("unknown-session", "unknown@example.com", "test")["status"]
        == "not_registered"
    )
    assert not sent
    challenge = service.start(session, "a@example.com", "test")
    assert challenge["status"] == "code_sent"
    assert (
        service.verify(session, challenge["challenge_id"], sent[0])["status"]
        == "verified"
    )
    assert service.authorize(session, "a@example.com")["status"] == "authorized"
    write_whitelist(path, "| a@example.com | Persona | false |\n")
    assert service.authorize(session, "a@example.com")["status"] == "not_enabled"
    write_whitelist(path, "| a@example.com | Persona | true |\n")
    assert service.authorize(session, "a@example.com")["status"] != "authorized"


def test_file_failure_blocks_access_without_sending_mail(tmp_path):
    class Mailer:
        def send_code(self, *args):
            pytest.fail("No debe enviar correo sin comprobar la whitelist")

    service = CalendarAccessService(
        tmp_path / "sessions.sqlite3",
        "x" * 40,
        Mailer(),
        MarkdownWhitelist(tmp_path / "missing.md"),
    )
    assert (
        service.start("session-whitelist", "a@example.com", "test")["status"]
        == "unavailable"
    )


def test_provider_selection_and_paths_ignore_working_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
    monkeypatch.chdir(tmp_path.parent)
    monkeypatch.delenv("CALENDAR_WHITELIST_PROVIDER", raising=False)
    monkeypatch.delenv("CALENDAR_WHITELIST_FILE", raising=False)
    assert configured_whitelist() == MarkdownWhitelist(tmp_path / "whitelist.md")
    monkeypatch.setenv("CALENDAR_WHITELIST_FILE", str(tmp_path / "private.md"))
    assert configured_whitelist() == MarkdownWhitelist(tmp_path / "private.md")
    monkeypatch.setenv("CALENDAR_WHITELIST_PROVIDER", "http")
    assert isinstance(configured_whitelist(), HTTPWhitelist)
    monkeypatch.setenv("CALENDAR_WHITELIST_PROVIDER", "invalid")
    with pytest.raises(ValueError):
        configured_whitelist()


def test_backend_wires_file_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("CALENDAR_ACCESS_SERVICE_KEY", "k" * 40)
    monkeypatch.setenv("CALENDAR_ACCESS_CODE_SECRET", "s" * 40)
    monkeypatch.setenv("CALENDAR_ACCESS_DB", str(tmp_path / "sessions.sqlite3"))
    monkeypatch.setenv("CALENDAR_WHITELIST_PROVIDER", "file")
    monkeypatch.setenv("CALENDAR_WHITELIST_FILE", str(tmp_path / "whitelist.md"))
    get_access_service.cache_clear()
    try:
        assert isinstance(get_access_service().whitelist, MarkdownWhitelist)
    finally:
        get_access_service.cache_clear()


def test_backend_loads_canonical_env_with_environment_precedence(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("CONFIG_FILE_VALUE=from-file\nCONFIG_OVERRIDE=from-file\n")
    monkeypatch.setattr(config, "ENV_FILE", env)
    monkeypatch.delenv("CONFIG_FILE_VALUE", raising=False)
    monkeypatch.setenv("CONFIG_OVERRIDE", "from-environment")
    monkeypatch.chdir(tmp_path.parent)
    config.load_environment()
    import os

    assert os.environ["CONFIG_FILE_VALUE"] == "from-file"
    assert os.environ["CONFIG_OVERRIDE"] == "from-environment"
