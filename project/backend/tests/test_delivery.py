"""Business contract, timing mathematics and a real PostgreSQL-backed API."""

import asyncio
import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import ValidationError
from pypdf import PdfReader
from sqlalchemy import URL

from app.api.delivery import (
    case_report_service,
    configured_repository,
    repository,
    review_router,
    router,
)
from app.bootstrap import create_report_runtime
from app.delivery.mcp import create_server
from app.delivery.metrics import calculate_metrics
from app.delivery.models import DemoRequest, EmulatorEvidence, PhaseTiming
from app.delivery.workflow import DeliveryWorkflow
from app.persistence.delivery import DeliveryBusy, PostgresRepository
from app.persistence.workflow import WorkflowStore


@pytest.fixture
def payload():
    path = Path(__file__).resolve().parents[1] / "fixtures" / "delivery-1.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["delivery_id"] = str(uuid4())
    return value


@pytest.fixture
def repo():
    dsn = os.getenv("DELIVERY_TEST_DATABASE_URL")
    if not dsn:
        if os.getenv("DELIVERY_TEST_REQUIRE_DATABASE") == "true":
            pytest.fail("CI requiere PostgreSQL; no se permite omitir el recorrido")
        pytest.skip("Requiere DELIVERY_TEST_DATABASE_URL para PostgreSQL de pruebas")
    schema = "delivery_test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    repository = PostgresRepository(
        make_conninfo(dsn, options=f"-c search_path={schema}")
    )
    try:
        repository.initialize()
        yield repository
    finally:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


@pytest.fixture
def client(repo):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.include_router(review_router, prefix="/api")
    app.dependency_overrides[repository] = lambda: repo
    return TestClient(app)


def test_parallel_time_is_not_summed_as_elapsed(payload):
    metrics = calculate_metrics(DemoRequest.model_validate(payload).upstream_timings)
    architecture = metrics["phases"][0]
    assert architecture["lead_time_seconds"] == 1800
    assert architecture["active_elapsed_seconds"] == 1200
    assert architecture["process_time_seconds"] == 1500
    assert architecture["wait_seconds"] == 600
    assert architecture["human_effort_seconds"] == 900
    assert architecture["agent_effort_seconds"] == 600
    assert architecture["rework_effort_seconds"] == 300
    assert "discovery" in metrics["missing_phases"]
    assert metrics["global_lead_time_seconds"] is None


def test_wait_overlap_and_unclassified_time(payload):
    phase = copy.deepcopy(payload["upstream_timings"][0])
    phase["activities"] = phase["activities"][:2]
    phase["activities"].append(
        {
            "actor_id": "waiting-human",
            "actor_type": "human",
            "kind": "wait",
            "started_at": "2026-11-06T14:00:00Z",
            "ended_at": "2026-11-06T14:20:00Z",
        }
    )
    metrics = calculate_metrics([PhaseTiming.model_validate(phase)])["phases"][0]
    assert metrics["active_elapsed_seconds"] == 900
    assert metrics["wait_seconds"] == 300
    assert metrics["unclassified_seconds"] == 600


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_finops",
        "real_source",
        "fake_real_approval",
        "naive_time",
        "out_of_bounds",
        "negative_cost",
        "unknown_version",
        "unsupported_module",
    ],
)
def test_contract_rejects_ambiguous_or_invalid_inputs(payload, mutation):
    if mutation == "missing_finops":
        del payload["finops"]
    elif mutation == "real_source":
        payload["architecture"]["source"]["provenance"] = "real"
    elif mutation == "fake_real_approval":
        payload["architecture"]["approval_status"] = "approved"
    elif mutation == "naive_time":
        payload["upstream_timings"][0]["accepted_at"] = "2026-11-06T14:00:00"
    elif mutation == "out_of_bounds":
        payload["upstream_timings"][0]["activities"][0]["ended_at"] = (
            "2026-11-06T15:00:00Z"
        )
    elif mutation == "negative_cost":
        payload["finops"]["budget_monthly"] = "-1"
    elif mutation == "unknown_version":
        payload["schema_version"] = "2.0"
    else:
        payload["architecture"]["baseline"]["module_id"] = "ec2"
    with pytest.raises(ValidationError):
        DemoRequest.model_validate(payload)


def test_handoff_report_download_and_idempotency(client, repo, payload):
    response = client.post("/api/delivery/runs", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "draft_ready"
    assert result["handoff"]["implementation_status"] == "prepared"
    assert result["handoff"]["review_status"] == "pending"
    assert result["handoff"]["integration_status"] == "no_pr"
    assert result["report"]["status"] == "draft"
    assert {m["phase"] for m in result["metrics"]["phases"]} == {
        "architecture",
        "finops",
        "engineering",
        "report",
    }
    assert all(
        check["status"] == "not_run" for check in result["handoff"]["checks"][2:]
    )

    pdf_id = result["report"]["artifact"]["artifact_id"]
    download = client.get(
        f"/api/delivery/runs/{payload['delivery_id']}/artifacts/{pdf_id}"
    )
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    text = "\n".join(
        page.extract_text() for page in PdfReader(BytesIO(download.content)).pages
    )
    for expected in [
        "Informe ejecutivo",
        "100.00",
        "24.50",
        "75.50",
        "BORRADOR",
        "simulados",
        "No ejecutada",
        "pendiente",
    ]:
        assert expected in text
    assert client.post("/api/delivery/runs", json=payload).json() == result
    with repo.connect() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS count FROM delivery_artifacts"
            ).fetchone()["count"]
            == 4
        )
    assert (
        client.get(f"/api/delivery/runs/{uuid4()}/artifacts/{pdf_id}").status_code
        == 404
    )
    source_id = result["handoff"]["artifacts"][0]["artifact_id"]
    source = client.get(
        f"/api/delivery/runs/{payload['delivery_id']}/artifacts/{source_id}"
    ).text
    assert "?ref=" + payload["architecture"]["baseline"]["commit"] in source
    assert "bucket_name = var.bucket_name" in source


@pytest.mark.parametrize("case", ["different_revision", "over_budget", "kms_region"])
def test_business_block_does_not_produce_report(client, repo, payload, case):
    if case == "different_revision":
        payload["finops"]["architecture_revision"] = "other-design"
    elif case == "over_budget":
        payload["finops"]["estimate_monthly"] = "100.01"
    else:
        payload["architecture"]["kms_key_arn"] = payload["architecture"][
            "kms_key_arn"
        ].replace("us-east-1", "us-west-2")
    result = client.post("/api/delivery/runs", json=payload).json()
    assert result["status"] == "blocked"
    assert result["report"] is None
    assert result["handoff"] is None
    with repo.connect() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS count FROM delivery_artifacts"
            ).fetchone()["count"]
            == 0
        )


def test_report_revision_approval_and_close(
    client, repo, payload, monkeypatch, tmp_path
):
    # Only this integration journey accepts an alternate fixture. The ordinary
    # regression keeps delivery-1 and its original timing expectations.
    if input_path := os.getenv("DELIVERY_TEST_INPUT"):
        payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
        payload["delivery_id"] = str(uuid4())
    request = DemoRequest.model_validate(payload)
    output = Path(os.getenv("DELIVERY_TEST_OUTPUT", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DELIVERY_ENGAGEMENT_MANAGER", "Operador de demostración")
    if evidence_path := os.getenv("DELIVERY_TEST_EMULATOR_EVIDENCE"):
        evidence = EmulatorEvidence.model_validate_json(
            Path(evidence_path).read_bytes()
        )
        if os.getenv("GITHUB_ACTIONS") == "true":
            assert evidence.run_url
        assert all(check.status == "passed" for check in evidence.checks)
        assert evidence.matches(request)
        assert {check.name for check in evidence.checks} >= {
            "terraform fmt",
            "terraform init",
            "terraform validate",
            "Trivy",
            "AWS Emulator TLS",
            "terraform plan",
            "Políticas del plan",
            "terraform apply",
            "Verificación después de apply",
            "terraform destroy",
            "Eliminar contenedor",
        }
        result = DeliveryWorkflow(repo).run(request, evidence)
        assert (
            DeliveryWorkflow(PostgresRepository(repo.dsn)).run(request, evidence)
            == result
        )
    else:
        result = client.post("/api/delivery/runs", json=payload).json()
    assert result["status"] == "draft_ready"
    handoff = result["handoff"]
    assert handoff["review_status"] == "pending"
    assert handoff["integration_status"] == "no_pr"
    assert result["report"]["handoff_id"] == handoff["handoff_id"]
    phases = {phase["phase"]: phase for phase in result["metrics"]["phases"]}
    assert set(phases) == {t.phase for t in request.upstream_timings} | {
        "engineering",
        "report",
    }
    for phase, metric in phases.items():
        assert metric["provenance"] == (
            "real" if phase in {"engineering", "report"} else "simulated"
        )
        assert metric["lead_time_seconds"] >= 0
        assert metric["process_time_seconds"] >= 0
    if input_path and Path(input_path).name == "issue21-mock.json":
        architecture = phases["architecture"]
        assert architecture["lead_time_seconds"] == 2520
        assert architecture["process_time_seconds"] == 2220
        assert architecture["active_elapsed_seconds"] == 1860
        assert architecture["wait_seconds"] == 660
        assert architecture["rework_effort_seconds"] == 600
        assert not result["metrics"]["missing_phases"]
    persisted = PostgresRepository(repo.dsn).get(request.delivery_id)
    assert persisted["handoff"] == handoff
    assert persisted["report"] == result["report"]
    assert persisted["report_timing"]["provenance"] == "real"
    if evidence_path:
        assert persisted["request"]["emulator_evidence"] == evidence.model_dump(
            mode="json"
        )
        assert all(check["status"] == "passed" for check in handoff["checks"])
    for ref in [*handoff["artifacts"], result["report"]["artifact"]]:
        artifact = repo.artifact(request.delivery_id, ref["artifact_id"])
        content = bytes(artifact["content"])
        assert sha256(content).hexdigest() == ref["sha256"]
        (output / ref["filename"]).write_bytes(content)
    for name, value in {
        "input.json": payload,
        "delivery-draft.json": result,
        "handoff.json": handoff,
        "metrics.json": result["metrics"],
    }.items():
        (output / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    run_url = f"/api/delivery/runs/{result['delivery_id']}"
    first = result["report"]

    def decision(report, action, detail):
        return {
            "decision_id": str(uuid4()),
            "version": report["version"],
            "sha256": report["artifact"]["sha256"],
            "action": action,
            "detail": detail,
        }

    def submit(value):
        return client.post(f"{run_url}/report/decisions", json=value)

    assert (
        submit(decision(first, "record_presentation", "Sesión de prueba")).status_code
        == 409
    )
    changes = decision(first, "request_changes", "Agregar conclusión ejecutiva")
    assert submit(changes).json()["report"]["status"] == "changes_requested"
    revision = decision(first, "revise", "Conclusión revisada para dirección")
    second = submit(revision).json()["report"]
    assert second["version"] == 2
    assert submit(revision).json()["report"] == second
    assert submit(decision(first, "approve", "Revisión anterior")).status_code == 409
    assert (
        client.get(
            f"{run_url}/artifacts/{first['artifact']['artifact_id']}"
        ).status_code
        == 200
    )
    approved = submit(decision(second, "approve", "Aprobado en la demostración")).json()
    assert approved["status"] == "approved"
    pdf_id = approved["report"]["approved_document"]["artifact_id"]
    download = client.get(f"{run_url}/artifacts/{pdf_id}")
    text = "\n".join(
        page.extract_text() for page in PdfReader(BytesIO(download.content)).pages
    )
    assert request.project_name in " ".join(text.split())
    assert "costos simulados" in text
    assert "Gasto real" in text
    assert "No disponible" in text
    assert "APROBADO" in text
    assert "Conclusión revisada para dirección" in text
    assert second["artifact"]["sha256"] in text
    if evidence_path:
        if evidence.run_url:
            assert evidence.run_url in text
        assert "terraform destroy" in text
    closed = submit(
        decision(second, "record_presentation", "Acta de demostración")
    ).json()
    assert closed["status"] == "closed"
    history = client.get(f"{run_url}/report").json()["report_decisions"]
    assert [entry["decision"]["action"] for entry in history] == [
        "request_changes",
        "revise",
        "approve",
        "record_presentation",
    ]

    async def verify_mcp_download():
        server = create_server(repo, "Operador de demostración")
        result = await server.call_tool(
            "consultar_informe", {"entrega_id": payload["delivery_id"]}
        )
        report = result.structured_content
        assert report["status"] == "closed"
        resources = list(await server.read_resource(report["pdf_uri"]))
        assert len(resources) == 1
        assert resources[0].mime_type == "application/pdf"
        assert resources[0].content == download.content

    asyncio.run(verify_mcp_download())
    assert (
        sha256(download.content).hexdigest()
        == approved["report"]["approved_document"]["sha256"]
    )
    (output / "informe-ejecutivo-demostracion.pdf").write_bytes(download.content)
    (output / "delivery-closed.json").write_text(
        json.dumps(closed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "report-decisions.json").write_text(
        json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Continue the existing report journey with an independent case and measured
    # workflow records. No engineering node or cloud simulation may execute here.
    settings = conninfo_to_dict(repo.dsn)
    workflow_url = URL.create(
        "postgresql+psycopg",
        username=settings.get("user"),
        password=settings.get("password"),
        host=settings.get("host"),
        port=int(settings.get("port", "5432")),
        database=settings.get("dbname"),
        query={"options": settings["options"]},
    ).render_as_string(hide_password=False)
    clock = [1700000000.0]
    workflow = WorkflowStore(workflow_url, clock=lambda: clock[0])
    manager = "Operador de demostración"
    case_id = "issue22-independent"
    runtime = create_report_runtime(repo.dsn, workflow_url, manager)
    runtime.service.sources.store.clock = lambda: clock[0]
    try:
        workflow.register_project(
            case_id,
            request.project_id,
            request.project_name,
            "Empresa ficticia",
            manager,
            is_fictitious=True,
        )
        workflow.put(
            f"opening:{case_id}",
            "opening",
            {
                "budget": {"currency": "USD", "total": "100.00"},
                "is_fictitious": True,
                "approval_reference": "Decisión ficticia del recorrido de informe",
            },
        )
        workflow.phase(case_id, "stage-1", manager)
        parent = workflow.start_work(case_id, "stage-1", manager, "human")
        clock[0] += 5
        detail = workflow.start_work(case_id, "preparation", manager, "human")
        clock[0] += 5
        workflow.stop_work(detail, manager)
        clock[0] += 5
        workflow.stop_work(parent, manager)
        workflow.create_handoff(
            "report-input",
            case_id,
            manager,
            manager,
            "stage-1",
            "stage-2",
            revision=1,
            artifact_sha256="a" * 64,
        )
        clock[0] += 5
        workflow.accept_handoff("report-input", manager)
        workflow.phase(case_id, "stage-3", manager)
        human = workflow.start_work(case_id, "stage-3", manager, "human")
        clock[0] += 10
        agent = workflow.start_work(case_id, "stage-3", "architect-agent", "agent")
        clock[0] += 10
        workflow.stop_work(human, manager)
        clock[0] += 5
        workflow.stop_work(agent, "architect-agent")
        clock[0] += 15
        workflow.complete_phase(case_id, "stage-3")
        workflow.event(
            "revision-requested",
            case_id,
            "process.transition",
            {"kind": "stage.changes_requested", "actor": manager},
        )
        service = runtime.service
        client.app.dependency_overrides[case_report_service] = lambda: service

        def forbidden_engineering(*args, **kwargs):
            pytest.fail("El informe por expediente no debe ejecutar ingeniería")

        monkeypatch.setattr(DeliveryWorkflow, "run", forbidden_engineering)
        case_input = {"report_id": str(uuid4()), "case_id": case_id}
        initial = client.post("/api/delivery/reports", json=case_input)
        assert initial.status_code == 200, initial.text
        captured = initial.json()
        assert captured["handoff"] is None
        assert captured["closure_blockers"]
        phases = {p["phase"]: p for p in captured["metrics"]["phases"]}
        assert (
            phases["discovery"]["process_time_seconds"] == 15
        )  # No nested double count.
        assert phases["architecture"]["lead_time_seconds"] == 40
        assert phases["architecture"]["process_time_seconds"] == 35
        assert phases["architecture"]["active_elapsed_seconds"] == 25
        assert phases["architecture"]["unclassified_seconds"] == 15
        assert phases["architecture"]["wait_seconds"] is None
        assert phases["architecture"]["rework_effort_seconds"] is None
        assert phases["finops"]["process_time_seconds"] is None
        assert captured["metrics"]["handoffs"][0]["wait_seconds"] == 5
        assert captured["metrics"]["process_rework_cycles"] == 1
        clock[0] += 100
        assert client.post("/api/delivery/reports", json=case_input).json() == captured

        case_url = f"/api/delivery/runs/{case_input['report_id']}"
        draft = captured["report"]
        changed = client.post(
            f"{case_url}/report/decisions",
            json=decision(draft, "request_changes", "Precisar siguientes pasos"),
        )
        assert changed.status_code == 200
        revise = decision(draft, "revise", "Corrección de secciones")
        revise["sections"] = {
            "results": "Resultados revisados desde el expediente.",
            "next_steps": "Esperar la entrega aprobada del issue 21.",
        }
        revised = client.post(f"{case_url}/report/decisions", json=revise).json()[
            "report"
        ]
        assert revised["version"] == 2
        assert revised["sections"]["results"] == revise["sections"]["results"]
        assert (
            client.post(
                f"{case_url}/report/decisions",
                json=decision(draft, "approve", "Versión antigua"),
            ).status_code
            == 409
        )
        approved = client.post(
            f"{case_url}/report/decisions",
            json=decision(revised, "approve", "Aprobado como informe parcial"),
        ).json()
        blocked = client.post(
            f"{case_url}/report/decisions",
            json=decision(revised, "record_presentation", "Sesión registrada"),
        )
        assert blocked.status_code == 409
        assert "#21" in blocked.json()["detail"]
        assert (
            workflow.get(f"process:{case_id}") is None
        )  # Never fabricate a completed process.
        assert len(repo.report_decisions(case_input["report_id"])) == 3
        file = approved["report"]["approved_document"]
        data = client.get(f"{case_url}/artifacts/{file['artifact_id']}").content
        text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(data)).pages)
        assert "Resultados revisados desde el expediente." in text
        assert "BORRADOR" not in text
        assert "INFORME PARCIAL APROBADO" in text
        assert "Sin medición" in text
        assert "Entrega técnica pendiente" not in text  # Replaced, not appended.
        assert (
            client.get(
                f"{case_url}/artifacts/{draft['artifact']['artifact_id']}"
            ).status_code
            == 200
        )
        (output / "informe-expediente-parcial.pdf").write_bytes(data)

        # The same MCP tool consumes a persisted demo handoff, without rerunning it.
        async def verify_case_mcp():
            server = create_server(repo, manager, service)
            linked_input = {
                **case_input,
                "report_id": str(uuid4()),
                "engineering_delivery_id": payload["delivery_id"],
            }
            response = await server.call_tool(
                "generar_informe", {"entrada": linked_input}
            )
            linked = response.structured_content
            assert linked["handoff"]["handoff_id"] == handoff["handoff_id"]
            assert linked["report"]["handoff_id"] == handoff["handoff_id"]
            assert len(linked["closure_blockers"]) >= 2
            ref = linked["report"]["sources"]
            resource = list(
                await server.read_resource(
                    f"delivery://sources/{linked['delivery_id']}/{ref['artifact_id']}"
                )
            )[0]
            raw = (
                resource.content.encode()
                if isinstance(resource.content, str)
                else resource.content
            )
            assert sha256(raw).hexdigest() == ref["sha256"]
            assert json.loads(raw)["technical"]["project_id"] == request.project_id
            (output / "fuentes-informe-expediente.json").write_bytes(raw)
            pdf_resource = list(await server.read_resource(linked["pdf_uri"]))[0]
            (output / "informe-expediente-con-entrega.pdf").write_bytes(
                pdf_resource.content
            )
            other = create_server(repo, "Otro operador")
            with pytest.raises(ToolError, match="otro responsable"):
                await other.call_tool(
                    "consultar_informe", {"entrega_id": linked["delivery_id"]}
                )
            return linked

        linked = asyncio.run(verify_case_mcp())
        assert linked["captured_at"] != captured["captured_at"]
        monkeypatch.setenv("DELIVERY_ENGAGEMENT_MANAGER", "Otro operador")
        assert client.get(f"{case_url}/report").status_code == 403
        assert (
            client.get(f"{case_url}/artifacts/{file['artifact_id']}").status_code == 403
        )
    finally:
        runtime.close()
        workflow.engine.dispose()


def test_missing_input_is_422(client, payload):
    del payload["finops"]
    assert client.post("/api/delivery/runs", json=payload).status_code == 422


def test_identifier_cannot_be_reused_for_different_version(client, payload):
    assert client.post("/api/delivery/runs", json=payload).status_code == 200
    payload["project_name"] = "Otra versión"
    assert client.post("/api/delivery/runs", json=payload).status_code == 409


def test_restart_resumes_committed_engineering_without_duplicates(repo, payload):
    request = DemoRequest.model_validate(payload)

    def broken_pdf(*args):
        raise RuntimeError("fallo de prueba antes del PDF")

    with pytest.raises(RuntimeError):
        DeliveryWorkflow(repo, pdf_renderer=broken_pdf).run(request)
    failed = repo.get(request.delivery_id)
    assert failed["status"] == "failed"
    assert failed["handoff"] is not None
    first_handoff = failed["handoff"]
    restarted = DeliveryWorkflow(PostgresRepository(repo.dsn)).run(request)
    assert restarted["status"] == "draft_ready"
    assert restarted["handoff"] == first_handoff
    with repo.connect() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS count FROM delivery_artifacts"
            ).fetchone()["count"]
            == 4
        )


def test_concurrent_worker_cannot_process_same_run(repo, payload):
    request = DemoRequest.model_validate(payload)
    with repo.locked(request.delivery_id), ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(DeliveryWorkflow(repo).run, request)
        with pytest.raises(DeliveryBusy):
            future.result(timeout=10)
    assert DeliveryWorkflow(repo).run(request)["status"] == "draft_ready"


def test_repository_migration_is_repeatable(repo):
    repo.initialize()


def test_main_backend_still_loads_and_registers_delivery():
    from app.main import app

    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        schema = client.get("/openapi.json").json()
        assert "/api/delivery/runs" in schema["paths"]
        assert "/api/calendar-access/start" in schema["paths"]


def test_disabled_without_database(monkeypatch, payload):
    monkeypatch.delenv("DELIVERY_DATABASE_URL", raising=False)
    configured_repository.cache_clear()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as client:
        assert client.post("/api/delivery/runs", json=payload).status_code == 503
    configured_repository.cache_clear()
