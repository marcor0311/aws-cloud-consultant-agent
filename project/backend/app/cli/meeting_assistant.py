"""Agent 2: PostgreSQL queue, recoverable GitHub opening and ChatGPT plan sign-in."""

import argparse
import json
import os
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from app.bootstrap import create_opening_runtime
from app.cli.preparation_documents import reconcile_approved_preparation
from app.core.config import PROJECT_DIR, load_environment, private_path
from app.integrations.ai.oauth import DemoError
from app.integrations.ai.plan_session import PlanSession
from app.integrations.errors import ProviderError
from app.integrations.opening_preview import PreviewGitHub, simulate_board_approval
from app.persistence.locking import Busy
from app.project_opening.mcp import create_server

ROOT = PROJECT_DIR.parent
AGENT = PROJECT_DIR / "agents/2. meeting assistant"


def session_directory():
    return private_path("chatgpt/meeting-assistant")


SOURCE = ROOT / "insumos temporales de agente 1"


def login(connection, port):
    class Callback(BaseHTTPRequestHandler):
        completed = False

        def do_GET(self):
            url = urlparse(self.path)
            if url.path != "/auth/callback":
                self.send_error(404)
                return
            try:
                connection.finish({k: v[0] for k, v in parse_qs(url.query).items()})
                self.completed = Callback.completed = True
                message = "Cuenta conectada. Podés cerrar esta ventana."
                status = 200
            except (DemoError, httpx.HTTPError, ValueError):
                message = "No se pudo completar el inicio de sesión. Reintentá desde la terminal."
                status = 400
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(message.encode())

        def log_message(self, *_args):
            pass  # OAuth callback URLs contain a one-time code.

    with HTTPServer(("127.0.0.1", port), Callback) as server:
        server.timeout = 1
        webbrowser.open(connection.authorize())
        print(
            "Continue with ChatGPT: completá el inicio de sesión en el navegador.",
            flush=True,
        )
        deadline = time.monotonic() + 600
        while not Callback.completed and time.monotonic() < deadline:
            server.handle_request()
        if not Callback.completed:
            raise DemoError(
                "El inicio de sesión no se completó dentro de diez minutos."
            )
        return {"connected": True, "authentication": "chatgpt_plan_oauth"}


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register")
    register.add_argument("--request", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--case", required=True)
    audit = commands.add_parser("audit")
    audit.add_argument("--case", required=True)
    commands.add_parser("queue")
    commands.add_parser("next")
    mcp = commands.add_parser("mcp")
    mcp.add_argument("--mock-board-for-case", default="")
    mcp.add_argument("--live-execution-id", default="")
    preview = commands.add_parser("preview")
    preview.add_argument(
        "--request",
        type=Path,
        default=PROJECT_DIR / "backend/fixtures/nike-lindora-stuart/opening.json",
    )
    auth = commands.add_parser("login")
    auth.add_argument("--port", type=int, default=8767)
    commands.add_parser("logout")
    draft = commands.add_parser("draft")
    draft.add_argument("--model", required=True)
    draft.add_argument("--transcript", type=Path, required=True)
    draft.add_argument("--output", type=Path, required=True)
    draft.add_argument("--allow-inference", action="store_true")
    args = parser.parse_args()
    if args.command in {"login", "logout", "draft"}:
        with httpx.Client(timeout=120, follow_redirects=False) as client:
            port = getattr(args, "port", 8767)
            session = PlanSession(
                client, session_directory(), f"http://127.0.0.1:{port}/auth/callback"
            )
            if args.command == "login":
                result = login(session, port)
            elif args.command == "logout":
                result = session.sign_out()
            else:
                if not args.allow_inference:
                    parser.error(
                        "La inferencia real requiere --allow-inference para esta ejecución."
                    )
                work = session.draft_work(
                    args.model,
                    args.transcript.read_text(),
                    allow_inference=args.allow_inference,
                )
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(work.model_dump_json(indent=2))
                result = {"status": "awaiting_review", "output": str(args.output)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    provider = None
    database_url = os.getenv("WORKFLOW_DATABASE_URL", "")
    if args.command == "preview":
        database_url = os.getenv("MEETING_ASSISTANT_PREVIEW_DATABASE_URL", "")
        if not database_url or database_url == os.getenv("WORKFLOW_DATABASE_URL", ""):
            parser.error(
                "Configurar MEETING_ASSISTANT_PREVIEW_DATABASE_URL aislada de la base activa."
            )
        request = json.loads(args.request.read_text())
        request["case_id"] = "preview-" + request["case_id"]
        request["is_fictitious"] = True
        provider = PreviewGitHub(
            PROJECT_DIR / "generated/meeting-assistant" / request["case_id"]
        )
        reconcile_approved_preparation(database_url, request)
    runtime = create_opening_runtime(
        database_url,
        SOURCE,
        AGENT / "templates/architecture.md",
        github=provider,
        allow_simulated_board=args.command == "preview",
        simulated_board_case=getattr(args, "mock_board_for_case", ""),
    )
    try:
        service = runtime.service
        if args.command == "mcp":
            if args.mock_board_for_case:
                if not args.live_execution_id:
                    raise ValueError(
                        "La votación mock para GitHub real requiere una ejecución identificada."
                    )
                record = service.get(args.mock_board_for_case)
                if not record["is_fictitious"]:
                    raise ValueError(
                        "La votación mock para GitHub real requiere un caso ficticio."
                    )
                current = runtime.board.repository.latest(args.mock_board_for_case)
                if current and not current["is_simulated"]:
                    raise ValueError(
                        "No se reemplaza una votación real con votos mock."
                    )
                runtime.store.event(
                    "live-mock-board:" + args.live_execution_id,
                    args.mock_board_for_case,
                    "opening.mock_board_live_authorized",
                    {
                        "execution_id": args.live_execution_id,
                        "actor": record["approved_by"],
                        "is_simulated": True,
                        "authorization": "operator activated live --mock-board for this fictitious case",
                    },
                )
                simulate_board_approval(runtime.board, args.mock_board_for_case)
            create_server(
                service,
                (AGENT / "prompts/assistant.txt").read_text(),
                board=runtime.board,
            ).run(transport="stdio")
            return
        if args.command == "preview":
            service.register(request)
            ballot = simulate_board_approval(runtime.board, request["case_id"])
            result = service.run(request["case_id"])
            report = {
                "mode": "preview",
                "orchestration": "LangGraph",
                "persistence": "PostgreSQL",
                "external_github_calls": 0,
                "real_inference_calls": 0,
                "external_slack_calls": 0,
                "board_vote": {
                    "is_simulated": True,
                    "approved": len(ballot["votes"]),
                    "members": len(ballot["members"]),
                    "certificate_sha256": ballot["certificate"]["digest"],
                },
                "case_id": request["case_id"],
                "status": result["status"],
                "steps_executed_this_run": provider.calls,
                "handoffs": runtime.store.case_handoffs(request["case_id"]),
                "directory": str(provider.directory),
            }
            provider.save("run-report.json", report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        if args.command == "register":
            result = service.register(json.loads(args.request.read_text()))
        elif args.command == "queue":
            result = service.queue()
        elif args.command == "next":
            result = service.run_next()
        elif args.command == "audit":
            result = service.audit(args.case)
        else:
            result = service.run(args.case)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        runtime.close()


if __name__ == "__main__":
    try:
        main()
    except (DemoError, ProviderError, Busy, ValueError) as error:
        raise SystemExit(str(error)) from None
