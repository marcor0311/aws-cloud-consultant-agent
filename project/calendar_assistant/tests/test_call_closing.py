"""Exercise the actual end-call tool and SDK playback lifecycle without services."""

import asyncio
from unittest.mock import Mock

from livekit import rtc
from livekit.agents import AgentSession, llm, mcp
from livekit.agents.testing import fake_job_context
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from livekit.agents.voice import io

from src import agent


class ScriptedLLM(llm.LLM):
    def __init__(self):
        super().__init__()
        self.responses = iter(
            [
                llm.ChoiceDelta(
                    tool_calls=[
                        llm.FunctionToolCall(
                            name="end_call", arguments="{}", call_id="bye"
                        )
                    ]
                ),
                llm.ChoiceDelta(content="Gracias por llamar. Hasta luego."),
            ]
        )

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


class ScriptedStream(llm.LLMStream):
    async def _run(self):
        self._event_ch.send_nowait(
            llm.ChatChunk(id="script", delta=next(self._llm.responses))
        )


class PlaybackSink(io.AudioOutput):
    def __init__(self):
        super().__init__(
            label="test-playback", capabilities=io.AudioOutputCapabilities(pause=False)
        )
        self.flushed = asyncio.Event()

    async def capture_frame(self, frame):
        await super().capture_frame(frame)

    def flush(self):
        super().flush()
        self.flushed.set()

    def clear_buffer(self):
        self.on_playback_finished(playback_position=0, interrupted=True)


class ScriptedSpeechAssistant(agent.Assistant):
    async def tts_node(self, text, model_settings):
        async for _ in text:
            yield rtc.AudioFrame.create(
                sample_rate=24000, num_channels=1, samples_per_channel=240
            )


async def test_hangup_waits_for_goodbye_playback(monkeypatch):
    # Only providers and the room transport are fake; the session and end_call are real.
    monkeypatch.setattr(agent.inference, "LLM", lambda **kwargs: ScriptedLLM())
    assistant = ScriptedSpeechAssistant()
    await assistant.update_tools(
        [tool for tool in assistant.tools if not isinstance(tool, mcp.MCPToolset)]
    )
    sink = PlaybackSink()
    closed = asyncio.Event()
    shutdown_callbacks = []

    with fake_job_context() as job:
        monkeypatch.setattr(job, "add_shutdown_callback", shutdown_callbacks.append)
        shutdown = Mock()
        monkeypatch.setattr(job, "shutdown", shutdown)
        delete_room = Mock(return_value=asyncio.get_running_loop().create_future())
        delete_room.return_value.set_result(None)
        monkeypatch.setattr(job, "delete_room", delete_room)

        async with AgentSession() as session:
            session.output.audio = sink
            session.on("close", lambda _: closed.set())
            await session.start(agent=assistant)
            turn = session.run(user_input="Eso era todo, adiós.")

            await asyncio.wait_for(sink.flushed.wait(), timeout=5)
            assert not closed.is_set()
            shutdown.assert_not_called()
            delete_room.assert_not_called()

            sink.on_playback_finished(playback_position=0.01, interrupted=False)
            result = await asyncio.wait_for(turn, timeout=5)
            result.expect.next_event().is_function_call(name="end_call")
            result.expect.next_event().is_function_call_output()
            result.expect.next_event().is_message(role="assistant")
            result.expect.no_more_events()
            await asyncio.wait_for(closed.wait(), timeout=5)
            shutdown.assert_called_once()
            for callback in shutdown_callbacks:
                await callback()
            delete_room.assert_called_once()
