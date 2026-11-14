"""Actual agent 1 MCP handshake and tool invocation, offline."""

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from livekit import api, rtc
from livekit.agents import AgentSession, llm
from livekit.agents.testing import fake_job_context

from demos.voice import ScriptedLLM
from src import agent
from src.tools.advisor_transfer import NEXT_STEP, OFFER


async def test_mcp_subprocess_starts_from_the_agent_root(monkeypatch):
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.tools.calendar_mcp"],
        cwd=str(agent.PROJECT_DIR),
    )
    async with (
        stdio_client(parameters) as (reader, writer),
        ClientSession(reader, writer) as session,
    ):
        await session.initialize()
        listed = await session.list_tools()
        names = {tool.name for tool in listed.tools}
        assert names == {
            "preparar_confirmacion_cliente",
            "iniciar_verificacion_cliente",
            "validar_codigo_correo",
            "reenviar_codigo_correo",
            "consultar_horarios",
            "agendar_reunion",
            "buscar_reuniones",
            "reagendar_reunion",
            "cancelar_reunion",
        }
        result = await session.call_tool(
            "preparar_confirmacion_cliente",
            {
                "codigo_transcrito": "India Oscar Alfa Alfa cero cero uno dos",
            },
        )
        assert not result.is_error
        payload = json.loads(result.content[0].text)
        assert payload["codigo_normalizado"] == "IOAA-0012"
        blocked = await session.call_tool("consultar_horarios", {})
        assert blocked.is_error  # A client code alone never authorizes Calendar.

    # Continue this integration journey through the real SDK, MCP subprocess and
    # local HTTP boundary. Only the backend response and SIP transport are mocked.
    requests = []

    class Backend(BaseHTTPRequestHandler):
        registration = "not_registered"

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, payload))
            result = {"status": "closed"}
            if self.path.endswith("/start"):
                result = {"status": self.registration}
                if self.registration == "code_sent":
                    result["challenge_id"] = "offline-challenge-for-this-call-only"
            elif self.path.endswith("/verify"):
                result = {"status": "verified", "email": "contact@example.invalid"}
            elif self.path.endswith("/authorize"):
                result = {"status": "not_enabled"}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        def log_message(self, *_):
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv(
        "CALENDAR_ACCESS_URL",
        f"http://127.0.0.1:{backend.server_port}/api/calendar-access",
    )
    # Reserved fictional NANP number; no private configuration is read by the test.
    monkeypatch.setenv("CALENDAR_ADVISOR_TRANSFER_E164", "+12025550100")
    monkeypatch.setenv("CALENDAR_ADVISOR_TRANSFER_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("CALENDAR_ASSISTANT_MODE", "mock")

    @asynccontextmanager
    async def phone_session():
        room = Mock()
        room.name = "offline-active-call"
        room.remote_participants = {
            "caller": SimpleNamespace(
                identity="sip-caller-assigned-at-dispatch",
                kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
            )
        }
        with fake_job_context(room=room) as job:
            refer = AsyncMock()
            job.api = SimpleNamespace(
                sip=SimpleNamespace(transfer_sip_participant=refer)
            )
            job.shutdown = Mock()
            job.delete_room = AsyncMock()
            job.add_shutdown_callback = Mock()
            model = ScriptedLLM(clock_tick=lambda: None)
            async with AgentSession() as session:
                closed = asyncio.Event()
                session.on("close", lambda _: closed.set())
                await session.start(
                    agent=agent.Assistant(llm_model=model), record=False
                )
                # Measure callbacks added by the call flow after SDK startup.
                job.add_shutdown_callback.reset_mock()

                async def turn(user, tool, arguments=None, answer=None):
                    model.prepare(answer, tool, arguments)
                    await asyncio.wait_for(session.run(user_input=user), timeout=15)
                    assert not model.responses

                yield session, turn, refer, closed, job

    def said(session):
        return [
            item.text_content
            for item in session.history.items
            if isinstance(item, llm.ChatMessage) and item.role == "assistant"
        ]

    async def registration_offer(session, turn, refer):
        await turn(
            "Sí, confirmó mi código; quiero continuar.",
            "iniciar_verificacion_cliente",
            {"codigo_cliente": "IOAA-0012"},
        )
        assert OFFER in said(session)
        refer.assert_not_awaited()

    try:
        # A refusal must finish the management without a REFER or calendar access.
        async with phone_session() as (session, turn, refer, closed, job):
            await registration_offer(session, turn, refer)
            await turn(
                "No, prefiero contactar después.",
                "transferir_a_asesor",
                {"confirmacion_usuario": False},
            )
            refer.assert_not_awaited()
            assert NEXT_STEP in said(session)
            await turn("Eso es todo, adiós.", "end_call")
            await asyncio.wait_for(closed.wait(), timeout=5)
            job.shutdown.assert_called_once()

        # A disabled record offers the same assistance without exposing its data.
        Backend.registration = "not_enabled"
        async with phone_session() as (session, turn, refer, closed, _job):
            refer.side_effect = api.ServerError(
                "canceled", "provider-private-details", status=408
            )
            await registration_offer(session, turn, refer)
            await turn(
                "Sí, comuníqueme con un asesor, por favor.",
                "transferir_a_asesor",
                {"confirmacion_usuario": True},
            )
            request = refer.await_args.args[0]
            assert request.room_name == "offline-active-call"
            assert request.participant_identity == "sip-caller-assigned-at-dispatch"
            assert request.transfer_to == "tel:+12025550100"
            assert request.ringing_timeout.seconds == 10
            assert refer.await_args.kwargs["timeout"] > 10
            assert any("no contestó" in text for text in said(session))
            assert not closed.is_set()
            # No retry after a failure, even if the model proposes one again.
            await turn(
                "Vuelva a intentarlo.",
                "transferir_a_asesor",
                {"confirmacion_usuario": True},
                answer="No puedo volver a intentar la transferencia. Puede contactar a Stuart.",
            )
            refer.assert_awaited_once()
            await turn("Contactaré a Stuart. Hasta luego.", "end_call")
            await asyncio.wait_for(closed.wait(), timeout=5)

        # Disabled during authorization after OTP: still no Calendar access, and
        # provider rejection resumes the call without exposing backend/provider data.
        Backend.registration = "code_sent"
        async with phone_session() as (session, turn, refer, closed, _job):
            refer.side_effect = api.SipCallError(
                "permission_denied",
                "provider-private-details",
                status=403,
                metadata={"sip_transfer_reason": "STR_REJECTED"},
            )
            await turn(
                "Sí, el código está correcto.",
                "iniciar_verificacion_cliente",
                {"codigo_cliente": "IOAA-0012"},
                answer="Se envió un código al correo registrado. ¿Qué código recibió?",
            )
            await turn(
                "El código recibido es cero cero uno dos tres cuatro.",
                "validar_codigo_correo",
                {"codigo": "001234"},
                answer="El código quedó verificado. ¿Qué fecha le sirve?",
            )
            await turn("¿Cuándo hay espacio?", "consultar_horarios")
            assert OFFER in said(session)
            refer.assert_not_awaited()
            await turn(
                "Sí, acepto la transferencia.",
                "transferir_a_asesor",
                {"confirmacion_usuario": True},
            )
            assert any("Sigo aquí con usted" in text for text in said(session))
            assert "provider-private-details" not in " ".join(said(session))
            assert not closed.is_set()
            refer.assert_awaited_once()
            await turn("Gracias, adiós.", "end_call")
            await asyncio.wait_for(closed.wait(), timeout=5)

        # Completion is accepted only after LiveKit reports a successful transfer.
        Backend.registration = "not_registered"
        async with phone_session() as (session, turn, refer, closed, job):
            refer.return_value = api.TransferSIPParticipantResponse(
                status=api.STS_TRANSFER_SUCCESSFUL, reason=api.STR_COMPLETED
            )
            await registration_offer(session, turn, refer)
            await turn(
                "De acuerdo, páseme con el asesor.",
                "transferir_a_asesor",
                {"confirmacion_usuario": True},
            )
            await asyncio.wait_for(closed.wait(), timeout=5)
            refer.assert_awaited_once()
            job.shutdown.assert_called_once()
            job.delete_room.assert_not_awaited()
            job.add_shutdown_callback.assert_not_called()

        assert all(
            path.endswith(("/start", "/verify", "/authorize", "/close"))
            for path, _ in requests
        )
        assert sum(path.endswith("/start") for path, _ in requests) == 4
    finally:
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=2)
