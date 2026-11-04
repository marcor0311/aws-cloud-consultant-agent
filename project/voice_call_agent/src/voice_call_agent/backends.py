import asyncio
import ctypes.util
import json
import os
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np

from .config import Config
from .contracts import AudioChunk, TurnToken


def espeak_library() -> str | None:
    configured = os.environ.get("PHONEMIZER_ESPEAK_LIBRARY")
    candidates = [
        configured,
        "/opt/homebrew/lib/libespeak-ng.dylib",
        "/usr/local/lib/libespeak-ng.dylib",
        ctypes.util.find_library("espeak-ng"),
    ]
    return next((str(p) for p in candidates if p and Path(p).exists()), None)


def espeak_data(library: str) -> Path:
    configured = os.environ.get("PHONEMIZER_ESPEAK_DATA_PATH")
    data = Path(configured) if configured else Path(library).parent.parent / "share/espeak-ng-data"
    if not (data / "phontab").is_file():
        raise RuntimeError(
            "No se encontraron los datos de eSpeak NG. Ejecuta brew install espeak-ng."
        )
    return data


class Whisper:
    def __init__(self, model: str):
        self.model = model
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx-whisper")
        self.peak_mlx_bytes = 0

    def _transcribe(self, samples):
        import mlx.core as mx
        import mlx_whisper

        result = mlx_whisper.transcribe(
            samples,
            path_or_hf_repo=self.model,
            language="es",
            task="transcribe",
            temperature=0.0,
            condition_on_previous_text=False,
            verbose=None,
        )
        get_peak = getattr(mx, "get_peak_memory", None)
        if get_peak:
            self.peak_mlx_bytes = max(self.peak_mlx_bytes, get_peak())
        return result["text"].strip()

    async def transcribe(self, samples):
        return await asyncio.get_running_loop().run_in_executor(
            self.pool, self._transcribe, samples
        )

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)


class Ollama:
    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.AsyncClient(
            base_url=config.models.ollama_url,
            timeout=httpx.Timeout(120, connect=5),
            trust_env=False,
        )
        self.stats: dict = {}

    async def stream(self, messages) -> AsyncIterator[str]:
        self.stats = {}
        c = self.config.conversation
        body = {
            "model": self.config.models.ollama,
            "messages": messages,
            "stream": True,
            "think": False,
            "keep_alive": "5m",
            "options": {
                "num_ctx": c.context_tokens,
                "num_predict": c.max_response_tokens,
                "temperature": c.temperature,
            },
        }
        async with self.client.stream("POST", "/api/chat", json=body) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if "error" in event:
                    raise RuntimeError(event["error"])
                content = event.get("message", {}).get("content", "")
                if content:
                    yield content
                if event.get("done"):
                    self.stats = {
                        k: event[k]
                        for k in (
                            "eval_count",
                            "eval_duration",
                            "prompt_eval_count",
                            "load_duration",
                        )
                        if k in event
                    }

    async def warmup(self):
        async for _ in self.stream([{"role": "user", "content": "Di solo: listo."}]):
            pass

    async def close(self):
        await self.client.aclose()


class Kokoro:
    def __init__(self, config: Config):
        self.config = config
        self.pipeline = None
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kokoro")

    def _synthesize(self, text: str, token: TurnToken):
        if token.cancelled.is_set():
            return []
        if self.pipeline is None:
            library = espeak_library()
            if not library:
                raise RuntimeError("Falta eSpeak NG de Homebrew: brew install espeak-ng")
            import torch
            from kokoro import KPipeline
            from phonemizer.backend.espeak.wrapper import EspeakWrapper

            # Misaki selects its bundled loader at import time. Override both paths
            # afterwards so macOS uses the matching Homebrew library AND voice data.
            EspeakWrapper.set_library(library)
            EspeakWrapper.set_data_path(str(espeak_data(library)))
            torch.set_num_threads(self.config.models.torch_threads)
            self.pipeline = KPipeline(lang_code="e", repo_id="hexgrad/Kokoro-82M", device="cpu")
        chunks = []
        for graphemes, _, audio in self.pipeline(
            text, voice=self.config.models.voice, speed=self.config.models.tts_speed
        ):
            if token.cancelled.is_set():
                break
            if audio is not None:
                samples = audio.detach().cpu().numpy().astype(np.float32, copy=True)
                chunks.append(AudioChunk(samples, 24000, graphemes))
        return chunks

    async def synthesize(self, text, token):
        chunks = await asyncio.get_running_loop().run_in_executor(
            self.pool, self._synthesize, text, token
        )
        for chunk in chunks:
            if token.cancelled.is_set():
                break
            yield chunk

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
