"""Business contract, timing mathematics and a real PostgreSQL-backed API."""

import asyncio
import base64
import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
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
from app.bootstrap import create_engineering_runtime, create_report_runtime
from app.delivery.engineering_mcp import create_server as create_engineering_server
from app.delivery.engineering_models import (
    CHECKS,
    EngineeringEvidence,
    EngineeringFile,
    EngineeringIntake,
    EngineeringRelease,
    package_digest,
)
from app.delivery.mcp import create_server
from app.delivery.metrics import calculate_metrics
from app.delivery.models import (
    CaseReportRequest,
    DemoRequest,
    EmulatorEvidence,
    PhaseTiming,
)
from app.delivery.workflow import DeliveryWorkflow
from app.integrations.langgraph import LangGraphExecution
from app.persistence.delivery import DeliveryBusy, DeliveryConflict, PostgresRepository
from app.persistence.workflow import WorkflowStore
from app.workflow.graph import build_process_graph
from app.workflow.service import ProcessService
from app.workflow.state import initial_state


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


def test_handoff_report_download_and_idempotency(
    client, repo, payload, tmp_path, monkeypatch
):
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

    # Extend this handoff journey with intake of recorded upstream decisions and
    # already-produced evidence. No Terraform/emulator or external API executes.
    settings = conninfo_to_dict(repo.dsn)
    url = URL.create(
        "postgresql+psycopg",
        username=settings.get("user"),
        password=settings.get("password"),
        host=settings.get("host"),
        port=int(settings.get("port", "5432")),
        database=settings.get("dbname"),
        query={"options": settings["options"]},
    ).render_as_string(hide_password=False)
    runtime = create_engineering_runtime(url, tmp_path, "engineer")
    store, service = runtime.store, runtime.service
    clock = [1700000000.0]
    store.clock = lambda: clock[0]
    case_id, repository_name = "engineering-pilot", "example/engineering-pilot"
    architecture_commit, finops_commit, implementation_commit = (
        "a" * 40,
        "b" * 40,
        "c" * 40,
    )

    def file(role, name, commit):
        content = ("Fictitious approved/exported bytes: " + name).encode()
        (tmp_path / name).write_bytes(content)
        return {
            "role": role,
            "path": name,
            "sha256": sha256(content).hexdigest(),
            "reference": f"https://github.com/{repository_name}/blob/{commit}/{name}",
        }

    try:
        store.register_project(
            case_id,
            "engineering-pilot",
            "Piloto ficticio de ingeniería",
            "Empresa ficticia",
            "engineer",
            is_fictitious=True,
        )
        store.put(f"owner:{case_id}", "owner", {"manager_id": "engineer"})
        execution = LangGraphExecution(build_process_graph(InMemorySaver()))
        # The fixture starts at architecture; it does not invent a real meeting.
        execution.start(
            f"process:{case_id}",
            {
                **initial_state(case_id, "engineer"),
                "stage": 3,
                "status": "awaiting_deliverable",
            },
        )
        process = ProcessService(execution, store, "engineer")
        process.ensure(case_id)
        input_data = {
            "intake_id": str(uuid4()),
            "case_id": case_id,
            "incoming_handoff_id": f"{case_id}:process:2:3",
            "repository": repository_name,
            "architecture": {
                "commit": architecture_commit,
                "revision": 1,
                "files": [
                    file("requirements", "requirements.md", architecture_commit),
                    file("design", "design.md", architecture_commit),
                    file("policies", "policies.json", architecture_commit),
                ],
                "approval": {
                    "event_id": "architecture-approved",
                    "actor": "architect",
                    "reference": f"https://github.com/{repository_name}/pull/1#review",
                },
            },
            "finops": {
                "commit": finops_commit,
                "revision": 1,
                "files": [
                    file("calculator_export", "estimate.csv", finops_commit),
                    file("cost_workbook", "forecast.xlsx", finops_commit),
                ],
                "approval": {
                    "event_id": "finops-approved",
                    "actor": "finops",
                    "reference": f"https://github.com/{repository_name}/pull/2#review",
                },
            },
            "finops_architecture_commit": architecture_commit,
            "finops_architecture_sha256": "0" * 64,
            "modules": [
                {
                    "repository": "example/baselines",
                    "path": "aws/s3",
                    "commit": "d" * 40,
                    "approval_reference": "https://github.com/example/baselines/pull/1",
                    "approved_by": "architect",
                }
            ],
            "region": "us-east-1",
            "budget": "100.00",
            "estimate": "24.50",
            "currency": "USD",
            "period": "month",
            "calculator_url": "https://calculator.aws/#/estimate/fictitious",
        }
        draft = EngineeringIntake.model_validate(input_data)
        input_data["finops_architecture_sha256"] = draft.approval_digest(3)
        intake = EngineeringIntake.model_validate(input_data)
        with pytest.raises(DeliveryConflict, match="proceso"):
            service.register(intake)
        assert service.repository.get(intake.intake_id) is None
        for stage, package in ((3, intake.architecture), (4, intake.finops)):
            process.internal(
                case_id,
                f"ready-{stage}",
                "deliverable.ready",
                revision=1,
                artifact_sha256=intake.approval_digest(stage),
                evidence=[package.approval.reference],
            )
            process.internal(
                case_id,
                package.approval.event_id,
                "stage.approved",
                revision=1,
                artifact_sha256=intake.approval_digest(stage),
                evidence=[package.approval.reference],
                actor=package.approval.actor,
            )
        original = (tmp_path / "design.md").read_bytes()
        (tmp_path / "design.md").write_bytes(b"tampered after approval")
        with pytest.raises(ValueError, match="SHA-256"):
            service.register(intake)
        assert store.handoff(intake.incoming_handoff_id)["accepted_at"] is None
        (tmp_path / "design.md").write_bytes(original)
        receipt = service.register(intake)
        assert receipt["intake"]["approval_validation"] == "matched_workflow_decisions"
        assert receipt["intake"]["is_fictitious"]
        assert receipt["evidence_status"] == "not_received"
        assert store.handoff(intake.incoming_handoff_id)["accepted_by"] == "engineer"
        assert service.register(intake)["intake"] == receipt["intake"]
        altered = {**input_data, "budget": "150.00"}
        with pytest.raises(DeliveryConflict, match="otra entrada"):
            service.register(EngineeringIntake.model_validate(altered))
        archived = service.repository.file(
            intake.intake_id, intake.architecture.files[1].sha256
        )
        assert base64.b64decode(archived["content_base64"]) == original

        early_report_runtime = create_report_runtime(repo.dsn, url, "engineer")
        early_request = CaseReportRequest(
            report_id=uuid4(), case_id=case_id, intake_id=intake.intake_id
        )
        try:
            early_report_runtime.service.sources.store.clock = lambda: clock[0]
            early_report = early_report_runtime.service.generate(early_request)
            assert early_report["engineering"]["evidence_status"] == "not_received"
            assert early_report["report"]["intake_id"] == str(intake.intake_id)
        finally:
            early_report_runtime.close()

        start = clock[0]
        code = file("implementation", "main.tf", implementation_commit)
        logs = [
            file("log", "run.log", implementation_commit),
            file("security_report", "security.json", implementation_commit),
            file("policy_report", "policy.json", implementation_commit),
        ]
        check_intervals = {
            "terraform fmt": (10, 20),
            "terraform plan": (20, 40),
            "Trivy": (25, 45),
            "terraform validate": (50, 60),
            "Eliminar contenedor": (60, 65),
        }
        checks = []
        for name in CHECKS:
            check = {
                "name": name,
                "status": "not_run",
                "detail": "Fictitious recorded check; no command executed by this test",
            }
            if name in check_intervals:
                a, b = check_intervals[name]
                check.update(
                    status="passed",
                    started_at=datetime.fromtimestamp(start + a, UTC).isoformat(),
                    ended_at=datetime.fromtimestamp(start + b, UTC).isoformat(),
                )
            if name == "terraform validate":
                check["kind"] = "rework"
            if name == "Eliminar contenedor":
                check.update(status="failed", failure_origin="cleanup")
            checks.append(check)
        evidence_data = {
            "scope": "local_emulator",
            "run_id": str(uuid4()),
            "intake_id": str(intake.intake_id),
            "input_sha256": receipt["intake"]["input_sha256"],
            "implementation_commit": implementation_commit,
            "implementation_tree_sha256": package_digest(
                [EngineeringFile.model_validate(code)]
            ),
            "plan_sha256": "e" * 64,
            "run_reference": f"https://github.com/{repository_name}/actions/runs/123",
            "modules": input_data["modules"],
            "versions": {
                "terraform": "recorded-test",
                "aws_provider": "recorded-test",
                "aws_emulator": "recorded-test",
                "trivy": "recorded-test",
            },
            "resources": ["aws_s3_bucket.documents"],
            "actor": "engineering-runner",
            "checks": checks,
            "files": [code, *logs],
        }
        clock[0] = start + 30
        human = store.start_work(case_id, "stage-5", "engineer", "human")
        clock[0] = start + 50
        store.stop_work(human, "engineer")
        clock[0] = start + 100
        wrong = {**evidence_data, "input_sha256": "0" * 64}
        with pytest.raises(DeliveryConflict, match="otra entrada"):
            service.record_evidence(EngineeringEvidence.model_validate(wrong))
        assert not service.repository.runs(intake.intake_id)
        evidence = EngineeringEvidence.model_validate(evidence_data)
        result = service.record_evidence(evidence)
        assert result["evidence_status"] == "failed"
        phase = result["phase_metrics"]
        assert phase["lead_time_seconds"] == 100
        assert phase["in_progress"]
        assert phase["process_time_seconds"] == 70
        assert phase["active_elapsed_seconds"] == 55
        assert phase["human_effort_seconds"] == 20
        assert phase["agent_effort_seconds"] == 50
        assert phase["recorded_rework_effort_seconds"] == 10
        assert phase["wait_seconds"] is None
        assert phase["unclassified_seconds"] == 45
        assert service.record_evidence(evidence)["evidence"] == result["evidence"]
        assert len(store.metrics(case_id)["sessions"]) == 6
        assert store.get(f"process:{case_id}")["stage"] == 5
        assert result["review_status"] == "pending"
        catalog = service.catalog(intake.intake_id)
        assert catalog["revision"] == 1
        assert catalog["entries"][0]["status"] == "failed"
        assert catalog["entries"][0]["versions"] == evidence_data["versions"]
        assert store.get(f"phase:{case_id}:stage-5")["completed_at"] is None

        async def inspect_mcp():
            server = create_engineering_server(service)
            assert (
                await server.call_tool(
                    "registrar_entrada_ingenieria", {"entrada": input_data}
                )
            ).structured_content["intake"] == receipt["intake"]
            assert (
                await server.call_tool(
                    "registrar_evidencias_ingenieria", {"evidencia": evidence_data}
                )
            ).structured_content["evidence"] == result["evidence"]
            response = await server.call_tool(
                "consultar_ingenieria", {"intake_id": str(intake.intake_id)}
            )
            assert response.structured_content["evidence_status"] == "failed"
            resource = list(
                await server.read_resource(
                    f"engineering://artifact/{intake.intake_id}/{intake.architecture.files[1].sha256}"
                )
            )[0]
            assert resource.content == original

        asyncio.run(inspect_mcp())
        reopened = create_engineering_runtime(url, tmp_path, "engineer")
        report_runtime = create_report_runtime(repo.dsn, url, "engineer")
        try:
            reopened.store.clock = report_runtime.service.sources.store.clock = lambda: (
                clock[0]
            )
            assert (
                reopened.service.get(intake.intake_id)["evidence"] == result["evidence"]
            )
            snapshot = report_runtime.service.sources.capture(
                CaseReportRequest(report_id=uuid4(), case_id=case_id), "engineer"
            )
            assert (
                next(
                    p
                    for p in snapshot["metrics"]["phases"]
                    if p["phase"] == "engineering"
                )["process_time_seconds"]
                == 70
            )
            assert (
                snapshot["measurements"]["technical_evidence"][0]["evidence_sha256"]
                == result["evidence"][0]["evidence_sha256"]
            )

            # Continue the same journey: receipts -> report -> partial approval,
            # preserving the earlier report even after evidence has arrived.
            preserved = report_runtime.service.generate(early_request)
            assert preserved["report"]["artifact"] == early_report["report"]["artifact"]
            assert preserved["engineering"]["selected_run_id"] is None
            with pytest.raises(LookupError, match="no incluido"):
                report_runtime.service.read_engineering_file(
                    early_request.report_id, code["sha256"]
                )
            store.register_project(
                "other-case",
                "other-project",
                "Otro expediente ficticio",
                "Empresa ficticia",
                "engineer",
                is_fictitious=True,
            )
            with pytest.raises(ValueError, match="otro expediente"):
                report_runtime.service.generate(
                    CaseReportRequest(
                        report_id=uuid4(),
                        case_id="other-case",
                        intake_id=intake.intake_id,
                    )
                )
            source_key = f"engineering-file:{intake.intake_id}:{intake.architecture.files[1].sha256}"
            store.put(
                source_key,
                "engineering-file",
                {
                    **archived,
                    "content_base64": base64.b64encode(b"corrupted archive").decode(),
                },
            )
            try:
                with pytest.raises(DeliveryConflict, match="hash"):
                    report_runtime.service.generate(
                        CaseReportRequest(
                            report_id=uuid4(),
                            case_id=case_id,
                            intake_id=intake.intake_id,
                        )
                    )
            finally:
                store.put(source_key, "engineering-file", archived)

            async def verify_report_from_intake():
                server = create_server(repo, "engineer", report_runtime.service)
                request_data = {
                    "report_id": str(uuid4()),
                    "case_id": case_id,
                    "intake_id": str(intake.intake_id),
                }
                response = await server.call_tool(
                    "generar_informe", {"entrada": request_data}
                )
                generated = response.structured_content
                assert generated["engineering"]["selected_run_id"] == str(
                    evidence.run_id
                )
                assert generated["engineering"]["evidence_status"] == "failed"
                assert (
                    generated["handoff"] is None
                )  # A receipt is not an approved handoff.
                phase = next(
                    p
                    for p in generated["metrics"]["phases"]
                    if p["phase"] == "engineering"
                )
                assert phase["process_time_seconds"] == 70
                assert phase["recorded_rework_effort_seconds"] == 10
                report = generated["report"]

                def decision(action):
                    return {
                        "decision_id": str(uuid4()),
                        "version": report["version"],
                        "sha256": report["artifact"]["sha256"],
                        "action": action,
                        "detail": "Confirmado para el informe parcial ficticio",
                    }

                approved = (
                    await server.call_tool(
                        "registrar_decision_informe",
                        {
                            "entrega_id": generated["delivery_id"],
                            "decision": decision("approve"),
                        },
                    )
                ).structured_content
                with pytest.raises(ToolError, match="cerrar"):
                    await server.call_tool(
                        "registrar_decision_informe",
                        {
                            "entrega_id": generated["delivery_id"],
                            "decision": decision("record_presentation"),
                        },
                    )
                content = list(await server.read_resource(approved["pdf_uri"]))[
                    0
                ].content
                text = " ".join(
                    " ".join(
                        p.extract_text() for p in PdfReader(BytesIO(content)).pages
                    ).split()
                )
                for expected in (
                    "INFORME PARCIAL APROBADO",
                    "Fallida informada",
                    "No ejecutada",
                    "Retrabajo",
                    "10.0 s (parcial)",
                    implementation_commit,
                    str(evidence.run_id),
                ):
                    assert expected in text
                source = list(await server.read_resource(approved["sources_uri"]))[
                    0
                ].content
                source = source.encode() if isinstance(source, str) else source
                assert (
                    sha256(source).hexdigest()
                    == approved["report"]["sources"]["sha256"]
                )
                captured = json.loads(source)
                assert (
                    captured["engineering"]["intake"]["input_sha256"]
                    == receipt["intake"]["input_sha256"]
                )
                assert (
                    captured["engineering"]["evidence"][0]["evidence_sha256"]
                    == result["evidence"][0]["evidence_sha256"]
                )
                backup = next(
                    f
                    for f in captured["engineering"]["files"]
                    if f["path"] == "design.md"
                )
                assert (
                    list(await server.read_resource(backup["uri"]))[0].content
                    == original
                )
                output = Path(
                    os.getenv("DELIVERY_TEST_OUTPUT", str(tmp_path / "report-links"))
                )
                output.mkdir(parents=True, exist_ok=True)
                (output / "informe-con-recepcion.pdf").write_bytes(content)
                (output / "fuentes-con-recepcion.json").write_bytes(source)
                early_pdf = repo.artifact(
                    early_request.report_id,
                    early_report["report"]["artifact"]["artifact_id"],
                )
                (output / "informe-sin-corridas.pdf").write_bytes(
                    bytes(early_pdf["content"])
                )
                assert store.get(f"process:{case_id}")["stage"] == 5
                return generated

            generated = asyncio.run(verify_report_from_intake())
            assert generated["engineering"]["upstream_current"]
        finally:
            reopened.close()
            report_runtime.close()
        process.internal(
            case_id,
            "engineering-ready",
            "deliverable.ready",
            revision=1,
            artifact_sha256="f" * 64,
            evidence=["local:fictitious"],
        )
        process.internal(
            case_id,
            "engineering-adjustments",
            "stage.changes_requested",
            revision=1,
            artifact_sha256="f" * 64,
            comment="Cambiar implementación",
        )
        assert not service.get(intake.intake_id)["upstream_current"]
        with pytest.raises(DeliveryConflict, match="iteración"):
            service.record_evidence(
                EngineeringEvidence.model_validate(
                    {**evidence_data, "run_id": str(uuid4())}
                )
            )

        # Continue the handoff journey with a separate isolated case exercising
        # the production metadata branch. All files/approvals/runs remain test
        # doubles; no GitHub operation, Terraform or cloud provider executes.
        final_case = case_id + "-final"
        store.register_project(
            final_case,
            "final-pilot",
            "Datos de prueba del cierre",
            "Empresa de prueba",
            "engineer",
            is_fictitious=False,
        )
        store.put(f"owner:{final_case}", "owner", {"manager_id": "engineer"})
        final_runtime = create_report_runtime(repo.dsn, url, "engineer")
        try:
            final_runtime.service.sources.store.clock = lambda: clock[0]
            final_process = final_runtime.service.process
            final_process.graph.start(
                f"process:{final_case}",
                {
                    **initial_state(final_case, "engineer"),
                    "stage": 3,
                    "status": "awaiting_deliverable",
                },
            )
            final_process.ensure(final_case)
            final_input = EngineeringIntake.model_validate(
                {
                    **input_data,
                    "intake_id": str(uuid4()),
                    "case_id": final_case,
                    "incoming_handoff_id": f"{final_case}:process:2:3",
                }
            )
            for stage, package in (
                (3, final_input.architecture),
                (4, final_input.finops),
            ):
                final_process.internal(
                    final_case,
                    f"ready-{stage}",
                    "deliverable.ready",
                    revision=1,
                    artifact_sha256=final_input.approval_digest(stage),
                    evidence=[package.approval.reference],
                )
                final_process.internal(
                    final_case,
                    package.approval.event_id,
                    "stage.approved",
                    revision=1,
                    artifact_sha256=final_input.approval_digest(stage),
                    evidence=[package.approval.reference],
                    actor=package.approval.actor,
                )
            final_receipt = service.register(final_input)
            successful = []
            for run_number in (124, 125):
                clock[0] += 100
                value = copy.deepcopy(evidence_data)
                value.update(
                    run_id=str(uuid4()),
                    intake_id=str(final_input.intake_id),
                    input_sha256=final_receipt["intake"]["input_sha256"],
                    run_reference=f"https://github.com/{repository_name}/actions/runs/{run_number}",
                )
                for check in value["checks"]:
                    check.update(
                        status="passed",
                        failure_origin=None,
                        started_at=datetime.fromtimestamp(
                            clock[0] - 20, UTC
                        ).isoformat(),
                        ended_at=datetime.fromtimestamp(clock[0] - 10, UTC).isoformat(),
                    )
                parsed = EngineeringEvidence.model_validate(value)
                service.record_evidence(parsed)
                successful.append(parsed)
            release = EngineeringRelease(
                intake_id=final_input.intake_id,
                input_sha256=final_receipt["intake"]["input_sha256"],
                revision=1,
                local_run_id=successful[0].run_id,
                ci_run_id=successful[1].run_id,
                implementation_commit=implementation_commit,
                implementation_tree_sha256=successful[0].implementation_tree_sha256,
                pull_request=f"https://github.com/{repository_name}/pull/3",
                base_branch="main",
                merge_commit="f" * 40,
                review_commit=implementation_commit,
                architect="architect",
                review_reference=f"https://github.com/{repository_name}/pull/3#pullrequestreview-1",
                baseline_verifications=[
                    {
                        "module": m.model_dump(mode="json"),
                        "verification_reference": m.approval_reference,
                    }
                    for m in final_input.modules
                ],
                branch_protection_reference=f"https://github.com/{repository_name}/settings/branches",
                integration_reference=f"https://github.com/{repository_name}/commit/{'f' * 40}",
                compatibility_limits=[
                    "Datos ficticios del recorrido; no acredita compatibilidad real."
                ],
                approval_event_id="engineering-approved",
            )
            with pytest.raises(DeliveryConflict, match="aprobación registrada"):
                service.record_release(release)
            final_process.internal(
                final_case,
                "engineering-final-ready",
                "deliverable.ready",
                revision=1,
                artifact_sha256=release.approval_digest(),
                evidence=[release.review_reference],
            )
            final_process.internal(
                final_case,
                release.approval_event_id,
                "stage.approved",
                revision=1,
                artifact_sha256=release.approval_digest(),
                evidence=[release.review_reference],
                actor="architect",
            )

            async def final_mcp_journey():
                engineering_server = create_engineering_server(service)
                released = (
                    await engineering_server.call_tool(
                        "registrar_entrega_tecnica",
                        {"entrega": release.model_dump(mode="json")},
                    )
                ).structured_content
                assert not released["blockers"]
                assert released["catalog"]["revision"] == 2
                assert service.record_release(release)["release"] == released["release"]
                server = create_server(repo, "engineer", final_runtime.service)
                generated = (
                    await server.call_tool(
                        "generar_informe",
                        {
                            "entrada": {
                                "report_id": str(uuid4()),
                                "case_id": final_case,
                                "intake_id": str(final_input.intake_id),
                            }
                        },
                    )
                ).structured_content
                assert not generated["closure_blockers"]
                report = generated["report"]
                common = {
                    "version": report["version"],
                    "sha256": report["artifact"]["sha256"],
                    "detail": "Confirmación ficticia del recorrido de cierre",
                }
                await server.call_tool(
                    "registrar_decision_informe",
                    {
                        "entrega_id": generated["delivery_id"],
                        "decision": {
                            **common,
                            "decision_id": str(uuid4()),
                            "action": "approve",
                        },
                    },
                )
                presentation = {
                    **common,
                    "decision_id": str(uuid4()),
                    "action": "record_presentation",
                }
                with pytest.raises(ToolError, match="fecha, audiencia"):
                    await server.call_tool(
                        "registrar_decision_informe",
                        {
                            "entrega_id": generated["delivery_id"],
                            "decision": presentation,
                        },
                    )
                presentation["presentation"] = {
                    "presented_at": datetime.now(UTC).isoformat(),
                    "audience": "Dirección de prueba",
                    "reference": "https://example.org/presentation/1",
                }
                from app.persistence.delivery import RunStore

                save = RunStore.save_decision

                def interrupted_save(self, decision_id, decision, *args):
                    if decision["action"] == "record_presentation":
                        raise RuntimeError(
                            "Interrupción después del checkpoint de cierre"
                        )
                    return save(self, decision_id, decision, *args)

                monkeypatch.setattr(RunStore, "save_decision", interrupted_save)
                with pytest.raises(ToolError):
                    await server.call_tool(
                        "registrar_decision_informe",
                        {
                            "entrega_id": generated["delivery_id"],
                            "decision": presentation,
                        },
                    )
                assert store.get(f"process:{final_case}")["status"] == "completed"
                assert (
                    repo.get(generated["delivery_id"])["report"]["status"] == "approved"
                )
                monkeypatch.setattr(RunStore, "save_decision", save)
                recovered_runtime = create_report_runtime(repo.dsn, url, "engineer")
                try:
                    recovered_runtime.service.sources.store.clock = lambda: clock[0]
                    recovered = create_server(
                        repo, "engineer", recovered_runtime.service
                    )
                    closed = (
                        await recovered.call_tool(
                            "registrar_decision_informe",
                            {
                                "entrega_id": generated["delivery_id"],
                                "decision": presentation,
                            },
                        )
                    ).structured_content
                    assert closed["report"]["status"] == "closed"
                    repeated = (
                        await recovered.call_tool(
                            "registrar_decision_informe",
                            {
                                "entrega_id": generated["delivery_id"],
                                "decision": presentation,
                            },
                        )
                    ).structured_content
                    assert repeated["report"] == closed["report"]
                    assert len(repo.report_decisions(generated["delivery_id"])) == 2
                    content = list(await recovered.read_resource(closed["pdf_uri"]))[
                        0
                    ].content
                    text = " ".join(
                        p.extract_text() for p in PdfReader(BytesIO(content)).pages
                    )
                    assert "INFORME DEFINITIVO APROBADO" in text
                    output = Path(
                        os.getenv(
                            "DELIVERY_TEST_OUTPUT", str(tmp_path / "report-links")
                        )
                    )
                    output.mkdir(parents=True, exist_ok=True)
                    (output / "informe-definitivo-prueba.pdf").write_bytes(content)
                finally:
                    recovered_runtime.close()

            asyncio.run(final_mcp_journey())
        finally:
            final_runtime.close()
    finally:
        runtime.close()


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
    monkeypatch.setenv("WORKFLOW_DATABASE_URL", workflow_url)
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
