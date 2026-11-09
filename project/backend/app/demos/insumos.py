"""Offline scripted preparation; fixture changes must be reviewed explicitly."""

import os
from pathlib import Path
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver

from app.integrations.langgraph import LangGraphExecution
from app.preparation.graph import build_graph
from app.preparation.insumos import MeetingInsumos, MeetingTranscript
from app.preparation.service import PreparationService

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures/nike-lindora-stuart"


def prepare_mock(directory=FIXTURE):
    directory = Path(directory)
    transcript = MeetingTranscript.model_validate_json(
        (directory / "transcript.json").read_text()
    )
    content = MeetingInsumos.model_validate_json(
        (directory / "content.json").read_text()
    )
    content.validate_transcript(transcript)
    if not transcript.is_mock:
        raise ValueError("Este proveedor guionado solo acepta el escenario ficticio.")

    def scripted_drafter(state):
        if state["transcript"] != transcript.as_text():
            raise ValueError("El mock no puede preparar otra transcripción.")
        return content.executive_package(transcript)

    with patch.dict(
        os.environ, {"LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}
    ):
        graph = LangGraphExecution(
            build_graph(InMemorySaver(), lambda _query: [], scripted_drafter)
        )
        service = PreparationService(graph)
        result = service.start(
            transcript.id,
            "mock-meeting-ended",
            transcript.as_text(),
            transcript.project_name,
        )
    if result["state"]["status"] != "awaiting_review":
        raise ValueError("La preparación debe quedar pendiente de revisión humana.")
    return transcript, content, result
