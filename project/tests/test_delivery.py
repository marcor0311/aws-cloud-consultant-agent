"""Business contract, timing mathematics and a real PostgreSQL-backed API."""

import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from app.delivery.api import configured_repository, repository, router
from app.delivery.metrics import calculate_metrics
from app.delivery.models import DemoRequest, PhaseTiming
from app.delivery.repository import DeliveryBusy, PostgresRepository
from app.delivery.workflow import DeliveryWorkflow
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo
from pydantic import ValidationError
from pypdf import PdfReader


@pytest.fixture
def payload():
    path = Path(__file__).resolve().parents[1] / "examples" / "delivery-1.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["delivery_id"] = str(uuid4())
    return value


@pytest.fixture
def repo():
    dsn = os.getenv("DELIVERY_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Requiere DELIVERY_TEST_DATABASE_URL para PostgreSQL de pruebas")
    schema = "delivery_test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    repository = PostgresRepository(
        make_conninfo(dsn, options=f"-c search_path={schema}")
    )
    repository.initialize()
    try:
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
        assert "/api/agent" in schema["paths"]


def test_disabled_without_database(monkeypatch, payload):
    monkeypatch.delenv("DELIVERY_DATABASE_URL", raising=False)
    configured_repository.cache_clear()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as client:
        assert client.post("/api/delivery/runs", json=payload).status_code == 503
    configured_repository.cache_clear()
