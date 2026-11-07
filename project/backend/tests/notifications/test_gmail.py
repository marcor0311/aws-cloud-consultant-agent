import base64
import json
import stat
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from app.cli import authorize_gmail
from app.notifications import gmail as gmail_mailer
from app.notifications.gmail import GMAIL_SEND_SCOPE, GmailMailer, GmailSettings
from app.notifications.provider import EnvironmentMailer


@pytest.fixture
def gmail(tmp_path, monkeypatch):
    token_file = tmp_path / "secrets" / "gmail_token.json"
    token_file.parent.mkdir()
    token_file.write_text(
        json.dumps(
            {
                "scopes": [GMAIL_SEND_SCOPE],
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
    )
    credentials = Mock(
        token="test-access-token",
        expired=False,
        valid=True,
        refresh_token="test-refresh-token",
    )
    credentials.has_scopes.return_value = True
    credentials.to_json.return_value = json.dumps(
        {
            "scopes": [GMAIL_SEND_SCOPE],
            "token_uri": "https://oauth2.googleapis.com/token",
            "token": "refreshed-test-token",
        }
    )
    monkeypatch.setattr(
        gmail_mailer.Credentials, "from_authorized_user_info", lambda _: credentials
    )
    return GmailMailer(GmailSettings("sender@example.com", token_file)), credentials


def test_gmail_sends_multipart_html_to_me_endpoint_without_exposing_code(
    gmail, monkeypatch
):
    mailer, _ = gmail
    captured = []

    def post(url, **kwargs):
        captured.append((url, kwargs))
        return httpx.Response(
            200, json={"id": "accepted-message"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", post)
    assert (
        mailer.send_code("recipient@example.com", "Ignored name", "003120", 5) is None
    )
    url, request = captured[0]
    assert url == "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    assert request["headers"] == {"Authorization": "Bearer test-access-token"}
    assert request["follow_redirects"] is False and request["timeout"] == 10
    message = BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(request["json"]["raw"])
    )
    assert message["From"] == "sender@example.com"
    assert message["To"] == "recipient@example.com"
    assert message["Subject"] == "Código de verificación"
    assert "003120" in message.get_body(preferencelist=("html",)).get_content()
    assert "003120" in message.get_body(preferencelist=("plain",)).get_content()


@pytest.mark.parametrize(
    "scopes", [[], ["https://www.googleapis.com/auth/calendar.events.owned"]]
)
def test_calendar_token_cannot_be_relabelled_to_send_mail(gmail, monkeypatch, scopes):
    mailer, _ = gmail
    mailer.settings.token_file.write_text(json.dumps({"scopes": scopes}))
    network = Mock(side_effect=AssertionError("Must not send"))
    monkeypatch.setattr(httpx, "post", network)
    with pytest.raises(RuntimeError, match="no está autorizado"):
        mailer.send_code("recipient@example.com", "", "003120", 5)
    network.assert_not_called()


def test_expired_token_refreshes_and_is_saved_atomically_with_private_permissions(
    gmail, monkeypatch
):
    mailer, credentials = gmail
    credentials.expired = True
    credentials.refresh.side_effect = lambda _: setattr(credentials, "expired", False)
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, **_: httpx.Response(
            200, json={"id": "sent"}, request=httpx.Request("POST", url)
        ),
    )
    mailer.send_code("recipient@example.com", "", "003120", 5)
    credentials.refresh.assert_called_once()
    saved = json.loads(mailer.settings.token_file.read_text())
    assert saved["token"] == "refreshed-test-token"
    assert stat.S_IMODE(mailer.settings.token_file.stat().st_mode) == 0o600
    assert list(mailer.settings.token_file.parent.iterdir()) == [
        mailer.settings.token_file
    ]


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_gmail_rejections_never_claim_success_or_retry_ambiguous_send(
    gmail, monkeypatch, status
):
    mailer, _ = gmail
    post = Mock(
        side_effect=lambda url, **_: httpx.Response(
            status, json={"error": "private detail"}, request=httpx.Request("POST", url)
        )
    )
    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(RuntimeError, match="no confirmó") as error:
        mailer.send_code("recipient@example.com", "", "003120", 5)
    assert post.call_count == 1
    assert "003120" not in str(error.value) and "test-access-token" not in str(
        error.value
    )


@pytest.mark.parametrize("response", [{}, {"id": ""}, [], {"id": 1}])
def test_gmail_requires_acceptance_receipt(gmail, monkeypatch, response):
    mailer, _ = gmail
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, **_: httpx.Response(
            200, json=response, request=httpx.Request("POST", url)
        ),
    )
    with pytest.raises(RuntimeError, match="no confirmó"):
        mailer.send_code("recipient@example.com", "", "003120", 5)


def test_missing_oauth_does_not_send(tmp_path, monkeypatch):
    mailer = GmailMailer(GmailSettings("sender@example.com", tmp_path / "absent.json"))
    post = Mock()
    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(RuntimeError, match="no está autorizado"):
        mailer.send_code("recipient@example.com", "", "003120", 5)
    post.assert_not_called()


def test_backend_selects_gmail_without_smtp_credentials(monkeypatch):
    monkeypatch.setenv("CALENDAR_MAIL_PROVIDER", "gmail")
    monkeypatch.setenv("GOOGLE_ACCOUNT_EMAIL", "sender@example.com")
    send = Mock()
    monkeypatch.setattr(GmailMailer, "send_code", send)
    EnvironmentMailer().send_code("recipient@example.com", "", "003120", 5)
    send.assert_called_once_with("recipient@example.com", "", "003120", 5)


def test_unknown_provider_fails_closed(monkeypatch):
    monkeypatch.setenv("CALENDAR_MAIL_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="proveedor"):
        EnvironmentMailer().send_code("recipient@example.com", "", "003120", 5)


def test_authorization_requests_only_send_scope_and_dedicated_token(
    tmp_path, monkeypatch
):
    client = tmp_path / "client.json"
    client.write_text("{}")
    token = tmp_path / "secrets" / "gmail.json"
    monkeypatch.setenv("GOOGLE_ACCOUNT_EMAIL", "sender@example.com")
    monkeypatch.setenv("CALENDAR_GMAIL_CLIENT_FILE", str(client))
    monkeypatch.setenv("CALENDAR_GMAIL_TOKEN_FILE", str(token))
    credentials = SimpleNamespace(
        granted_scopes=[GMAIL_SEND_SCOPE],
        refresh_token="test-refresh",
        to_json=lambda: json.dumps({"scopes": [GMAIL_SEND_SCOPE]}),
    )
    flow = Mock()
    flow.run_local_server.return_value = credentials
    factory = Mock(return_value=flow)
    monkeypatch.setattr(
        authorize_gmail.InstalledAppFlow, "from_client_secrets_file", factory
    )
    monkeypatch.setattr(authorize_gmail, "load_environment", lambda: None)
    assert authorize_gmail.authorize() == token
    assert factory.call_args.kwargs["scopes"] == [GMAIL_SEND_SCOPE]
    assert flow.run_local_server.call_args.kwargs["login_hint"] == "sender@example.com"
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
