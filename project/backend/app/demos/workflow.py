"""Runnable offline journey: real LiveKit/MCP, LangGraph, SQL, and mocked providers."""

import asyncio
import base64
import hashlib
import json
import os
import socket
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from app.api import router as workflow_router
from app.api.dependencies import (
    get_access_service,
    get_call_receipt_key,
    get_runtime,
    require_service,
)
from app.bootstrap import create_runtime
from app.clients.repository import ClientRepository
from app.core.config import PROJECT_DIR
from app.integrations.mocks import load_projects
from app.mcp_server import create_server
from app.verification.repository import SQLiteVerificationRepository
from app.verification.service import CalendarAccessService
from app.workflow.runtime import timestamp
from app.workflow.settings import WorkflowSettings

MOCK_KEY = "local-mock-service-key-not-a-real-secret-0001"


class MockMailer:
    def __init__(self, path):
        self.path = path

    def send_code(self, email, name, code, minutes):
        mailbox = json.loads(self.path.read_text()) if self.path.exists() else {}
        mailbox[email] = {
            "code": code,
            "name": name,
            "is_mock": True,
            "expires_in_minutes": minutes,
        }
        self.path.write_text(json.dumps(mailbox, ensure_ascii=False, indent=2))


class AdvanceClock(BaseModel):
    seconds: float


def mock_backend(runtime, registry, mailbox):
    app = FastAPI(title="Offline workflow demo")
    access = CalendarAccessService(
        SQLiteVerificationRepository(runtime.settings.mock_dir / "clients.sqlite3"),
        "local-mock-code-secret-not-a-real-secret-0002",
        MockMailer(mailbox),
        registry,
        clock=runtime.store.clock,
    )

    def authorize(authorization: str = Header(default="")):
        if authorization != f"Bearer {MOCK_KEY}":
            raise HTTPException(401, "La demo requiere su clave local ficticia.")

    app.dependency_overrides[require_service] = authorize
    app.dependency_overrides[get_access_service] = lambda: access
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_call_receipt_key] = lambda: MOCK_KEY
    app.include_router(workflow_router, prefix="/api")

    @app.post("/mock/clock/advance", dependencies=[Depends(authorize)])
    def advance_clock(payload: AdvanceClock):
        runtime.mock_clock.advance(payload.seconds)
        return {"timestamp": runtime.store.clock(), "is_simulated": True}

    return app


@contextmanager
def local_server(app):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="off"))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("No se pudo iniciar el backend mock local.")
            time.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()


def drain(runtime):
    for _ in range(100):
        if not runtime.run_once():
            break
    failed = [
        j
        for j in runtime.store.pending_jobs()
        if j["status"] in {"failed", "uncertain"}
    ]
    if failed:
        raise RuntimeError(f"Falló una tarea mock: {failed}")


def book_with_livekit(runtime, project, client, url, mailbox):
    agent = PROJECT_DIR / "agents/1. calendar assistant"
    env = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "TMPDIR", "SYSTEMROOT")
        if key in os.environ
    }
    env.update(
        {
            "CALENDAR_ASSISTANT_MODE": "mock",
            "WORKFLOW_ENABLED": "1",
            "CALENDAR_MOCK_DB": str(
                runtime.settings.mock_dir / "mock-calendar.sqlite3"
            ),
            "MOCK_CLOCK_FILE": str(runtime.mock_clock.path),
            "MOCK_MAILBOX_FILE": str(mailbox),
            "MOCK_POST_CALL_DIR": str(runtime.settings.mock_dir / "post-call"),
            "MOCK_BACKEND_URL": url,
            "CALENDAR_ACCESS_URL": f"{url}/api/calendar-access",
            "CALENDAR_ACCESS_SERVICE_KEY": MOCK_KEY,
            "GOOGLE_CALENDAR_ID": "primary",
            "CALENDAR_ACCESS_ORIGIN_ID": "offline-demo",
        }
    )
    started = runtime.store.clock()
    result = subprocess.run(
        [str(agent / ".venv/bin/python"), "-m", "demos.voice"],
        cwd=agent,
        env=env,
        input=json.dumps({**project, "client_code": client.client_code}),
        text=True,
        capture_output=True,
        timeout=90,
    )
    if result.returncode:
        log = runtime.settings.mock_dir / f"{project['project_id']}-agent-error.log"
        log.write_text(result.stderr)
        raise RuntimeError(f"El recorrido LiveKit falló; diagnóstico: {log}")
    trace = json.loads(result.stdout)
    meetings = [
        m for m in runtime.store.list("meeting") if m["client_id"] == client.client_id
    ]
    if len(meetings) != 1:
        raise RuntimeError(
            "El SDK no produjo una reserva y un registro de workflow únicos."
        )
    case_id = meetings[0]["case_id"]
    runtime.store.register_project(
        case_id,
        project["project_id"],
        project["title"],
        project["company"],
        runtime.settings.manager_id,
        opened_at=started,
        is_fictitious=True,
    )
    runtime.store.phase(case_id, "scheduling", runtime.settings.manager_id)
    runtime.store.set_phase_start(case_id, "scheduling", started)
    for index, turn in enumerate(trace["trace"]):
        runtime.store.record_interval(
            f"{case_id}:call:{index}",
            case_id,
            "scheduling",
            "calendar-assistant",
            "agent",
            turn["started_at"],
            turn["ended_at"],
        )
    runtime.store.complete_phase(case_id, "scheduling")
    runtime.store.create_handoff(
        f"{case_id}:calendar:meeting",
        case_id,
        "calendar-assistant",
        runtime.settings.manager_id,
        "scheduling",
        "initial_meeting",
    )
    runtime.store.event(
        f"scheduled:{case_id}",
        case_id,
        "meeting.confirmed",
        {"provider": "mock_calendar", "is_simulated": True},
    )
    (runtime.settings.mock_dir / f"{project['project_id']}-call.json").write_text(
        json.dumps(trace, ensure_ascii=False, indent=2)
    )
    drain(runtime)
    waiting = runtime.service.get(case_id)
    if (
        waiting["state"]["status"] != "awaiting_meeting"
        or waiting["pending"][0]["action"] != "await_meeting_transcript"
    ):
        raise RuntimeError(
            "LangGraph debe esperar a la reunión humana antes de preparar insumos."
        )
    return case_id


def finish_meeting(runtime, case_id, project):
    meeting = runtime.store.get(f"meeting:{case_id}")
    start = timestamp(project["meeting_start"])
    runtime.mock_clock.move_to(start)
    runtime.store.accept_handoff(
        f"{case_id}:calendar:meeting", runtime.settings.manager_id
    )
    runtime.store.phase(case_id, "initial_meeting", runtime.settings.manager_id)
    runtime.mock_clock.advance(1800)
    runtime.store.record_interval(
        f"{case_id}:human-meeting",
        case_id,
        "initial_meeting",
        runtime.settings.manager_id,
        "human",
        start,
        runtime.store.clock(),
    )
    runtime.store.complete_phase(case_id, "initial_meeting")
    incoming = f"{case_id}:meeting:preparation"
    runtime.store.create_handoff(
        incoming,
        case_id,
        runtime.settings.manager_id,
        "preparation-agent",
        "initial_meeting",
        "preparation",
    )
    conference = f"conferenceRecords/mock-{case_id}"
    transcript_name = f"{conference}/transcripts/mock-transcript"
    runtime.store.put(
        f"mock-meeting:{conference}",
        "mock_meeting",
        {
            "conference": {
                "name": conference,
                "space": meeting["space"],
                "startTime": datetime.fromtimestamp(start).astimezone().isoformat(),
                "endTime": datetime.fromtimestamp(runtime.store.clock())
                .astimezone()
                .isoformat(),
            },
            "text": project["transcript"],
            "sources": [transcript_name],
            "is_fictitious": True,
        },
    )
    runtime.store.event(
        f"meeting-ended:{case_id}",
        case_id,
        "meeting.ended",
        {
            "participants": [project["contact"], "Stuart"],
            "agent_present": False,
            "is_simulated": True,
        },
    )
    runtime.store.accept_handoff(incoming, "preparation-agent")
    subscription = runtime.store.get(f"subscription:{meeting['space']}")
    runtime.receive_message(
        {
            "messageId": f"mock-transcript:{case_id}",
            "attributes": {
                "ce-id": f"mock-transcript:{case_id}",
                "ce-type": "google.workspace.meet.transcript.v2.fileGenerated",
                "ce-source": f"//workspaceevents.googleapis.com/{subscription['name']}",
            },
            "data": base64.b64encode(
                json.dumps({"transcript": {"name": transcript_name}}).encode()
            ).decode(),
        }
    )
    # No manager interaction: the worker prepares and sends the mock Slack notice.
    drain(runtime)


async def simulate_stuart(runtime):
    server = create_server(runtime.service, runtime)

    async def call(name, **args):
        result = await server.call_tool(name, args)
        return json.loads(result.content[0].text)

    trace = []
    listing = await call("agente_preparacion")
    trace.append(
        {"actor": "Stuart (mock)", "step": "Elegir proyecto", "result": listing}
    )
    project = listing["projects"][0]
    selected = await call("agente_preparacion", proyecto_id=project["project_id"])
    case_id, revision = project["case_id"], selected["revision"]
    runtime.mock_clock.advance(900)
    await call("comenzar_revision", expediente_id=case_id, revision=revision)
    runtime.mock_clock.advance(30)
    await call(
        "comentar_preparacion",
        expediente_id=case_id,
        revision=revision,
        comentario="Quiero priorizar el MVP y mantener explícitos los costos y fechas pendientes.",
    )
    runtime.mock_clock.advance(45)
    changed = await call(
        "actualizar_insumos",
        expediente_id=case_id,
        revision=revision,
        cambios={
            "summary": "Prioridad acordada para revisar: el recorrido mínimo de compra y gestión del pedido. "
            + selected["package"]["summary"],
            "presentation": [
                {
                    "title": "MVP primero",
                    "bullets": [
                        "Problema del cliente y recorrido de compra.",
                        "Alcance mínimo y exclusiones.",
                        "Presupuesto, plazo y validaciones todavía pendientes.",
                    ],
                }
            ],
        },
        comentario="Stuart y el agente reorganizan el planteamiento antes de presentar a dirección.",
    )
    revision = changed["state"]["revision"]
    # Only this offline journey uses placeholder documents; never real approved inputs.
    inputs = runtime.settings.mock_dir / "mock-presentation" / case_id / f"v{revision}"
    inputs.mkdir(parents=True, exist_ok=True)
    placeholders = {
        "resumen.pdf": changed["state"]["draft"],
        "ficha.pdf": json.dumps(changed["state"]["package"], ensure_ascii=False),
        "presentacion.html": json.dumps(
            changed["state"]["package"]["presentation"], ensure_ascii=False
        ),
        "presentacion.pdf": json.dumps(
            changed["state"]["package"]["presentation"], ensure_ascii=False
        ),
        "transcripcion.md": changed["state"]["transcript"],
    }
    files = []
    for name, text in placeholders.items():
        data = ("MOCK: documento de prueba offline\n" + text).encode()
        (inputs / name).write_bytes(data)
        files.append({"name": name, "sha256": hashlib.sha256(data).hexdigest()})
    await call(
        "registrar_archivos_presentacion",
        expediente_id=case_id,
        revision=revision,
        archivos=files,
        directorio=str(inputs),
    )
    await call("comenzar_revision", expediente_id=case_id, revision=revision)
    runtime.mock_clock.advance(15)
    script = await call(
        "revisar_preparacion",
        expediente_id=case_id,
        decision="approve",
        revision=revision,
    )
    trace.append(
        {
            "actor": "Stuart (mock)",
            "step": "Aprobar revisión exacta",
            "revision": revision,
        }
    )
    revision = script["state"]["revision"]
    await call("comenzar_revision", expediente_id=case_id, revision=revision)
    runtime.mock_clock.advance(30)
    await call(
        "revisar_preparacion",
        expediente_id=case_id,
        decision="approve",
        revision=revision,
    )
    trace.append(
        {
            "actor": "Stuart (mock)",
            "step": "Aprobar guion de la presentación",
            "revision": revision,
        }
    )
    exported = await call(
        "exportar_paquete_aprobado",
        expediente_id=case_id,
        revision=revision,
    )
    trace.append(
        {
            "actor": "Agente de preparación (mock)",
            "step": "Exportar paquete aprobado",
            "result": exported,
        }
    )
    runtime.mock_clock.advance(120)
    handoff = f"{case_id}:stage-1:stage-2:v{revision}"
    runtime.store.accept_handoff(handoff, "executive-direction-agent")
    runtime.store.phase(case_id, "stage-2", "executive-direction-agent")
    trace.append(
        {
            "actor": "Siguiente agente (mock)",
            "step": "Aceptar handoff",
            "handoff": handoff,
        }
    )
    drain(runtime)
    return trace


def export_run(runtime, collaboration):
    directory = runtime.settings.mock_dir
    for artifact in runtime.store.list("artifact"):
        project = next(
            p for p in runtime.owned_cases() if p["case_id"] == artifact["case_id"]
        )
        folder = (
            directory / "artifacts" / project["project_id"] / f"v{artifact['revision']}"
        )
        folder.mkdir(parents=True, exist_ok=True)
        for name, content in artifact["documents"].items():
            (folder / name).write_text(content)
    with runtime.store.engine.connect() as db:
        schema = (
            db.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name LIKE 'workflow_%'"
            )
            .scalars()
            .all()
        )
    (directory / "schema.sql").write_text(";\n\n".join(schema) + ";\n")
    report = {
        "mode": "mock",
        "external_connections": [],
        "time_source": "simulated",
        "scheduling_engine": "real LiveKit SDK + scripted mock LLM + real Calendar MCP",
        "orchestration": "LangGraph with SQL checkpoints and real interrupts",
        "projects": runtime.owned_cases(),
        "slack_outbox": runtime.store.list("mock_slack"),
        "collaboration": collaboration,
        "metrics": [runtime.store.metrics(p["case_id"]) for p in runtime.owned_cases()],
    }
    (directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    return report


def run_demo(directory, *, collaborate=False, activate=False):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    settings = WorkflowSettings(
        database_url=f"sqlite:///{directory / 'workflow.sqlite3'}",
        checkpoint_url=str(directory / "checkpoints.sqlite3"),
        enabled=True,
        manager_id="stuart",
        mode="mock",
        mock_dir=directory,
        pubsub_topic="projects/mock/topics/meet",
    )
    runtime = create_runtime(settings)
    try:
        registry = ClientRepository(directory / "clients.sqlite3")
        mailbox = directory / "mock-mailbox.json"
        planned = []
        with local_server(mock_backend(runtime, registry, mailbox)) as url:
            for project in load_projects():
                client = registry.create(project["company"], project["email"])
                planned.append(
                    (book_with_livekit(runtime, project, client, url, mailbox), project)
                )
            for case_id, project in planned:
                finish_meeting(runtime, case_id, project)
        collaboration = asyncio.run(simulate_stuart(runtime)) if collaborate else []
        report = export_run(runtime, collaboration)
        if activate:
            active = PROJECT_DIR / "data/mock-workflow/active.json"
            active.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = active.with_suffix(f".{uuid.uuid4().hex}.tmp")
            temporary.write_text(
                json.dumps({"directory": str(directory), "mode": "mock"})
            )
            os.replace(temporary, active)
        return report
    finally:
        runtime.close()
