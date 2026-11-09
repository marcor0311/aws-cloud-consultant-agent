"""Use the existing offline transport guard for all agent tests, not just demos."""

import socket

import pytest

from src.integrations.mock_network import install_mock_network_guard


@pytest.fixture(autouse=True)
def offline_network(monkeypatch):
    monkeypatch.setenv("LIVEKIT_INFERENCE_ENABLED", "0")
    monkeypatch.setenv("WORKFLOW_ENABLED", "0")
    monkeypatch.setenv(
        "CALENDAR_ACCESS_SERVICE_KEY", "offline-service-only-key-12345678901234567890"
    )
    monkeypatch.setenv("CALENDAR_ACCESS_URL", "http://127.0.0.1:1/api/calendar-access")
    monkeypatch.delenv("CALENDAR_CALL_RECEIPT_FILE", raising=False)
    # Register originals for fixture teardown; the guard replaces these methods.
    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, getattr(socket.socket, name))
    monkeypatch.setattr(socket, "getaddrinfo", socket.getaddrinfo)
    monkeypatch.setattr(socket, "_calendar_mock_guard", False, raising=False)
    install_mock_network_guard()
