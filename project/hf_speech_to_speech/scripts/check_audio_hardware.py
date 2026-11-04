"""Manual acoustic check: opens the microphone and plays a synthetic Spanish phrase.

Run with the built-in speakers and microphone selected, in a quiet room.
Only numerical measurements are persisted.
"""

import asyncio
import json
import time

import sounddevice as sd
import soundfile as sf

from hf_voice.audio import MicrophoneClient
from hf_voice.benchmark import FIXTURES, prepare_fixtures
from hf_voice.runtime import ServerSession
from hf_voice.settings import DEFAULT_PROFILE, has_headphones


class Probe(MicrophoneClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ready = asyncio.Event()
        self.completed = asyncio.Event()
        self.statuses = []
        self.false_interruptions = 0
        self.generated_audio = False

    def handle_event(self, event):
        kind = event["type"]
        if kind == "session.updated":
            self.ready.set()
        if kind == "response.output_audio.delta":
            self.generated_audio = True
        if kind == "input_audio_buffer.speech_started" and self.generated_audio:
            self.false_interruptions += 1
        if kind == "response.done":
            self.statuses.append(event["response"]["status"])
            self.completed.set()
        super().handle_event(event)


async def main():
    if has_headphones(sd.query_devices(kind="output")["name"]):
        raise RuntimeError(
            "Selecciona los altavoces y el micrófono del Mac para la prueba acústica."
        )
    await prepare_fixtures()
    async with ServerSession(DEFAULT_PROFILE, "hardware-audio-check") as session:
        client = Probe(
            session.data["runtime"]["client"]["url"],
            display=False,
            blocked=True,
            instructions=session.data["blocks"]["llm"]["settings"]["init_chat_prompt"],
            voice=session.data["runtime"]["client"]["voice"],
        )
        task = asyncio.create_task(client.run())
        try:
            await asyncio.wait_for(client.ready.wait(), 10)
            await asyncio.sleep(0.5)
            samples, rate = sf.read(FIXTURES / "user-0.wav", dtype="float32")
            sd.play(samples, rate)
            await asyncio.to_thread(sd.wait)
            await asyncio.wait_for(client.completed.wait(), 45)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and (
                client.playback.is_active() or time.monotonic() < client.suppress_until
            ):
                await asyncio.sleep(0.1)
            await asyncio.sleep(1)
            result = {
                "input_source": (
                    "synthetic Kokoro phrase played on speakers "
                    "and captured by actual Mac microphone"
                ),
                "human_conversation_test": False,
                "input_device": sd.query_devices(kind="input")["name"],
                "output_device": sd.query_devices(kind="output")["name"],
                "response_statuses": client.statuses,
                "speaker_self_interruptions": client.false_interruptions,
                "actual_output_seconds": client.stats["output_audio_frames"] / 16000,
                "audio_callback_counts": client.stats,
            }
            (session.measurements.path / "hardware-audio.json").write_text(
                json.dumps(result, indent=2) + "\n"
            )
            print(json.dumps(result, indent=2), flush=True)
            assert client.statuses == ["completed"], result
            assert result["actual_output_seconds"] > 2, result
            assert client.false_interruptions == 0, result
        finally:
            sd.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
