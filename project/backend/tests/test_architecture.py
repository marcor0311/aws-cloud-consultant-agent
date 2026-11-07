"""Dependency rules keep business features independent of HTTP and the voice agent."""

import ast
from pathlib import Path

import pytest

from app.core import config

APP = Path(__file__).resolve().parents[1] / "app"


def imports_in(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


@pytest.mark.parametrize(
    "relative", ["clients", "verification/service.py", "notifications"]
)
def test_business_and_adapters_do_not_depend_on_http_or_voice(relative):
    path = APP / relative
    files = list(path.rglob("*.py")) if path.is_dir() else [path]
    for file in files:
        for dependency in imports_in(file):
            assert dependency.split(".")[0] not in {"fastapi", "livekit", "src"}, (
                file,
                dependency,
            )
            assert not dependency.startswith("app.api.calendar_access"), (
                file,
                dependency,
            )
            assert not dependency.startswith("app.api.dependencies"), (
                file,
                dependency,
            )


def test_client_domain_does_not_depend_on_persistence_or_frameworks():
    imports = set(imports_in(APP / "clients/domain.py"))
    assert not imports & {"sqlite3", "pydantic", "fastapi", "httpx"}
    assert not any(name.startswith("app.") for name in imports)


@pytest.mark.parametrize(
    "relative",
    [
        "preparation/service.py",
        "preparation/models.py",
        "preparation/state.py",
        "preparation/ports.py",
        "verification/service.py",
        "workflow/service.py",
        "workflow/state.py",
        "workflow/transitions.py",
    ],
)
def test_business_services_do_not_construct_or_import_outer_adapters(relative):
    for dependency in imports_in(APP / relative):
        assert dependency.split(".")[0] not in {
            "fastapi",
            "httpx",
            "livekit",
            "google",
            "openai",
            "mcp",
            "sqlalchemy",
            "sqlite3",
            "langgraph",
        }
        assert not dependency.startswith(
            (
                "app.api",
                "app.bootstrap",
                "app.mcp_server",
                "app.integrations",
                "app.persistence",
                "app.demos",
                "app.verification.repository",
            )
        ), (relative, dependency)
        if relative in {"workflow/state.py", "workflow/transitions.py"}:
            assert not dependency.startswith("app.preparation")


@pytest.mark.parametrize(
    "relative", ["workflow/graph.py", "preparation/graph.py", "preparation/nodes.py"]
)
def test_graphs_receive_dependencies_instead_of_composing_adapters(relative):
    for dependency in imports_in(APP / relative):
        assert not dependency.startswith(
            (
                "app.api",
                "app.bootstrap",
                "app.mcp_server",
                "app.integrations",
                "app.persistence",
                "app.demos",
            )
        )


def test_backend_never_loads_the_voice_sdk():
    for file in APP.rglob("*.py"):
        assert not any(name.split(".")[0] == "livekit" for name in imports_in(file)), (
            file
        )


def test_configuration_remains_rooted_in_project_after_reorganization(
    tmp_path, monkeypatch
):
    project = APP.parents[1]
    monkeypatch.chdir(tmp_path)
    assert config.ENV_FILE == project / ".env"
    assert (
        config.project_path("data/calendar-access.sqlite3")
        == project / "data/calendar-access.sqlite3"
    )
    assert (
        config.project_path(str(tmp_path / "absolute.sqlite3"))
        == tmp_path / "absolute.sqlite3"
    )
