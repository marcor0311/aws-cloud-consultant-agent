import asyncio
import time
from collections.abc import Callable

from .config import Config
from .contracts import AudioSink, AudioSource, LanguageModel, Synthesizer, Transcriber, TurnToken
from .dialogue import History, PhraseBuffer
from .metrics import Recorder
from .vad import EndpointDetector


class ConversationEngine:
    """No device APIs: replace sources/sinks to use the same engine in a call."""

    def __init__(
        self,
        config: Config,
        vad,
        stt: Transcriber,
        llm: LanguageModel,
        tts: Synthesizer,
        output: AudioSink,
        metrics: Recorder,
        on_event: Callable[[str, dict], None] | None = None,
        allow_barge_in: bool = True,
    ):
        self.config, self.vad, self.stt, self.llm = config, vad, stt, llm
        self.tts, self.output, self.metrics = tts, output, metrics
        c = config.conversation
        self.history = History(c.system_prompt, c.history_turns, c.history_characters)
        self.detector = EndpointDetector(config.vad)
        self.on_event = on_event or (lambda *_: None)
        self.task: asyncio.Task | None = None
        self.token: TurnToken | None = None
        self.number = 0
        self.last_error: str | None = None
        self.allow_barge_in = allow_barge_in
        self._input_suppressed = False

    def emit(self, kind, **fields):
        self.on_event(kind, fields)

    def interrupt(self, reason="barge_in"):
        if self.task and not self.task.done():
            start = time.perf_counter()
            self.token.cancel(reason)
            self.output.interrupt()
            self.task.cancel()
            self.metrics.event(
                reason,
                turn=self.token.number,
                output_cancel_request_ms=(time.perf_counter() - start) * 1000,
            )
            self.emit("interrupted", reason=reason)

    async def run(self, source: AudioSource):
        async for frame in source:
            suppress = not self.allow_barge_in and (
                self.output.is_playing
                or frame.captured_at < getattr(self.output, "input_resume_at", 0)
            )
            if suppress != self._input_suppressed:
                self.detector.reset()
                self.vad.reset()
                self._input_suppressed = suppress
            if suppress:
                continue
            if frame.discontinuity:
                self.detector.reset()
                self.vad.reset()
                self.interrupt("audio_discontinuity")
                self.metrics.event("audio_input_overflow")
            detection = self.detector.feed(frame, self.vad.probability(frame.samples))
            if detection.started:
                self.interrupt()
                self.emit("listening")
            if detection.utterance:
                self.interrupt("new_turn")
                self.number += 1
                token = self.token = TurnToken(self.number)
                self.task = asyncio.create_task(self._respond(detection.utterance, token))
        await self.drain()

    async def drain(self):
        if self.task:
            try:
                await self.task
            except asyncio.CancelledError:
                if not self.token.cancelled.is_set():
                    raise

    async def close(self):
        self.interrupt("shutdown")
        await self.drain()

    async def _respond(self, utterance, token):
        started = time.perf_counter()
        record = {
            "turn": token.number,
            "status": "completed",
            "first_audio_ms": None,
            "endpoint_ms": (utterance.detected_at - utterance.speech_ended_at) * 1000,
            "speech_seconds": utterance.speech_ended_at - utterance.started_at,
            "played_audio_seconds": 0.0,
        }
        delivered = []
        had_audio = False
        try:
            start = time.perf_counter()
            text = await self.stt.transcribe(utterance.samples)
            record["stt_ms"] = (time.perf_counter() - start) * 1000
            if token.cancelled.is_set():
                raise asyncio.CancelledError
            if not text:
                record["status"] = "empty_transcript"
                return
            self.history.add("user", text)
            self.emit("user", text=text)
            phrases: asyncio.Queue[str | None] = asyncio.Queue(maxsize=2)
            c = self.config.conversation
            buffer = PhraseBuffer(c.phrase_min_characters, c.phrase_max_characters)
            llm_start = time.perf_counter()

            async def produce():
                async for word in self.llm.stream(self.history.messages()):
                    if token.cancelled.is_set():
                        return
                    record.setdefault(
                        "llm_first_token_ms", (time.perf_counter() - llm_start) * 1000
                    )
                    for phrase in buffer.feed(word):
                        await phrases.put(phrase)
                tail = buffer.flush()
                if tail:
                    await phrases.put(tail)
                record["llm_total_ms"] = (time.perf_counter() - llm_start) * 1000
                record["ollama"] = dict(getattr(self.llm, "stats", {}))
                await phrases.put(None)

            def audio_started(at):
                nonlocal had_audio
                had_audio = True
                if record["first_audio_ms"] is None:
                    record["first_audio_ms"] = (at - utterance.speech_ended_at) * 1000

            async def speak():
                while True:
                    phrase = await phrases.get()
                    if phrase is None:
                        return
                    tts_start = time.perf_counter()
                    async for audio in self.tts.synthesize(phrase, token):
                        if token.cancelled.is_set():
                            return
                        record.setdefault(
                            "tts_first_chunk_ms", (time.perf_counter() - tts_start) * 1000
                        )
                        playback = await self.output.play(audio, token, audio_started)
                        record["played_audio_seconds"] += playback.played_seconds
                        if playback.completed:
                            delivered.append(audio.text or phrase)
                            self.emit("assistant", text=audio.text or phrase)
                        else:
                            return

            async with asyncio.TaskGroup() as group:
                group.create_task(produce())
                group.create_task(speak())
        except asyncio.CancelledError:
            record["status"] = "interrupted"
            record["reason"] = token.reason
            raise
        except Exception as exc:
            record["status"] = "error"
            record["error"] = str(exc)
            self.last_error = str(exc)
            token.cancel("backend_error")
            self.output.interrupt()
            self.emit("error", error=str(exc))
        finally:
            spoken = " ".join(delivered)
            if record["status"] == "interrupted" and (had_audio or spoken):
                spoken += " [Respuesta interrumpida por el usuario.]"
            if spoken:
                self.history.add("assistant", spoken)
            record["turn_processing_ms"] = (time.perf_counter() - started) * 1000
            self.metrics.turn(record)
            self.emit("metrics", **record)
