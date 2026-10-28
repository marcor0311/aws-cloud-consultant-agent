import asyncio
import time

import numpy as np

from voice_call_agent.config import Config
from voice_call_agent.contracts import AudioChunk, AudioFrame, Playback
from voice_call_agent.engine import ConversationEngine
from voice_call_agent.metrics import Recorder


class Probability:
    def probability(self, samples):
        return float(samples[0])

    def reset(self):
        pass


class STT:
    def __init__(self):
        self.turn = 0

    async def transcribe(self, samples):
        self.turn += 1
        return ["Me llamo Marco", "Recuerda mi nombre"][self.turn - 1]


class LLM:
    def __init__(self):
        self.prompts = []
        self.cancelled = False
        self.stats = {}

    async def stream(self, messages):
        self.prompts.append(messages)
        if len(self.prompts) == 1:
            try:
                yield "Esta primera respuesta no debe quedar como si se hubiera escuchado. "
                await asyncio.Event().wait()
            finally:
                self.cancelled = True
        else:
            yield "Tu nombre es Marco, según lo que me acabas de decir."


class TTS:
    async def synthesize(self, text, token):
        if not token.cancelled.is_set():
            yield AudioChunk(np.ones(240, np.float32), 24000, text)


class Sink:
    def __init__(self):
        self.started = asyncio.Event()
        self.calls = 0
        self.stopped = 0
        self.completed = []

    async def play(self, audio, token, on_start=None):
        self.calls += 1
        at = time.perf_counter()
        on_start(at)
        if self.calls == 1:
            self.started.set()
            await asyncio.Event().wait()
        assert not token.cancelled.is_set()
        self.completed.append(audio.text)
        return Playback(True, at, 0.01)

    def interrupt(self):
        self.stopped += 1


async def test_barge_in_cancels_generation_and_keeps_only_delivered_context(tmp_path):
    config = Config()
    config.vad.silence_ms = 96
    recorder = Recorder(str(tmp_path), {"sink": "test"})
    sink, llm = Sink(), LLM()
    engine = ConversationEngine(config, Probability(), STT(), llm, TTS(), sink, recorder)

    class Source:
        async def __aiter__(self):
            index, origin = 0, time.perf_counter() - 10
            for utterance in range(2):
                if utterance == 1:
                    await asyncio.wait_for(sink.started.wait(), timeout=2)
                for level in [*[0.9] * 8, *[0.0] * 4]:
                    yield AudioFrame(np.full(512, level, np.float32), origin + index * 0.032)
                    index += 1
                    await asyncio.sleep(0)

    await asyncio.wait_for(engine.run(Source()), timeout=3)
    assert llm.cancelled
    assert sink.stopped == 1
    assert sink.completed == ["Tu nombre es Marco, según lo que me acabas de decir."]
    context = llm.prompts[-1]
    assert any(m["content"] == "Me llamo Marco" for m in context)
    assert any("interrumpida" in m["content"] for m in context)
    assert not any("no debe quedar" in m["content"] for m in engine.history.messages())
    assert [t["status"] for t in recorder.turns] == ["interrupted", "completed"]
    assert recorder.turns[0]["first_audio_ms"] is not None
    summary = recorder.finish({})
    assert summary["barge_in_events"] == 1 and summary["completed"] == 1


async def test_speaker_echo_does_not_cut_the_answer_or_create_a_new_turn(tmp_path):
    config = Config()
    config.vad.silence_ms = 96
    recorder = Recorder(str(tmp_path), {"sink": "speaker_echo_test"})

    class CompleteLLM:
        async def stream(self, messages):
            yield "Esta respuesta debe escucharse completa aunque el micrófono capte el altavoz."

    class Speaker:
        def __init__(self):
            self.started, self.release = asyncio.Event(), asyncio.Event()
            self.is_playing = False
            self.completed = []
            self.stopped = 0

        async def play(self, audio, token, on_start=None):
            self.is_playing = True
            on_start(time.perf_counter())
            self.started.set()
            await self.release.wait()
            self.is_playing = False
            self.completed.append(audio.text)
            return Playback(True, time.perf_counter(), 1)

        def interrupt(self):
            self.stopped += 1

    speaker = Speaker()
    engine = ConversationEngine(
        config, Probability(), STT(), CompleteLLM(), TTS(), speaker, recorder, allow_barge_in=False
    )

    class EchoInput:
        async def __aiter__(self):
            index, origin = 0, time.perf_counter() - 10
            for level in [*[0.9] * 8, *[0.0] * 4]:
                yield AudioFrame(np.full(512, level, np.float32), origin + index * 0.032)
                index += 1
                await asyncio.sleep(0)
            await asyncio.wait_for(speaker.started.wait(), timeout=2)
            for _ in range(10):
                yield AudioFrame(np.full(512, 0.9, np.float32), origin + index * 0.032)
                index += 1
                await asyncio.sleep(0)
            speaker.release.set()
            await asyncio.sleep(0)
            for _ in range(8):
                yield AudioFrame(np.zeros(512, np.float32), origin + index * 0.032)
                index += 1
                await asyncio.sleep(0)

    await asyncio.wait_for(engine.run(EchoInput()), timeout=3)
    assert speaker.stopped == 0
    assert len(speaker.completed) == 1
    assert engine.number == 1
    assert recorder.turns[0]["status"] == "completed"
    assert recorder.event_count == 0
    recorder.finish({})


async def test_delayed_echo_frames_are_ignored_after_device_playback_ends(tmp_path):
    config = Config()
    config.vad.silence_ms = 96
    recorder = Recorder(str(tmp_path), {"sink": "delayed_echo"})
    resume_at = time.perf_counter()

    class QuietOutput:
        is_playing = False
        input_resume_at = resume_at

    engine = ConversationEngine(
        config, Probability(), STT(), None, None, QuietOutput(), recorder, allow_barge_in=False
    )

    class Backlog:
        async def __aiter__(self):
            for index, level in enumerate([*[0.9] * 8, *[0.0] * 4]):
                yield AudioFrame(np.full(512, level, np.float32), resume_at - 1 + index * 0.032)

    await engine.run(Backlog())
    assert engine.number == 0 and not recorder.turns
    recorder.finish({})
