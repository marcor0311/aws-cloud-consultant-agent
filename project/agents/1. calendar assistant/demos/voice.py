"""Drive the real LiveKit session and Calendar MCP with scripted, offline providers."""

import asyncio
import json
import os
import sys
from collections import deque
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from livekit.agents import AgentSession, llm
from livekit.agents.testing import fake_job_context
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

from src.agent import Assistant
from src.integrations.mock_network import install_mock_network_guard


def advance(seconds):
    url = os.environ["MOCK_BACKEND_URL"]
    if urlsplit(url).hostname != "127.0.0.1":
        raise ValueError("El simulador solo se conecta al backend mock local.")
    request = Request(
        f"{url}/mock/clock/advance",
        data=json.dumps({"seconds": seconds}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ['CALENDAR_ACCESS_SERVICE_KEY']}",
        },
    )
    with urlopen(request, timeout=10) as response:
        return json.load(response)["timestamp"]


class ScriptedLLM(llm.LLM):
    def __init__(self):
        super().__init__()
        self.responses = deque()

    def chat(
        self,
        *,
        chat_ctx,
        tools=None,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
        **kwargs,
    ):
        return ScriptedStream(
            self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options
        )

    def prepare(self, text, tool=None, arguments=None):
        if self.responses:
            raise RuntimeError(
                "El turno anterior no consumió el guion del modelo mock."
            )
        if tool:
            self.responses.append(
                llm.ChoiceDelta(
                    tool_calls=[
                        llm.FunctionToolCall(
                            name=tool,
                            arguments=json.dumps(arguments or {}),
                            call_id=f"mock-{tool}",
                        )
                    ]
                )
            )
        if tool != "end_call":
            self.responses.append(llm.ChoiceDelta(content=text))


class ScriptedStream(llm.LLMStream):
    async def _run(self):
        if not self._llm.responses:
            raise RuntimeError(
                "El SDK pidió una respuesta no prevista por el modelo mock."
            )
        advance(1)
        self._event_ch.send_nowait(
            llm.ChatChunk(id="mock", delta=self._llm.responses.popleft())
        )


async def run(scenario):
    if os.getenv("CALENDAR_ASSISTANT_MODE") != "mock":
        raise ValueError("Este recorrido requiere proveedores mock.")
    install_mock_network_guard()
    model = ScriptedLLM()
    trace = []
    with fake_job_context() as job:
        shutdown_callbacks = []
        job.add_shutdown_callback = shutdown_callbacks.append
        job.shutdown = Mock()
        job.delete_room = AsyncMock()
        async with AgentSession() as session:
            from src.integrations.post_call import PostCallDelivery, register_delivery

            delivery = PostCallDelivery(os.environ["MOCK_POST_CALL_DIR"])
            register_delivery(job, session, delivery)
            closed = asyncio.Event()
            session.on("close", lambda _: closed.set())
            await session.start(
                agent=Assistant(llm_model=model, receipt_file=delivery.path),
                record=False,
            )

            async def turn(user, answer, tool=None, arguments=None, wait=4):
                advance(wait)
                started = advance(0)
                model.prepare(answer, tool, arguments)
                previous = len(session.history.items)
                await asyncio.wait_for(session.run(user_input=user), timeout=30)
                observed = session.history.items[previous:]
                calls = [
                    item.name for item in observed if isinstance(item, llm.FunctionCall)
                ]
                if tool and calls != [tool]:
                    raise AssertionError(
                        f"El SDK no ejecutó la herramienta esperada: {tool}"
                    )
                trace.append(
                    {
                        "user": user,
                        "assistant": answer,
                        "tools": calls,
                        "started_at": started,
                        "ended_at": advance(0),
                    }
                )

            await turn(
                f"Soy {scenario['contact']}. Quiero conversar con Stuart sobre {scenario['title']}.",
                "Claro, te ayudo a encontrar un horario. ¿Cuál es el código de tu empresa?",
            )
            await turn(
                scenario["client_code"],
                f"Entendí el código {scenario['client_code']}. ¿Lo tengo correcto?",
                "preparar_confirmacion_cliente",
                {"codigo_transcrito": scenario["client_code"]},
            )
            await turn(
                "Sí, ese es mi código.",
                "Te envié el código al correo registrado de la empresa. ¿Qué código recibiste?",
                "iniciar_verificacion_cliente",
                {"codigo_cliente": scenario["client_code"]},
            )
            mailbox = json.loads(Path(os.environ["MOCK_MAILBOX_FILE"]).read_text())
            code = mailbox[scenario["email"]]["code"]
            await turn(
                f"El código que recibí es {code}.",
                "El correo quedó verificado. ¿Qué día y hora te funcionan?",
                "validar_codigo_correo",
                {"codigo": code},
                wait=25,
            )
            date, hour = (
                scenario["meeting_start"][:10],
                scenario["meeting_start"][11:16],
            )
            await turn(
                f"¿Hay espacio el {date} a las {hour}?",
                "Ese horario está disponible para una reunión de treinta minutos. ¿Lo confirmamos?",
                "consultar_horarios",
                {"fecha_solicitada": date, "hora_solicitada": hour},
            )
            await turn(
                "Sí, confirmo ese horario.",
                "La reunión con Stuart quedó agendada y la invitación está lista. ¿Necesitás algo más?",
                "agendar_reunion",
                {
                    "inicio": scenario["meeting_start"],
                    "nombre": scenario["contact"],
                    "tema": scenario["title"],
                },
            )
            await turn(
                "Eso era todo. Muchas gracias, adiós.",
                "Gracias por llamar. Hasta luego.",
                "end_call",
            )
            await asyncio.wait_for(closed.wait(), timeout=5)
            job.shutdown.assert_called_once()
            for callback in shutdown_callbacks:
                await callback()
            job.delete_room.assert_awaited_once()
            history = session.history.to_dict(exclude_timestamp=False)
    print(
        json.dumps(
            {
                "mode": "mock",
                "sdk": "livekit",
                "call_closed": closed.is_set(),
                "room_transport": "mock",
                "trace": trace,
                "history": history,
            },
            ensure_ascii=False,
            default=str,
        )
    )


if __name__ == "__main__":
    asyncio.run(run(json.load(sys.stdin)))
