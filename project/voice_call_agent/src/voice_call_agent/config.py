import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class Models:
    whisper: str = "mlx-community/whisper-small-mlx"
    ollama: str = "qwen3:1.7b-q4_K_M"
    ollama_url: str = "http://127.0.0.1:11434"
    voice: str = "ef_dora"
    tts_speed: float = 1.05
    torch_threads: int = 4


@dataclass
class Conversation:
    system_prompt: str = (
        "Responde brevemente en español, sin markdown, usando el historial. "
        "El nombre y los datos del usuario pertenecen al usuario, no a ti. "
        "Responde preguntas sobre lo conversado solo con datos explícitos; "
        "si falta un dato, pide aclaración y no lo inventes."
    )
    context_tokens: int = 4096
    max_response_tokens: int = 160
    temperature: float = 0.2
    history_turns: int = 6
    history_characters: int = 6000
    phrase_min_characters: int = 35
    phrase_max_characters: int = 160


@dataclass
class Vad:
    threshold: float = 0.55
    release_threshold: float = 0.35
    onset_ms: int = 96
    silence_ms: int = 480
    pre_roll_ms: int = 160
    min_speech_ms: int = 256
    max_utterance_seconds: float = 20


@dataclass
class Audio:
    input_device: int = -1
    output_device: int = -1
    queue_frames: int = 32
    barge_in_mode: str = "auto"
    echo_tail_ms: int = 350


@dataclass
class Metrics:
    directory: str = "outputs"
    sample_seconds: float = 0.5


@dataclass
class Config:
    models: Models = field(default_factory=Models)
    conversation: Conversation = field(default_factory=Conversation)
    vad: Vad = field(default_factory=Vad)
    audio: Audio = field(default_factory=Audio)
    metrics: Metrics = field(default_factory=Metrics)

    @classmethod
    def load(cls, path: Path | None = None):
        data = tomllib.loads(path.read_text()) if path else {}
        known = {
            "models": Models,
            "conversation": Conversation,
            "vad": Vad,
            "audio": Audio,
            "metrics": Metrics,
        }
        if data.keys() - known.keys():
            raise ValueError(f"Secciones desconocidas: {data.keys() - known.keys()}")
        result = cls(**{key: model(**data.get(key, {})) for key, model in known.items()})
        host = urlparse(result.models.ollama_url)
        if host.scheme != "http" or host.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Ollama debe usar una dirección HTTP de loopback local.")
        v, c = result.vad, result.conversation
        if not 0 < v.release_threshold <= v.threshold < 1:
            raise ValueError("Umbrales VAD inválidos.")
        if min(v.onset_ms, v.silence_ms, v.pre_roll_ms, v.min_speech_ms) <= 0:
            raise ValueError("Los tiempos del VAD deben ser positivos.")
        if v.pre_roll_ms < v.onset_ms or v.max_utterance_seconds < 1:
            raise ValueError(
                "El pre-roll debe cubrir el inicio de voz y el máximo debe ser >= 1 s."
            )
        if not 0 < c.phrase_min_characters < c.phrase_max_characters:
            raise ValueError("Límites de frases inválidos.")
        if (
            min(
                c.context_tokens,
                c.max_response_tokens,
                c.history_turns,
                c.history_characters,
                result.audio.queue_frames,
            )
            <= 0
        ):
            raise ValueError("Los límites de contexto y colas deben ser positivos.")
        if c.max_response_tokens >= c.context_tokens or result.metrics.sample_seconds < 0.1:
            raise ValueError("Configuración de contexto o frecuencia de métricas inválida.")
        if not 0 <= c.temperature <= 1:
            raise ValueError("La temperatura debe estar entre 0 y 1.")
        if result.models.torch_threads < 1 or not 0.5 <= result.models.tts_speed <= 2:
            raise ValueError("Número de hilos o velocidad TTS inválidos.")
        if not result.models.voice.startswith("e"):
            raise ValueError("Selecciona una voz española de Kokoro: ef_dora, em_alex o em_santa.")
        if result.audio.barge_in_mode not in {"auto", "on", "off"}:
            raise ValueError("barge_in_mode debe ser auto, on u off.")
        if not 0 <= result.audio.echo_tail_ms <= 2000:
            raise ValueError("echo_tail_ms debe estar entre 0 y 2000.")
        return result
