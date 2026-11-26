"""Opt-in local demo API. Does not initialize databases during import."""

import os
from contextlib import ExitStack
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response

from app.delivery.models import CaseReportRequest, DemoRequest, ReportDecision
from app.delivery.report import ReportAccessDenied, require_report_owner
from app.delivery.review import ReportReview, configured_manager
from app.delivery.workflow import DeliveryWorkflow, public_result
from app.persistence.delivery import DeliveryBusy, DeliveryConflict, PostgresRepository
from app.persistence.locking import Busy

router = APIRouter(prefix="/delivery", tags=["Entrega 1 local"])
review_router = APIRouter(prefix="/delivery", tags=["Revisión ejecutiva local"])


@lru_cache
def configured_repository():
    dsn = os.getenv("DELIVERY_DATABASE_URL")
    if not dsn:
        raise HTTPException(
            503, "Configurar DELIVERY_DATABASE_URL e inicializar la base de datos local"
        )
    return PostgresRepository(dsn)


def repository():
    return configured_repository()


Repository = Annotated[PostgresRepository, Depends(repository)]


def case_report_service():
    from app.bootstrap import create_report_runtime

    try:
        runtime = create_report_runtime(
            os.getenv("DELIVERY_DATABASE_URL", ""),
            os.getenv("WORKFLOW_DATABASE_URL"),
            configured_manager(),
            checkpoint_url=os.getenv("WORKFLOW_CHECKPOINT_URL") or None,
        )
        if runtime.service is None:
            runtime.close()
            raise ValueError("Configurar WORKFLOW_DATABASE_URL")
    except ValueError as error:
        raise HTTPException(503, str(error)) from error
    try:
        yield runtime.service
    finally:
        runtime.close()


@review_router.post("/reports")
def create_case_report(
    request: CaseReportRequest, service=Depends(case_report_service)
):
    try:
        return service.generate(request)
    except (DeliveryConflict, DeliveryBusy, Busy) as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except psycopg.Error as error:
        raise HTTPException(503, "Persistencia de informe no disponible") from error


@router.post("/runs")
def create_run(request: DemoRequest, repo: Repository):
    try:
        return DeliveryWorkflow(repo).run(request)
    except (DeliveryConflict, DeliveryBusy) as error:
        raise HTTPException(409, str(error)) from error
    except psycopg.Error as error:
        raise HTTPException(
            503, "Persistencia no disponible; revisar configuración y migración"
        ) from error
    except Exception as error:
        raise HTTPException(
            500,
            "No se completó la entrega; puede reintentarse con el mismo identificador",
        ) from error


@router.get("/runs/{delivery_id}")
def get_run(delivery_id: UUID, repo: Repository):
    try:
        row = repo.get(delivery_id)
    except psycopg.Error as error:
        raise HTTPException(503, "Persistencia no disponible") from error
    if not row:
        raise HTTPException(404, "Entrega no encontrada")
    try:
        require_report_owner(row, os.getenv("DELIVERY_ENGAGEMENT_MANAGER"))
    except ValueError as error:
        raise HTTPException(403, str(error)) from error
    return public_result(row)


@router.get("/runs/{delivery_id}/artifacts/{artifact_id}")
def get_artifact(delivery_id: UUID, artifact_id: UUID, repo: Repository):
    try:
        row = repo.get(delivery_id)
        if row:
            require_report_owner(row, os.getenv("DELIVERY_ENGAGEMENT_MANAGER"))
        artifact = repo.artifact(delivery_id, artifact_id)
    except ValueError as error:
        raise HTTPException(403, str(error)) from error
    except psycopg.Error as error:
        raise HTTPException(503, "Persistencia no disponible") from error
    if not artifact:
        raise HTTPException(404, "Archivo no encontrado en esta entrega")
    return Response(
        bytes(artifact["content"]),
        media_type=artifact["media_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{artifact["filename"]}"',
            "ETag": f'"{artifact["sha256"]}"',
            "Cache-Control": "no-store",
        },
    )


@review_router.get("/runs/{delivery_id}/report")
def get_report(delivery_id: UUID, repo: Repository):
    try:
        return ReportReview(repo, os.getenv("DELIVERY_ENGAGEMENT_MANAGER")).get(
            delivery_id
        )
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(403, str(error)) from error
    except psycopg.Error as error:
        raise HTTPException(503, "Persistencia de revisión no disponible") from error


@review_router.post("/runs/{delivery_id}/report/decisions")
def decide_report(delivery_id: UUID, decision: ReportDecision, repo: Repository):
    try:
        operator = configured_manager()
        with ExitStack() as resources:
            service = None
            row = repo.get(delivery_id)
            if (
                row
                and row["request"].get("kind") == "case_report"
                and os.getenv("WORKFLOW_DATABASE_URL")
            ):
                from app.bootstrap import create_report_runtime

                runtime = create_report_runtime(
                    repo.dsn,
                    os.environ["WORKFLOW_DATABASE_URL"],
                    operator,
                    checkpoint_url=os.getenv("WORKFLOW_CHECKPOINT_URL") or None,
                )
                resources.callback(runtime.close)
                service = runtime.service
            return ReportReview(repo, operator, service).decide(
                delivery_id, decision, operator
            )
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except (DeliveryConflict, DeliveryBusy, Busy) as error:
        raise HTTPException(409, str(error)) from error
    except ReportAccessDenied as error:
        raise HTTPException(403, str(error)) from error
    except (psycopg.Error, ValueError) as error:
        raise HTTPException(
            503, "Configurar operador y persistencia de revisión"
        ) from error
