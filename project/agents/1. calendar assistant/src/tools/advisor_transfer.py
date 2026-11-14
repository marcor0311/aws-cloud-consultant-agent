"""A restricted conversation phase after the backend denies registration access."""

import json

from livekit.agents import (
    Agent,
    RunContext,
    ToolError,
    function_tool,
    get_job_context,
    llm,
    mcp,
)
from livekit.agents.llm import ToolFlag

from src.config import advisor_transfer_settings
from src.integrations.sip_transfer import transfer_active_call

OFFER = (
    "Para continuar con su registro necesita hablar con un asesor de negocio. "
    "¿Quiere que intente comunicarle con un asesor en esta misma llamada?"
)
NEXT_STEP = (
    "Puede contactar a asistencia arroba noname punto com para completar "
    "su registro con un asesor de negocio. Por ahora no puedo gestionar citas."
)

UNAVAILABLE = "El asesor no está disponible en este momento. " + NEXT_STEP


class AdvisorAssistant(Agent):
    def __init__(self, *, llm_model, end_tools):
        super().__init__(
            llm=llm_model,
            tools=end_tools,
            instructions=(
                "Sigues siendo Alisa, la asistente de Stuart. Habla en español, "
                "con calidez y brevedad, sin mencionar herramientas ni estados internos. "
                "El backend exige atención de un asesor. No reveles datos del cliente "
                "ni solicites códigos, OTP, correo o datos nuevos. No puedes gestionar "
                "citas ni volver a verificar en esta llamada. Si no hay un asesor disponible, "
                "orienta a contactar a asistencia arroba noname punto com; no ofrezcas "
                "transferir ni reveles detalles de configuración. Si has ofrecido "
                "comunicar con un asesor, interpreta la respuesta. Solo una aceptación "
                "explícita autoriza transferir_a_asesor con confirmacion_usuario=true. "
                "Una pregunta, silencio, agradecimiento o respuesta ambigua no es "
                "aceptación: aclara sin transferir. Si rechaza, llama la herramienta "
                "con false para terminar la gestión sin transferir. Si se despide, "
                "usa end_call. Después de un fallo no reintentes ni afirmes que hubo "
                "conexión; permite preguntas sobre cómo contactar y usa end_call "
                "cuando se despida. No expongas el destino privado de transferencia."
            ),
        )
        self._offer_delivered = False
        self._latest_user_id = None
        self._offered_after_user_id = None
        self._resolved = False

    def _observe_user(self, event):
        if isinstance(event.item, llm.ChatMessage) and event.item.role == "user":
            self._latest_user_id = event.item.id

    async def on_enter(self):
        self.session.on("conversation_item_added", self._observe_user)
        # Check local configuration before offering a transfer that cannot be made.
        try:
            advisor_transfer_settings()
        except ValueError:
            self._resolved = True
            await self.update_tools(
                [tool for tool in self.tools if tool.id == "end_call"]
            )
            await self.session.say(UNAVAILABLE, allow_interruptions=False)
            return
        # This phase starts with fresh context and never carries client codes or OTPs.
        speech = self.session.say(OFFER, allow_interruptions=False)
        await speech
        if not speech.interrupted:
            self._offered_after_user_id = self._latest_user_id
            self._offer_delivered = True

    async def on_exit(self):
        self.session.off("conversation_item_added", self._observe_user)

    @function_tool(flags=ToolFlag.IGNORE_ON_ENTER, on_duplicate="reject")
    async def transferir_a_asesor(
        self, context: RunContext, confirmacion_usuario: bool
    ) -> None:
        """Resuelve la oferta de asesor solo con una respuesta posterior de la persona.

        confirmacion_usuario: true solo si acepta explícitamente transferir esta llamada;
        false si rechaza. No llamar ante preguntas, silencio ni respuestas ambiguas.
        """
        if (
            not self._offer_delivered
            or self._latest_user_id is None
            or self._latest_user_id == self._offered_after_user_id
        ):
            raise ToolError("Espere una respuesta de la persona después de la oferta.")
        if self._resolved:
            raise ToolError("La derivación ya terminó; no vuelva a transferir.")
        context.disallow_interruptions()
        self._resolved = True
        # Keep only end_call, even if REFER fails. Registration never grants OTP access.
        await self.update_tools([tool for tool in self.tools if tool.id == "end_call"])
        if not confirmacion_usuario:
            await self.session.say(NEXT_STEP, allow_interruptions=False)
            return

        await self.session.say(
            "Voy a intentar comunicarle con un asesor. Espere un momento, por favor.",
            allow_interruptions=False,
        )
        job = get_job_context()

        def finish_job(_event):
            job.shutdown(reason="advisor_transfer_finished")

        # The caller can leave the room before the REFER response arrives.
        self.session.once("close", finish_job)
        outcome = await transfer_active_call()
        if outcome == "transferred":
            # REFER already removed the caller from LiveKit. Do not delete the room.
            self.session.shutdown()
            return
        self.session.off("close", finish_job)
        explanation = {
            "no_answer": "El asesor no contestó a tiempo. Sigo aquí con usted. ",
            "rejected": "No se pudo completar la transferencia. Sigo aquí con usted. ",
            "unavailable": "El asesor no está disponible en este momento. ",
            "failed": "No pude confirmar la conexión con el asesor. Sigo aquí con usted. ",
        }[outcome]
        await self.session.say(explanation + NEXT_STEP, allow_interruptions=False)


def resolve_calendar_result(context: mcp.MCPToolResultContext, *, llm_model, end_tools):
    """Only a trusted MCP/backend result can enter the restricted referral phase."""
    content = context.result.content
    if len(content) == 1 and hasattr(content[0], "text"):
        try:
            payload = json.loads(content[0].text)
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("estado") in {
            "not_registered",
            "not_enabled",
        }:
            # Returning an Agent is the SDK's tool handoff; no original-agent reply.
            return AdvisorAssistant(llm_model=llm_model, end_tools=end_tools)
    # Preserve the SDK's normal serialization for all existing Calendar/OTP results.
    if len(content) == 1:
        return content[0].model_dump_json(by_alias=True)
    if not content:
        raise ToolError("La herramienta no devolvió un resultado.")
    return json.dumps([item.model_dump(by_alias=True) for item in content])
