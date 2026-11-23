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
from psycopg import sql
from psycopg.conninfo import make_conninfo
from pydantic import ValidationError
from pypdf import PdfReader

from app.api.delivery import configured_repository, repository, review_router, router
from app.delivery.mcp import create_server
from app.delivery.metrics import calculate_metrics
from app.delivery.models import DemoRequest, EmulatorEvidence, PhaseTiming
from app.delivery.workflow import DeliveryWorkflow
from app.persistence.delivery import DeliveryBusy, PostgresRepository


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
