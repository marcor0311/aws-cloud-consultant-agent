import json
import os
import sys
from pathlib import Path

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    STTContextOptions,
    TurnHandlingOptions,
    cli,
    inference,
    mcp,
    room_io,
)
from livekit.agents.beta.tools import EndCallTool
from livekit.plugins import ai_coustics

try:
    from .config import load_environment, require_inference_enabled
except ImportError:  # Executed directly by the LiveKit launcher.
    from config import load_environment, require_inference_enabled

PROJECT_DIR = Path(__file__).resolve().parents[1]
AGENT_CONFIG = json.loads((PROJECT_DIR / "agent.json").read_text(encoding="utf-8"))
load_environment()


class Assistant(Agent):
    def __init__(self, *, llm_model=None, receipt_file=None) -> None:
        from src.tools.advisor_transfer import resolve_calendar_result

        async def finish_without_more_tools(event):
            # Speak once through the SDK and wait for playback. A model-generated
            # farewell can be empty or invoke end_call again in long conversations.
            await event.ctx.session.current_agent.update_tools([])
            await event.ctx.session.say(
                "Gracias por llamar. Hasta luego.", allow_interruptions=False
            )

        end_call = EndCallTool(
            delete_room=True,
            ignore_on_enter=True,
            on_tool_called=finish_without_more_tools,
            extra_description=(
                "Úsala cuando la persona se despida o indique claramente que ya terminó, "
                "incluso antes de verificar su identidad. No la uses por un agradecimiento "
                "si aún tiene una pregunta, una gestión pendiente o pide esperar."
            ),
            end_instructions=None,
        )
        model = (
            llm_model
            if llm_model is not None
            else inference.LLM(**AGENT_CONFIG["models"]["llm"])
        )
        super().__init__(
            llm=model,
            tools=[
                mcp.MCPToolset(
                    id="google-calendar",
                    mcp_server=mcp.MCPServerStdio(
                        command=sys.executable,
                        args=["-m", "src.tools.calendar_mcp"],
                        cwd=str(PROJECT_DIR),
                        tool_result_resolver=lambda result: resolve_calendar_result(
                            result, llm_model=model, end_tools=end_call.tools
                        ),
                        env={
                            **(
                                {"CALENDAR_CALL_RECEIPT_FILE": str(receipt_file)}
                                if receipt_file
                                else {}
                            ),
                            **{
                                key: os.environ[key]
                                for key in (
                                    "CALENDAR_ACCESS_URL",
                                    "CALENDAR_ACCESS_SERVICE_KEY",
                                    "CALENDAR_ACCESS_ORIGIN_ID",
                                    "WORKFLOW_ENABLED",
                                    "CALENDAR_ASSISTANT_MODE",
                                    "CALENDAR_MOCK_DB",
                                    "MOCK_CLOCK_FILE",
                                )
                                if key in os.environ
                            },
                        },
                    ),
                ),
                *end_call.tools,
            ],
            instructions=(PROJECT_DIR / "prompts" / "assistant.txt").read_text(
                encoding="utf-8"
            ),
        )


server = AgentServer()


@server.rtc_session(agent_name=AGENT_CONFIG["agent_id"])
async def my_agent(ctx: JobContext):
    require_inference_enabled()
    from src.integrations.post_call import PostCallDelivery, register_delivery

    delivery = PostCallDelivery()
    ctx.log_context_fields = {
        "room": ctx.room.name,
        "agent_id": AGENT_CONFIG["agent_id"],
        "agent_number": AGENT_CONFIG["agent_number"],
    }

    session = AgentSession(
        stt=inference.STT(**AGENT_CONFIG["models"]["stt"]),
        stt_context_options=STTContextOptions(
            keyterms=["LiveKit"],
            keyterm_detection={"enabled": True},
        ),
        tts=inference.TTS(**AGENT_CONFIG["models"]["tts"]),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
            preemptive_generation={"enabled": True},
        ),
    )

    register_delivery(ctx, session, delivery)

    await session.start(
        agent=Assistant(receipt_file=delivery.path),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_S
                ),
            ),
        ),
    )

    await ctx.connect()
    await session.generate_reply(
        instructions=(
            "Inicia ahora en español con este saludo natural: Hola, soy Alisa, la asistente "
            "de Stuart, gerente de Relaciones con el Cliente. ¿Con quién tengo el gusto? "
            "Usa el femenino al hablar de ti y espera la respuesta antes de preguntar otra cosa."
        )
    )


if __name__ == "__main__":
    require_inference_enabled()
    cli.run_app(server)
