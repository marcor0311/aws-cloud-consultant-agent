import threading
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512


@dataclass
class AudioFrame:
    samples: np.ndarray
    captured_at: float  # perf_counter, instante del primer sample
    discontinuity: bool = False


@dataclass
class Utterance:
    samples: np.ndarray
    started_at: float
    speech_ended_at: float
    detected_at: float


@dataclass
class AudioChunk:
    samples: np.ndarray
    sample_rate: int = 24000
    text: str = ""


@dataclass
class TurnToken:
    number: int
    cancelled: threading.Event = field(default_factory=threading.Event)
    reason: str | None = None

    def cancel(self, reason: str):
        self.reason = reason
        self.cancelled.set()


@dataclass
class Playback:
    completed: bool
    started_at: float | None
    played_seconds: float


class AudioSource(Protocol):
    def __aiter__(self) -> AsyncIterator[AudioFrame]: ...


class AudioSink(Protocol):
    @property
    def is_playing(self) -> bool: ...

    async def play(
        self, audio: AudioChunk, token: TurnToken, on_start: Callable[[float], None] | None = None
    ) -> Playback: ...
    def interrupt(self) -> None: ...


class Transcriber(Protocol):
    async def transcribe(self, samples: np.ndarray) -> str: ...


class LanguageModel(Protocol):
    def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]: ...


class Synthesizer(Protocol):
    def synthesize(self, text: str, token: TurnToken) -> AsyncIterator[AudioChunk]: ...
