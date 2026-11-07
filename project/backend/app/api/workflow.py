"""Authenticated ingestion and manager operations; external events are queued durably."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_runtime, require_manager
from app.workflow.runtime import WorkflowRuntime
from app.workflow.schemas import ProcessEvent

router = APIRouter(tags=["Flujo de reuniones"])
Runtime = Annotated[WorkflowRuntime, Depends(get_runtime)]


@router.get("/workflow/cases", dependencies=[Depends(require_manager)])
def cases(runtime: Runtime):
    return runtime.owned_cases()


@router.get("/workflow/cases/{case_id}", dependencies=[Depends(require_manager)])
def case(case_id: str, runtime: Runtime):
    try:
        return runtime.service.get(case_id)
    except ValueError as error:
        raise HTTPException(404, str(error)) from None


@router.get(
    "/workflow/cases/{case_id}/process", dependencies=[Depends(require_manager)]
)
def process(case_id: str, runtime: Runtime):
    try:
        return runtime.process.get(case_id)
    except ValueError as error:
        raise HTTPException(404, str(error)) from None


@router.post(
    "/workflow/cases/{case_id}/process/events",
    dependencies=[Depends(require_manager)],
    status_code=202,
)
def process_event(case_id: str, payload: ProcessEvent, runtime: Runtime):
    try:
        return runtime.process.submit(case_id, payload.model_dump())
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
