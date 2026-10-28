import asyncio
import sys
from types import SimpleNamespace

import numpy as np

from voice_call_agent.audio import LocalInput, LocalOutput, WavOutput, allow_voice_barge_in
from voice_call_agent.contracts import AudioChunk, TurnToken


async def test_input_overflow_discards_stale_frames_and_marks_discontinuity():
    source = LocalInput(queue_frames=2)
    source._enqueue((np.ones(960), 1, False))
    source._enqueue((np.ones(960), 2, False))
    source._enqueue((np.ones(960), 3, False))
    assert source.queue.qsize() == 1
    _, timestamp, gap = source.queue.get_nowait()
    assert timestamp == 3 and gap


async def test_output_callback_zeroes_stale_audio_on_interruption(monkeypatch):
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]

        def start(self):
            pass

        def abort(self):
            pass

        def close(self):
            pass

    fake = SimpleNamespace(
        query_devices=lambda *_: {"default_samplerate": 48000, "name": "MacBook Pro Speakers"},
        OutputStream=Stream,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    with LocalOutput() as sink:
        token = TurnToken(1)
        task = asyncio.create_task(sink.play(AudioChunk(np.ones(1024), 48000), token))
        await asyncio.sleep(0)
        audio = np.empty((256, 1), np.float32)
        timing = SimpleNamespace(outputBufferDacTime=0, currentTime=0)
        sink.stream.callback(audio, 256, timing, None)
        assert np.all(audio == 1)
        token.cancel("barge_in")
        sink.interrupt()
        sink.stream.callback(audio, 256, timing, None)
        assert np.all(audio == 0)
        assert not (await task).completed
        next_task = asyncio.create_task(
            sink.play(AudioChunk(np.full(256, 0.25), 48000), TurnToken(2))
        )
        await asyncio.sleep(0)
        sink.stream.callback(audio, 256, timing, None)
        assert np.all(audio == 0.25)
        assert (await next_task).completed
        assert sink.is_playing


async def test_simulated_playback_saves_only_the_prefix_before_cancellation(tmp_path):
    import soundfile as sf

    path = tmp_path / "cut.wav"
    sink, token = WavOutput(path, realtime=True), TurnToken(1)
    task = asyncio.create_task(sink.play(AudioChunk(np.ones(24000), 24000), token))
    await sink.started.wait()
    token.cancel("barge_in")
    result = await task
    sink.close()
    assert not result.completed
    saved, rate = sf.read(path)
    assert rate == 24000 and 0 < len(saved) < 24000


def test_auto_barge_in_uses_headphones_but_does_not_feed_speaker_echo_back():
    assert not allow_voice_barge_in("auto", "MacBook Pro Speakers")
    assert not allow_voice_barge_in("auto", "External Display Audio")
    assert allow_voice_barge_in("auto", "AirPods Pro")
    assert allow_voice_barge_in("auto", "USB Headset")
    assert allow_voice_barge_in("on", "USB Audio")
    assert not allow_voice_barge_in("off", "AirPods Pro")
