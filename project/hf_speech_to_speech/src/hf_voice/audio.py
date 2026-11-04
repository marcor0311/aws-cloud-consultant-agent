"""CoreAudio adapter only; all conversational decisions stay in the HF server."""

import asyncio
import base64
import json
import sys
import time
from queue import Empty, Full, Queue

import sounddevice as sd
from speech_to_speech.api.openai_realtime.audio_client import (
    PlaybackBuffer,
    RealtimeAudioClientConfig,
    build_session_update,
)
from websockets.asyncio.client import connect

from .transcript import TranscriptDisplay


class MicrophoneClient:
    def __init__(
        self,
        url,
        *,
        blocked=True,
        input_device=None,
        output_device=None,
        display=True,
        instructions=None,
        voice="Ryan",
    ):
        self.config = RealtimeAudioClientConfig(
            url=url, voice=voice, instructions=instructions, playback_buffer_ms=240
        )
        self.blocked, self.input_device, self.output_device = blocked, input_device, output_device
        self.playback = PlaybackBuffer(16000, startup_buffer_ms=self.config.playback_buffer_ms)
        self.queue = Queue(maxsize=32)
        self.suppress_until = 0.0
        self.response_id, self.generating = None, False
        self.response_audio_started = False
        self.ignored = set()
        self.ws = None
        self.display = display
        self.transcript = TranscriptDisplay() if display else None
        self.user_deltas = {}
        self.user_snapshots = set()
        self.stats = {
            "input_frames": 0,
            "suppressed_frames": 0,
            "output_audio_frames": 0,
            "manual_interruptions": 0,
        }

    def input_callback(self, data, frames, _timing, _status):
        self.stats["input_frames"] += frames
        now = time.monotonic()
        if self.microphone_blocked(now):
            self.stats["suppressed_frames"] += frames
            return
        try:
            self.queue.put_nowait((now, bytes(data)))
        except Full:
            pass

    def output_callback(self, data, frames, timing, _status):
        active = self.playback.is_active()
        self.playback.write(data)
        if any(memoryview(data).cast("B")):
            self.stats["output_audio_frames"] += frames
        if active:
            # Account for audio queued in CoreAudio, plus the room's echo tail.
            delay = max(0, timing.outputBufferDacTime - timing.currentTime)
            self.suppress_until = time.monotonic() + delay + frames / 16000 + 0.65

    def microphone_blocked(self, captured):
        return self.blocked and (
            self.playback.is_active()
            or (self.generating and self.response_audio_started)
            or captured < self.suppress_until
        )

    async def cancel(self):
        self.playback.clear()
        if self.transcript:
            self.transcript.interrupt()
        if self.response_id:
            self.ignored.add(self.response_id)
        self.stats["manual_interruptions"] += 1
        if self.generating:
            await self.ws.send(json.dumps({"type": "response.cancel"}))

    async def send(self):
        while True:
            try:
                captured, data = await asyncio.to_thread(self.queue.get, True, 0.1)
            except Empty:
                continue
            if time.monotonic() - captured > 0.5:
                continue
            if self.microphone_blocked(captured):
                continue
            await self.ws.send(
                json.dumps(
                    {"type": "input_audio_buffer.append", "audio": base64.b64encode(data).decode()}
                )
            )

    async def receive(self):
        async for message in self.ws:
            event = json.loads(message)
            self.handle_event(event)

    def handle_event(self, event):
        kind = event["type"]
        if kind == "session.updated" and self.display:
            print("Micrófono listo.", flush=True)
        elif kind == "response.created":
            self.response_id = event["response"]["id"]
            self.generating = True
            self.response_audio_started = False
        elif kind == "input_audio_buffer.speech_started":
            if self.response_id:
                self.ignored.add(self.response_id)
            self.playback.clear()
            if self.transcript:
                self.transcript.interrupt()
        elif kind == "response.output_audio.delta":
            if event["response_id"] not in self.ignored:
                self.response_audio_started = True
                self.playback.append(base64.b64decode(event["delta"]))
        elif kind == "response.output_audio.done" and event.get("response_id") == self.response_id:
            self.playback.finish()
        elif kind == "response.done":
            if event["response"]["id"] != self.response_id:
                return
            self.generating = False
            if event["response"]["status"] == "cancelled":
                self.playback.clear()
                if self.transcript:
                    self.transcript.interrupt()
            else:
                self.playback.finish()
        elif (
            kind
            in {
                "speech_to_speech.input_audio_transcription.snapshot",
                "conversation.item.input_audio_transcription.delta",
                "conversation.item.input_audio_transcription.completed",
            }
            and self.transcript
        ):
            item = event.get("item_id", "input")
            text = event.get("transcript", event.get("delta", ""))
            if kind.endswith(".snapshot"):
                self.user_snapshots.add(item)
            elif kind.endswith(".delta"):
                self.user_deltas[item] = self.user_deltas.get(item, "") + text
                # HF may send committed deltas alongside replaceable snapshots.
                # Keep their accumulators separate: adding both duplicates words.
                if item in self.user_snapshots:
                    return
                text = self.user_deltas[item]
            elif kind.endswith(".completed"):
                self.user_snapshots.discard(item)
                self.user_deltas.pop(item, None)
            self.transcript.update(
                "Tú",
                item,
                text,
                final=kind.endswith(".completed"),
            )
        elif (
            kind
            in {"response.output_audio_transcript.delta", "response.output_audio_transcript.done"}
            and self.transcript
        ):
            if event.get("response_id") not in self.ignored:
                self.transcript.update(
                    "Agente",
                    event.get("item_id", event.get("response_id", "output")),
                    event.get("transcript", event.get("delta", "")),
                    append=kind.endswith(".delta"),
                    final=kind.endswith(".done"),
                )
        elif kind == "error":
            raise RuntimeError(event.get("error", event))

    async def run(self):
        tasks, cancel_tasks = [], set()
        loop = asyncio.get_running_loop()

        def enter():
            if sys.stdin.readline() == "":
                loop.remove_reader(sys.stdin)
                return
            task = asyncio.create_task(self.cancel())
            cancel_tasks.add(task)
            task.add_done_callback(cancel_tasks.discard)

        registered = False
        try:
            async with connect(self.config.url, max_size=8 * 1024 * 1024) as ws:
                self.ws = ws
                await ws.send(json.dumps(build_session_update(self.config)))
                with (
                    sd.RawOutputStream(
                        samplerate=16000,
                        channels=1,
                        dtype="int16",
                        blocksize=512,
                        callback=self.output_callback,
                        device=self.output_device,
                    ),
                    sd.RawInputStream(
                        samplerate=16000,
                        channels=1,
                        dtype="int16",
                        blocksize=512,
                        callback=self.input_callback,
                        device=self.input_device,
                    ),
                ):
                    if sys.stdin.isatty():
                        loop.add_reader(sys.stdin, enter)
                        registered = True
                    tasks = [asyncio.create_task(self.send()), asyncio.create_task(self.receive())]
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
        finally:
            if self.transcript:
                self.transcript.close()
            if registered:
                loop.remove_reader(sys.stdin)
            for task in [*tasks, *cancel_tasks]:
                task.cancel()
            await asyncio.gather(*tasks, *cancel_tasks, return_exceptions=True)
