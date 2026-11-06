"""Opt-in local demo API. Does not initialize databases during import."""

import os
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import psycopg
from app.delivery.models import DemoRequest
from app.delivery.repository import DeliveryBusy, DeliveryConflict, PostgresRepository
from app.delivery.workflow import DeliveryWorkflow, public_result
from fastapi import APIRouter, Depends, HTTPException, Response

router = APIRouter(prefix="/delivery", tags=["Entrega 1 local"])


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
    return public_result(row)


@router.get("/runs/{delivery_id}/artifacts/{artifact_id}")
def get_artifact(delivery_id: UUID, artifact_id: UUID, repo: Repository):
    try:
        artifact = repo.artifact(delivery_id, artifact_id)
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
