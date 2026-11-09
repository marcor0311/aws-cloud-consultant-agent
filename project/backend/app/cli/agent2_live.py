"""Explicit live activation: PostgreSQL LangGraph -> ChatGPT OAuth -> MCP -> GitHub."""

import argparse
import json
import os
import re
import uuid
from contextlib import ExitStack

import httpx

from app.cli.meeting_assistant import login, session_directory
from app.core.config import PROJECT_DIR, load_environment
from app.integrations.ai.oauth import DemoError
from app.integrations.ai.plan_session import PlanSession
from app.integrations.opening_mcp_client import OpeningMCPClient
from app.persistence.checkpoints import open_checkpointer
from app.persistence.project_opening import ProjectOpeningRepository
from app.persistence.workflow import WorkflowStore
from app.project_opening.live_graph import build_live_opening_graph


def resolve_case(store, case_id, execution_id):
    previous = store.get("agent2-live:" + execution_id)
    if previous:
        if case_id and case_id != previous["case_id"]:
            raise ValueError("El execution-id ya corresponde a otro expediente.")
        return previous["case_id"]
    if case_id:
        return case_id
    return next(
        (
            record["case_id"]
            for record in ProjectOpeningRepository(store).queue()
            if record["status"] != "delivered"
        ),
        None,
    )


def execute_live(
    store,
    saver,
    mcp,
    session,
    *,
    case_id,
    model,
    execution_id,
    allow_inference,
    mock_board=False,
):
    if not allow_inference:
        raise ValueError("La ejecución real requiere --allow-inference.")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,120}", execution_id):
        raise ValueError("execution-id inválido.")
    key = "agent2-live:" + execution_id
    thread = "agent2-live:" + case_id + ":" + execution_id
    identity = {
        "case_id": case_id,
        "model": model,
        "execution_id": execution_id,
        "mock_board": mock_board,
    }

    def infer(state):
        journal = store.get(key + ":inference")
        if journal:
            if journal["status"] == "completed":
                return journal["result"]
            raise ValueError(
                "La inferencia anterior quedó sin confirmación. No se repite ni consume automáticamente; revisar y usar otro execution-id para autorizar un nuevo intento."
            )
        store.put(
            key + ":inference", "live-inference", {"status": "started", **identity}
        )
        result = session.opening_tool_call(
            model, state["preflight"], allow_inference=True
        )
        store.put(
            key + ":inference",
            "live-inference",
            {"status": "completed", **identity, "result": result},
        )
        store.event(
            key + ":inference",
            case_id,
            "opening.oauth_inference_completed",
            {**identity, **result},
        )
        return result

    with store.lock(key):
        previous = store.get(key)
        if previous and any(previous[k] != identity[k] for k in identity):
            raise ValueError("El execution-id ya pertenece a otro caso o modelo.")
        if not previous:
            store.put(key, "live-opening", {**identity, "activated_at": store.clock()})
        graph = build_live_opening_graph(saver, mcp, infer)
        config = {"configurable": {"thread_id": thread}}
        snapshot = graph.get_state(config)
        if not snapshot.values:
            state = graph.invoke(identity, config)
        elif snapshot.next:
            state = graph.invoke(None, config)
        else:
            state = snapshot.values
        delivery = state["delivery"]["result"]
        if delivery["status"] != "delivered":
            raise ValueError("MCP no confirmó la entrega del proyecto.")
        report = {
            **identity,
            "status": "delivered",
            "orchestration": "LangGraph",
            "mode": "live",
            "inference": state["inference"],
            "mcp": {
                k: state["delivery"][k]
                for k in ("server", "transport", "protocol_version")
            },
            "repository": delivery["repository"],
            "commit": delivery["commit"],
            "issue": delivery["issue"],
        }
        store.put(key + ":report", "live-opening-report", report)
        store.event(
            key + ":delivered", case_id, "opening.live_execution_delivered", report
        )
        return report


def main(argv=None):
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        help="Expediente; por defecto toma el siguiente pendiente de PostgreSQL.",
    )
    parser.add_argument("--model", default=os.getenv("MEETING_ASSISTANT_MODEL", "auto"))
    parser.add_argument("--execution-id", default=uuid.uuid4().hex)
    parser.add_argument("--allow-inference", action="store_true")
    parser.add_argument(
        "--mock-board",
        action="store_true",
        help="Votos simulados autorizados para este caso ficticio; GitHub e inferencia son reales.",
    )
    args = parser.parse_args(argv)
    if not args.allow_inference:
        parser.error("Requiere --allow-inference: consume el plan y publica en GitHub.")
    url = os.getenv("WORKFLOW_DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        parser.error("Configurar PostgreSQL en WORKFLOW_DATABASE_URL.")
    with ExitStack() as resources:
        store = WorkflowStore(url.replace("postgresql://", "postgresql+psycopg://", 1))
        resources.callback(store.engine.dispose)
        args.case = resolve_case(store, args.case, args.execution_id)
        if args.case is None:
            print(
                json.dumps(
                    {
                        "status": "idle",
                        "reason": "No hay aperturas pendientes en PostgreSQL.",
                    },
                    ensure_ascii=False,
                )
            )
            return
        print(
            f"Ejecución {args.execution_id}; expediente {args.case}: LangGraph → ChatGPT OAuth → MCP → GitHub",
            flush=True,
        )
        saver = resources.enter_context(
            open_checkpointer(url.replace("postgresql+psycopg://", "postgresql://", 1))
        )
        client = resources.enter_context(
            httpx.Client(timeout=120, follow_redirects=False)
        )
        session = PlanSession(
            client, session_directory(), "http://127.0.0.1:8767/auth/callback"
        )
        if not session.access_token:
            login(session, 8767)
        mcp = OpeningMCPClient(
            mock_board_case=args.case if args.mock_board else "",
            execution_id=args.execution_id,
        )
        report = execute_live(
            store,
            saver,
            mcp,
            session,
            case_id=args.case,
            model=args.model,
            execution_id=args.execution_id,
            allow_inference=True,
            mock_board=args.mock_board,
        )
        path = (
            PROJECT_DIR
            / "generated/meeting-assistant"
            / ("live-" + args.execution_id + ".json")
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(
            json.dumps(
                {**report, "report_file": str(path)}, ensure_ascii=False, indent=2
            )
        )


if __name__ == "__main__":
    try:
        main()
    except (DemoError, ValueError) as error:
        raise SystemExit(str(error)) from None
