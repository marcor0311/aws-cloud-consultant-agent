import asyncio
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr

from .contracts import FRAME_SAMPLES, SAMPLE_RATE, AudioChunk, AudioFrame, Playback, TurnToken


def allow_voice_barge_in(mode: str, output_name: str) -> bool:
    if mode != "auto":
        return mode == "on"
    # Without acoustic echo cancellation, only known headset routes are safe
    # for simultaneous microphone detection and agent playback.
    name = output_name.casefold()
    return any(
        word in name
        for word in (
            "headphone",
            "headset",
            "earphone",
            "airpods",
            "auricular",
            "earbud",
            "buds",
            "diadema",
        )
    )


class LocalInput:
    """CoreAudio callback only copies audio; resampling/VAD happen outside it."""

    def __init__(self, device=-1, queue_frames=32):
        self.device = None if device == -1 else device
        self.queue = asyncio.Queue(maxsize=queue_frames)
        self.stream = None
        self.closed = False

    def _enqueue(self, item):
        if self.closed:
            return
        if self.queue.full():
            while not self.queue.empty():
                self.queue.get_nowait()
            item = (*item[:2], True)
        self.queue.put_nowait(item)

    def __enter__(self):
        import sounddevice as sd

        self.loop = asyncio.get_running_loop()
        self.rate = int(sd.query_devices(self.device, "input")["default_samplerate"])

        def callback(indata, frames, timing, status):
            captured = time.perf_counter() + timing.inputBufferAdcTime - timing.currentTime
            self.loop.call_soon_threadsafe(
                self._enqueue, (indata[:, 0].copy(), captured, bool(status.input_overflow))
            )

        self.stream = sd.InputStream(
            device=self.device,
            channels=1,
            dtype="float32",
            samplerate=self.rate,
            blocksize=round(self.rate * 0.02),
            callback=callback,
            latency="low",
        )
        self.stream.start()
        return self

    async def __aiter__(self):
        resampler = soxr.ResampleStream(self.rate, SAMPLE_RATE, 1, dtype="float32", quality="LQ")
        pending = np.empty(0, dtype=np.float32)
        origin, cursor, discontinuity = None, 0, False
        while not self.closed:
            item = await self.queue.get()
            if item is None:
                return
            samples, captured, gap = item
            if origin is None or gap:
                origin, cursor, pending = captured, 0, np.empty(0, dtype=np.float32)
                resampler.clear()
                discontinuity = gap
            converted = resampler.resample_chunk(samples)
            pending = np.concatenate((pending, converted))
            while len(pending) >= FRAME_SAMPLES:
                frame = pending[:FRAME_SAMPLES].copy()
                pending = pending[FRAME_SAMPLES:]
                yield AudioFrame(frame, origin + cursor / SAMPLE_RATE, discontinuity)
                cursor += FRAME_SAMPLES
                discontinuity = False

    def __exit__(self, *_):
        self.closed = True
        if self.stream:
            self.stream.stop()
            self.stream.close()
        while not self.queue.empty():
            self.queue.get_nowait()
        self.queue.put_nowait(None)


class FileInput:
    """Replay actual PCM at wall-clock speed, keeping latency timestamps meaningful."""

    def __init__(self, path: Path):
        self.path = path

    async def __aiter__(self):
        samples, rate = sf.read(self.path, dtype="float32", always_2d=True)
        samples = samples.mean(axis=1)
        if rate != SAMPLE_RATE:
            samples = soxr.resample(samples, rate, SAMPLE_RATE).astype(np.float32)
        # Real silence allows the same streaming endpoint detector to finish its turn.
        samples = np.concatenate(
            (np.zeros(2560, np.float32), samples, np.zeros(SAMPLE_RATE, np.float32))
        )
        samples = np.pad(samples, (0, (-len(samples)) % FRAME_SAMPLES))
        origin = time.perf_counter()
        for offset in range(0, len(samples), FRAME_SAMPLES):
            captured = origin + offset / SAMPLE_RATE
            await asyncio.sleep(
                max(0, captured + FRAME_SAMPLES / SAMPLE_RATE - time.perf_counter())
            )
            yield AudioFrame(samples[offset : offset + FRAME_SAMPLES], captured)


class InterruptingFileInput:
    """Start the second WAV after response audio begins, to exercise actual barge-in."""

    def __init__(self, first: Path, second: Path, output_started: asyncio.Event):
        self.first, self.second, self.output_started = first, second, output_started

    async def __aiter__(self):
        async for frame in FileInput(self.first):
            yield frame
        await asyncio.wait_for(self.output_started.wait(), timeout=30)
        await asyncio.sleep(0.2)
        async for frame in FileInput(self.second):
            yield frame


class WavOutput:
    def __init__(self, path: Path, realtime=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.realtime = realtime
        self.is_playing = False
        self.started = asyncio.Event()
        self.file = sf.SoundFile(path, mode="w", samplerate=24000, channels=1, subtype="PCM_16")

    async def play(self, audio: AudioChunk, token: TurnToken, on_start=None):
        self.is_playing = True
        try:
            return await self._play(audio, token, on_start)
        finally:
            self.is_playing = False

    async def _play(self, audio: AudioChunk, token: TurnToken, on_start=None):
        if token.cancelled.is_set():
            return Playback(False, None, 0)
        if audio.sample_rate != 24000:
            raise ValueError("WavOutput espera audio Kokoro a 24 kHz.")
        started = time.perf_counter()
        if on_start:
            on_start(started)
        self.started.set()
        if not self.realtime:
            self.file.write(audio.samples)
            self.file.flush()
            return Playback(True, started, len(audio.samples) / audio.sample_rate)
        block = audio.sample_rate // 50
        written = 0
        for offset in range(0, len(audio.samples), block):
            if token.cancelled.is_set():
                return Playback(False, started, written / audio.sample_rate)
            part = audio.samples[offset : offset + block]
            self.file.write(part)
            self.file.flush()
            written += len(part)
            await asyncio.sleep(len(part) / audio.sample_rate)
        return Playback(True, started, written / audio.sample_rate)

    def interrupt(self):
        pass  # No queued/hardware playback in a file sink.

    def close(self):
        self.file.close()


@dataclass
class _Pending:
    samples: np.ndarray
    token: TurnToken
    future: asyncio.Future
    on_start: object
    cursor: int = 0
    started_at: float | None = None
    ends_at: float = 0


class LocalOutput:
    def __init__(self, device=-1, echo_tail_ms=350):
        self.device = None if device == -1 else device
        self.lock = threading.Lock()
        self.current: _Pending | None = None
        self.stream = None
        self.echo_tail = echo_tail_ms / 1000
        self._mute_until = 0.0

    @property
    def is_playing(self):
        with self.lock:
            return self.current is not None or time.perf_counter() < self._mute_until

    @property
    def input_resume_at(self):
        with self.lock:
            return self._mute_until

    def _resolve(self, job, completed):
        if not job.future.done():
            job.future.set_result(Playback(completed, job.started_at, job.cursor / self.rate))

    def __enter__(self):
        import sounddevice as sd

        self.loop = asyncio.get_running_loop()
        info = sd.query_devices(self.device, "output")
        self.name = info["name"]
        self.rate = int(info["default_samplerate"])

        def callback(outdata, frames, timing, status):
            outdata.fill(0)
            with self.lock:
                job = self.current
                if job is None:
                    return
                if job.token.cancelled.is_set():
                    self.current = None
                    self.loop.call_soon_threadsafe(self._resolve, job, False)
                    return
                count = min(frames, len(job.samples) - job.cursor)
                scheduled = time.perf_counter() + max(
                    0, timing.outputBufferDacTime - timing.currentTime
                )
                if job.started_at is None:
                    job.started_at = scheduled
                    if job.on_start:
                        self.loop.call_soon_threadsafe(job.on_start, scheduled)
                outdata[:count, 0] = job.samples[job.cursor : job.cursor + count]
                job.cursor += count
                job.ends_at = scheduled + count / self.rate
                self._mute_until = max(self._mute_until, job.ends_at + self.echo_tail)
                if job.cursor == len(job.samples):
                    self.current = None
                    self.loop.call_soon_threadsafe(self._resolve, job, True)

        self.stream = sd.OutputStream(
            device=self.device,
            channels=1,
            dtype="float32",
            samplerate=self.rate,
            blocksize=256,
            callback=callback,
            latency="low",
        )
        self.stream.start()
        return self

    async def play(self, audio, token, on_start=None):
        if token.cancelled.is_set() or not len(audio.samples):
            return Playback(False, None, 0)
        samples = audio.samples
        if audio.sample_rate != self.rate:
            samples = await asyncio.to_thread(soxr.resample, samples, audio.sample_rate, self.rate)
        if token.cancelled.is_set():
            return Playback(False, None, 0)
        job = _Pending(
            np.asarray(samples, dtype=np.float32), token, self.loop.create_future(), on_start
        )
        with self.lock:
            if self.current is not None:
                raise RuntimeError("LocalOutput acepta un único reproductor a la vez.")
            self.current = job
        try:
            result = await job.future
            # The callback acknowledges submission; wait for the scheduled DAC end.
            await asyncio.sleep(max(0, job.ends_at - time.perf_counter()))
            return Playback(
                result.completed and not token.cancelled.is_set(),
                result.started_at,
                result.played_seconds,
            )
        finally:
            with self.lock:
                if self.current is job:
                    self.current = None

    def interrupt(self):
        with self.lock:
            job, self.current = self.current, None
        if job:
            self.loop.call_soon_threadsafe(self._resolve, job, False)

    def __exit__(self, *_):
        self.interrupt()
        if self.stream:
            self.stream.abort()
            self.stream.close()
