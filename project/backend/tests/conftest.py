"""Every ordinary backend test is offline; loopback transports remain available."""

import ipaddress
import socket

import pytest


@pytest.fixture(autouse=True)
def offline_network(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVEKIT_INFERENCE_ENABLED", "0")
    for key, value in {
        "CALENDAR_ACCESS_DB": str(tmp_path / "calendar-access.sqlite3"),
        "CALENDAR_ACCESS_SERVICE_KEY": "offline-service-only-key-12345678901234567890",
        "CALENDAR_ACCESS_CODE_SECRET": "offline-code-only-key-12345678901234567890",
        "WORKFLOW_DATABASE_URL": f"sqlite:///{tmp_path / 'workflow.sqlite3'}",
        "WORKFLOW_CHECKPOINT_URL": str(tmp_path / "checkpoints.sqlite3"),
        "WORKFLOW_MODE": "live",
        "WORKFLOW_ENABLED": "0",
        "WORKFLOW_GOOGLE_TOKEN_FILE": "",
        "WORKFLOW_CALENDAR_WEBHOOK_URL": "",
        "WORKFLOW_PUBSUB_TOPIC": "",
        "WORKFLOW_PUBSUB_SUBSCRIPTION": "",
        "WORKFLOW_TRANSCRIPT_TOKEN": "",
        "OPENAI_API_KEY": "",
        "SLACK_BOT_TOKEN": "",
    }.items():
        monkeypatch.setenv(key, value)
    connect, connect_ex, resolve = (
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.getaddrinfo,
    )

    def check(host):
        if host in {None, "localhost"}:
            return
        try:
            allowed = ipaddress.ip_address(host).is_loopback
        except ValueError:
            allowed = False
        if not allowed:
            raise AssertionError("Las pruebas offline bloquean conexiones externas.")

    def guarded_connect(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            check(address[0])
        return connect(sock, address)

    def guarded_connect_ex(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            check(address[0])
        return connect_ex(sock, address)

    def guarded_resolve(host, *args, **kwargs):
        check(host)
        return resolve(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_resolve)
