import math
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from .config import Vad
from .contracts import FRAME_SAMPLES, SAMPLE_RATE, AudioFrame, Utterance


class Silero:
    def __init__(self):
        from silero_vad import load_silero_vad

        self.model = load_silero_vad(onnx=True)

    def probability(self, samples: np.ndarray) -> float:
        import torch

        return float(self.model(torch.from_numpy(samples), SAMPLE_RATE).item())

    def reset(self):
        self.model.reset_states()


@dataclass
class Detection:
    started: bool = False
    utterance: Utterance | None = None


class EndpointDetector:
    """512-sample mono frames, hysteresis, onset debounce and bounded utterances."""

    def __init__(self, config: Vad):
        self.config = config
        self.pre = deque(maxlen=math.ceil(config.pre_roll_ms / 32))
        self.reset()

    def reset(self):
        self.pre.clear()
        self.frames: list[AudioFrame] = []
        self.candidate = 0
        self.voiced = 0
        self.active = False
        self.last_voice = 0.0

    def feed(self, frame: AudioFrame, probability: float) -> Detection:
        if frame.samples.shape != (FRAME_SAMPLES,) or not np.isfinite(frame.samples).all():
            raise ValueError("AudioFrame requiere 512 muestras mono float32 finitas a 16 kHz.")
        end = frame.captured_at + FRAME_SAMPLES / SAMPLE_RATE
        started = False
        if not self.active:
            self.pre.append(frame)
            self.candidate = self.candidate + 1 if probability >= self.config.threshold else 0
            if self.candidate * 32 < self.config.onset_ms:
                return Detection()
            self.active = started = True
            self.frames = list(self.pre)
            self.voiced = self.candidate
            self.last_voice = end
        else:
            self.frames.append(frame)
            if probability >= self.config.release_threshold:
                self.voiced += 1
                self.last_voice = end
        expired = end - self.frames[0].captured_at >= self.config.max_utterance_seconds
        silent = (end - self.last_voice) * 1000 >= self.config.silence_ms - 1e-6
        if not (expired or silent):
            return Detection(started=started)
        utterance = None
        if self.voiced * 32 >= self.config.min_speech_ms:
            utterance = Utterance(
                np.concatenate([f.samples for f in self.frames]),
                self.frames[0].captured_at,
                self.last_voice,
                time.perf_counter(),
            )
        self.reset()
        return Detection(started=started, utterance=utterance)
