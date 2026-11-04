import argparse
import asyncio
import importlib.metadata
import json
import platform
import shutil
import sys
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

from .audio import (
    FileInput,
    InterruptingFileInput,
    LocalInput,
    LocalOutput,
    WavOutput,
    allow_voice_barge_in,
)
from .backends import Kokoro, Ollama, Whisper, espeak_library
from .config import Config
from .contracts import TurnToken
from .engine import ConversationEngine
from .metrics import MemorySampler, Recorder
from .vad import Silero


def show_event(kind, values):
    if kind in {"user", "assistant"}:
        print(f"{'Tú' if kind == 'user' else 'Agente'}: {values['text']}", flush=True)
    elif kind == "interrupted":
        print("[Respuesta detenida]", flush=True)
    elif kind == "error":
        print(f"Error de turno: {values['error']}", flush=True)
    elif kind == "metrics":
        first = values.get("first_audio_ms")
        value = f"{first:.0f} ms" if first is not None else "sin audio"
        print(
            f"[Turno {values['turn']} · {values['status']} · primera salida: {value}]", flush=True
        )


@contextmanager
def enter_to_interrupt(engine):
    """Read terminal Enter without an uncancellable input() executor thread."""
    if sys.stdin is None or not sys.stdin.isatty():
        yield False
        return
    loop, descriptor = asyncio.get_running_loop(), sys.stdin.fileno()

    def pressed():
        if sys.stdin.readline() == "":
            loop.remove_reader(descriptor)
        else:
            engine.interrupt("manual_interrupt")

    try:
        loop.add_reader(descriptor, pressed)
    except (OSError, ValueError, NotImplementedError):
        yield False
        return
    try:
        yield True
    finally:
        loop.remove_reader(descriptor)


@asynccontextmanager
async def runtime(config, sink_kind):
    metadata = {
        "python": platform.python_version(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "model": config.models.ollama,
        "whisper": config.models.whisper,
        "voice": config.models.voice,
        "sink": sink_kind,
        "context_tokens": config.conversation.context_tokens,
    }
    recorder = Recorder(config.metrics.directory, metadata)
    sampler = MemorySampler(recorder, config.models.ollama_url, config.metrics.sample_seconds)
    sampler.start()
    stt, tts, llm, engine = Whisper(config.models.whisper), Kokoro(config), Ollama(config), None
    try:
        started = time.perf_counter()
        print("Preparando Silero, Whisper MLX, Kokoro y Qwen local…", flush=True)
        vad = Silero()
        async for _ in tts.synthesize(
            "Hola. La conversación en español está preparada.", TurnToken(0)
        ):
            pass
        await stt.transcribe(np.zeros(16000, dtype=np.float32))
        await llm.warmup()
        recorder.event("warmup", duration_ms=(time.perf_counter() - started) * 1000)

        def make_engine(output, *, allow_barge_in=True):
            nonlocal engine
            engine = ConversationEngine(
                config,
                vad,
                stt,
                llm,
                tts,
                output,
                recorder,
                show_event,
                allow_barge_in=allow_barge_in,
            )
            return engine

        yield recorder, tts, make_engine
    finally:
        if engine:
            await engine.close()
        await llm.close()
        stt.close()
        tts.close()
        memory = sampler.stop()
        memory["mlx_peak_allocated_mib"] = stt.peak_mlx_bytes / (1024**2)
        report = recorder.finish(memory)
        print(f"Métricas: {recorder.directory / 'summary.json'}", flush=True)
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


async def doctor(config, as_json):
    checks = {
        "macos_arm64": platform.system() == "Darwin" and platform.machine() == "arm64",
        "python_312": platform.python_version_tuple()[:2] == ("3", "12"),
        "homebrew": shutil.which("brew"),
        "espeak_library": espeak_library(),
    }
    versions = {}
    for package in [
        "silero-vad",
        "mlx-whisper",
        "kokoro",
        "onnxruntime",
        "sounddevice",
        "soundfile",
        "soxr",
        "psutil",
        "torch",
    ]:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            checks[f"package_{package}"] = False
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get(config.models.ollama_url + "/api/tags")
            response.raise_for_status()
        names = {model["name"] for model in response.json()["models"]}
        checks["ollama_running"] = True
        checks["qwen_downloaded"] = config.models.ollama in names
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        checks["ollama_running"] = False
        checks["ollama_error"] = str(exc)
    ok = all(value for key, value in checks.items() if key != "ollama_error")
    result = {"ok": bool(ok), "checks": checks, "versions": versions}
    print(
        json.dumps(result, indent=2)
        if as_json
        else "\n".join(f"{key}: {value}" for key, value in checks.items())
    )
    return 0 if ok else 1


async def execute(args, config):
    if args.command == "doctor":
        return await doctor(config, args.json)
    if args.command == "devices":
        import sounddevice as sd

        print(sd.query_devices())
        return 0
    if args.command == "prepare":
        async with runtime(config, "none"):
            print("Modelos preparados. No se ha abierto el micrófono.")
        return 0
    if args.command == "chat":
        async with runtime(config, "coreaudio_dac_scheduled") as (recorder, _, make_engine):
            with (
                LocalOutput(
                    args.output_device
                    if args.output_device is not None
                    else config.audio.output_device,
                    echo_tail_ms=config.audio.echo_tail_ms,
                ) as output,
                LocalInput(
                    args.input_device
                    if args.input_device is not None
                    else config.audio.input_device,
                    config.audio.queue_frames,
                ) as source,
            ):
                mode = args.barge_in_mode or config.audio.barge_in_mode
                voice_interrupt = allow_voice_barge_in(mode, output.name)
                recorder.event(
                    "audio_route",
                    output_device=output.name,
                    voice_barge_in=voice_interrupt,
                    requested_mode=mode,
                    echo_tail_ms=config.audio.echo_tail_ms,
                )
                engine = make_engine(output, allow_barge_in=voice_interrupt)
                with enter_to_interrupt(engine) as keyboard_available:
                    print(f"Salida: {output.name}")
                    if voice_interrupt:
                        print("Puedes interrumpir al agente hablando.")
                    else:
                        print("Modo altavoces: la escucha se reanuda al terminar cada respuesta.")
                    if keyboard_available:
                        print("Pulsa Enter para cortar la respuesta y después hablar.")
                    print("Escuchando en español. Ctrl+C para terminar.")
                    try:
                        await engine.run(source)
                    finally:
                        await engine.close()
        return 0
    if args.command == "benchmark":
        sink_kind = "wav_realtime_simulation" if args.barge_in else "wav_file_available_not_audible"
        async with runtime(config, sink_kind) as (
            recorder,
            tts,
            make_engine,
        ):
            output = WavOutput(recorder.directory / "assistant.wav", realtime=args.barge_in)
            try:
                engine = make_engine(output)
                files = args.input or []
                if not files:
                    prompts = args.prompt or [
                        "Me llamo Marco. Estoy preparando una consultora de arquitectura en AWS.",
                        "¿Cómo me llamo y de qué proyecto estamos hablando?",
                    ]
                    for index, prompt in enumerate(prompts):
                        chunks = []
                        async for audio in tts.synthesize(prompt, TurnToken(-1)):
                            chunks.append(audio.samples)
                        if not chunks:
                            raise RuntimeError("Kokoro no generó la frase de prueba.")
                        path = recorder.directory / f"input-{index + 1}.wav"
                        sf.write(path, np.concatenate(chunks), 24000)
                        files.append(path)
                if args.barge_in:
                    if len(files) != 2:
                        raise ValueError("--barge-in requiere exactamente dos entradas.")
                    await engine.run(InterruptingFileInput(files[0], files[1], output.started))
                    if recorder.event_count < 1:
                        raise RuntimeError("La segunda intervención no interrumpió la primera.")
                else:
                    for path in files:
                        engine.vad.reset()
                        engine.detector.reset()
                        await engine.run(FileInput(path))
                if engine.last_error:
                    raise RuntimeError(engine.last_error)
                if not recorder.turns or not any(t["first_audio_ms"] for t in recorder.turns):
                    raise RuntimeError("No se obtuvo voz de respuesta; revisa el audio y el VAD.")
                if not args.input and not args.prompt:
                    answer = engine.history.items[-1]["content"].casefold()
                    remembered = "marco" in answer and ("aws" in answer or "amazon" in answer)
                    recorder.event("context_check", passed=remembered)
                    if not remembered:
                        raise RuntimeError(
                            "El modelo no recuperó el nombre y el proyecto del historial."
                        )
            finally:
                await engine.close()
                output.close()
        return 0
    raise ValueError(f"Comando desconocido: {args.command}")


def main():
    parser = argparse.ArgumentParser(
        description="Conversación de voz local en español para Apple Silicon"
    )
    parser.add_argument(
        "--config", type=Path, help="Archivo TOML; por defecto config.toml del directorio actual"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare", help="Descargar y calentar modelos sin abrir el micrófono")
    check = commands.add_parser("doctor", help="Diagnóstico de dependencias y Ollama")
    check.add_argument("--json", action="store_true")
    commands.add_parser("devices", help="Listar dispositivos de entrada y salida")
    chat = commands.add_parser("chat", help="Conversación con micrófono y auriculares")
    chat.add_argument("--input-device", type=int)
    chat.add_argument("--output-device", type=int)
    chat.add_argument(
        "--barge-in-mode",
        choices=["auto", "on", "off"],
        help="auto: voz con auriculares, escucha por turnos con altavoces",
    )
    benchmark = commands.add_parser("benchmark", help="Prueba completa con WAV o frases sintéticas")
    benchmark.add_argument(
        "--barge-in",
        action="store_true",
        help="Interrumpir la primera respuesta con la segunda entrada; salida simulada",
    )
    benchmark.add_argument(
        "--input", type=Path, action="append", help="WAV; repetir para varios turnos"
    )
    benchmark.add_argument(
        "--prompt", action="append", help="Frase española para generar un WAV de prueba"
    )
    report = commands.add_parser("report", help="Mostrar el resumen JSON de una sesión")
    report.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "report":
            path = args.path / "summary.json" if args.path.is_dir() else args.path
            print(json.dumps(json.loads(path.read_text()), ensure_ascii=False, indent=2))
            return
        path = args.config or (Path("config.toml") if Path("config.toml").exists() else None)
        config = Config.load(path)
        raise SystemExit(asyncio.run(execute(args, config)))
    except KeyboardInterrupt:
        print("Conversación finalizada.")
    except (OSError, RuntimeError, ValueError, httpx.HTTPError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
