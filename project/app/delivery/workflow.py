"""Two business agents orchestrated by LangGraph; no cloud/LLM API calls."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import TypedDict
from uuid import uuid5

from app.delivery.metrics import calculate_metrics
from app.delivery.models import (
    Activity,
    Check,
    DemoRequest,
    EngineeringHandoff,
    PhaseTiming,
    ReportDraft,
)
from app.delivery.pdf_report import render_pdf
from app.delivery.repository import DeliveryConflict, PostgresRepository
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context


def utcnow():
    return datetime.now(UTC)


class WorkflowState(TypedDict):
    engineering_ready: bool


def timing(phase, start, end):
    return PhaseTiming(
        phase=phase,
        provenance="real",
        accepted_at=start,
        handed_off_at=end,
        activities=[
            Activity(
                actor_id=f"agent-{phase}",
                actor_type="agent",
                kind="work",
                started_at=start,
                ended_at=end,
            )
        ],
    )


def terraform_files(request: DemoRequest) -> dict[str, bytes]:
    architecture = request.architecture
    source = f"git::{architecture.baseline.repository}//aws/s3?ref={architecture.baseline.commit}"
    main = f'''# DEMO: baseline pendiente de aprobación. No desplegar sin revisión.
terraform {{
  required_version = ">= 1.9.0, < 2.0.0"
  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = ">= 6.71.0, < 7.0.0"
    }}
  }}
}}

provider "aws" {{
  region = var.region
}}

module "documents" {{
  source = "{source}"

  bucket_name = var.bucket_name
  kms_key_arn = var.kms_key_arn
  tags = {{
    Project     = "{request.project_id}"
    Environment = "{architecture.environment}"
    Owner       = "demo"
    CostCenter  = "PSWE07"
  }}
}}

output "bucket_id" {{
  value = module.documents.bucket_id
}}
'''
    variables = """variable "region" {
  type = string
}

variable "bucket_name" {
  type = string
}

variable "kms_key_arn" {
  type = string
}
"""
    values = {
        "region": architecture.region,
        "bucket_name": architecture.bucket_name,
        "kms_key_arn": architecture.kms_key_arn,
    }
    example = (
        "# Valores simulados. No constituyen accesos ni recursos existentes.\n"
        + "\n".join(f"{key} = {json.dumps(value)}" for key, value in values.items())
        + "\n"
    )
    return {
        "main.tf": main.encode(),
        "variables.tf": variables.encode(),
        "terraform.tfvars.example": example.encode(),
    }


class DeliveryWorkflow:
    def __init__(self, repository: PostgresRepository, pdf_renderer=render_pdf):
        self.repository, self.pdf_renderer = repository, pdf_renderer

    def run(self, request: DemoRequest):
        payload = request.model_dump(mode="json")
        digest = sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()
        with self.repository.locked(request.delivery_id) as store:
            existing = store.get()
            if existing and existing["request_hash"] != digest:
                raise DeliveryConflict(
                    "El identificador ya corresponde a otra entrada; utilizar uno nuevo para otra versión"
                )
            if not existing:
                store.create(payload, digest)

            def engineering(_state):
                if store.get()["handoff"]:
                    return {"engineering_ready": True}
                start = utcnow()
                issues = []
                if (
                    request.finops.architecture_revision
                    != request.architecture.source.revision
                ):
                    issues.append("FinOps corresponde a otra revisión de arquitectura")
                if request.finops.estimate_monthly > request.finops.budget_monthly:
                    issues.append("La estimación supera el presupuesto del ejemplo")
                if (
                    request.architecture.kms_key_arn.split(":")[3]
                    != request.architecture.region
                ):
                    issues.append("La región KMS no coincide con la arquitectura")
                if issues:
                    store.blocked("; ".join(issues))
                    return {"engineering_ready": False}
                with store.conn.transaction():
                    artifacts = [
                        store.put_artifact(name, "text/plain; charset=utf-8", content)
                        for name, content in terraform_files(request).items()
                    ]
                    handoff = EngineeringHandoff(
                        handoff_id=uuid5(request.delivery_id, "engineering-v1"),
                        delivery_id=request.delivery_id,
                        project_id=request.project_id,
                        created_at=utcnow(),
                        summary="Composición S3 preparada y coherencia de los insumos comprobada para una demostración local de ingeniería e informe ejecutivo.",
                        inputs={
                            "architecture": request.architecture.model_dump(
                                mode="json"
                            ),
                            "finops": request.finops.source.model_dump(mode="json"),
                        },
                        costs=request.finops,
                        checks=[
                            Check(
                                name="Coherencia de entradas",
                                status="passed",
                                provenance="real",
                                detail="Se verificaron revisión de arquitectura, presupuesto y región KMS sobre datos simulados.",
                            ),
                            Check(
                                name="Composición Terraform",
                                status="passed",
                                provenance="real",
                                detail="Archivos generados con referencia fija al catálogo; baseline pendiente de aprobación.",
                            ),
                            Check(
                                name="Terraform y seguridad",
                                status="not_run",
                                provenance="real",
                                detail="No se ejecutaron fmt/validate, pruebas Terraform, Trivy ni políticas del diseño.",
                            ),
                            Check(
                                name="Despliegue local / AWS",
                                status="not_run",
                                provenance="real",
                                detail="No se desplegaron recursos ni se utilizaron credenciales AWS.",
                            ),
                        ],
                        artifacts=artifacts,
                        timings=[
                            *request.upstream_timings,
                            timing("engineering", start, utcnow()),
                        ],
                        pending_items=[
                            "Sustituir arquitectura y FinOps simulados por entregas reales aprobadas. Responsable: Arquitectura / FinOps.",
                            "Obtener revisión del baseline y confirmar KMS y demás dependencias. Responsable: Arquitectura.",
                            "Ejecutar Terraform, seguridad, políticas y el despliegue local acordado. Responsable: Ingeniería.",
                            "Publicar el PR técnico y obtener revisión e integración autorizadas. Responsable: Ingeniería / Arquitectura.",
                            "Conectar MCP y completar ajustes, aprobación del informe y cierre. Responsable: Engagement Manager / backend.",
                        ],
                    )
                    store.save_handoff(handoff.model_dump(mode="json"))
                return {"engineering_ready": True}

            def report(_state):
                row = store.get()
                if row["report"]:
                    return {}
                start = utcnow()
                handoff = EngineeringHandoff.model_validate(row["handoff"])
                metrics = calculate_metrics(handoff.timings)
                pdf = self.pdf_renderer(request, handoff, metrics)
                with store.conn.transaction():
                    artifact = store.put_artifact(
                        "informe-ejecutivo-v1.pdf", "application/pdf", pdf
                    )
                    draft = ReportDraft(
                        report_id=uuid5(request.delivery_id, "report-v1"),
                        handoff_id=handoff.handoff_id,
                        artifact=artifact,
                        metrics=metrics,
                        pending_items=handoff.pending_items,
                    )
                    store.save_report(
                        draft.model_dump(mode="json"),
                        timing("report", start, utcnow()).model_dump(mode="json"),
                    )
                return {}

            graph = StateGraph(WorkflowState)
            graph.add_node("engineering_agent", engineering)
            graph.add_node("executive_report_agent", report)
            graph.add_edge(START, "engineering_agent")
            graph.add_conditional_edges(
                "engineering_agent",
                lambda state: (
                    "executive_report_agent" if state["engineering_ready"] else END
                ),
            )
            graph.add_edge("executive_report_agent", END)
            try:
                # No implicit LangSmith networking if the host has tracing enabled.
                with tracing_context(enabled=False):
                    graph.compile().invoke({"engineering_ready": False})
            except Exception:
                store.failed()
                raise
            return public_result(store.get())


def public_result(row):
    handoff = row["handoff"]
    timings = (
        [PhaseTiming.model_validate(t) for t in handoff["timings"]] if handoff else []
    )
    if row["report_timing"]:
        timings.append(PhaseTiming.model_validate(row["report_timing"]))
    return {
        "delivery_id": str(row["delivery_id"]),
        "status": row["status"],
        "handoff": handoff,
        "report": row["report"],
        "error": row["error"],
        "metrics": calculate_metrics(timings),
    }
