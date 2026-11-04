import argparse
import asyncio
import contextlib
import sys
from importlib.metadata import version
from pathlib import Path

import httpx

from .runtime import ServerSession
from .settings import DEFAULT_PROFILE, ROOT, has_headphones, load_profile


def parser():
    result = argparse.ArgumentParser(
        description="Conversación local con Hugging Face Speech-to-Speech"
    )
    result.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    commands = result.add_subparsers(dest="command", required=True)
    chat = commands.add_parser("chat", help="Micrófono y altavoces con métricas")
    chat.add_argument("--input-device", type=int)
    chat.add_argument("--output-device", type=int)
    chat.add_argument("--barge-in", choices=["auto", "voice", "enter"], default="auto")
    chat.add_argument(
        "--voice",
        choices=["Ryan", "Aiden", "Serena", "Vivian"],
        help="Voz Qwen3-TTS; por defecto usa la del perfil (Ryan)",
    )
    commands.add_parser("devices", help="Dispositivos de audio y sus índices")
    commands.add_parser("doctor", help="Verifica perfil, dependencias y Ollama")
    commands.add_parser("prepare", help="Descarga y prepara los modelos sin abrir el micrófono")
    commands.add_parser("serve", help="Motor sin dispositivos de audio, con protocolo Realtime")
    commands.add_parser("benchmark", help="Prueba de audio, contexto e interrupciones reproducible")
    return result


def block_microphone(mode, output_name):
    return mode == "enter" or (mode == "auto" and not has_headphones(output_name))


async def chat(session, args):
    import sounddevice as sd

    from .audio import MicrophoneClient

    output = sd.query_devices(args.output_device, "output")
    blocked = block_microphone(args.barge_in, output["name"])
    print(f"Salida: {output['name']}. Interrupción: {'Enter' if blocked else 'voz o Enter'}.")
    print(
        "Habla en español. Enter interrumpe; Ctrl+C termina. "
        "Usa audífonos para interrumpir hablando."
    )
    client = MicrophoneClient(
        session.data["runtime"]["client"]["url"],
        blocked=blocked,
        input_device=args.input_device,
        output_device=args.output_device,
        instructions=session.data["blocks"]["llm"]["settings"]["init_chat_prompt"],
        voice=args.voice or session.data["runtime"]["client"]["voice"],
    )
    await client.run()


async def run(args):
    args.profile = args.profile.resolve()
    if args.command == "devices":
        import sounddevice as sd

        print(sd.query_devices())
        return
    if args.command == "doctor":
        data, _, _, llm = load_profile(args.profile)
        print(f"speech-to-speech {version('speech-to-speech')} · Python {sys.version.split()[0]}")
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "hf_voice.worker", str(args.profile), "--validate"
        )
        if await process.wait():
            raise RuntimeError("El perfil no cumple el esquema oficial.")
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            response = await client.get(f"http://{llm.netloc}/api/tags")
            response.raise_for_status()
            names = [model["name"] for model in response.json()["models"]]
            expected = data["blocks"]["llm"]["settings"]["model_name"]
            if expected not in names:
                raise RuntimeError(f"Falta el modelo Ollama {expected}; ejecuta ./setup.sh.")
        from .worker import configure_espeak

        configure_espeak()
        print("Perfil, Ollama y eSpeak NG: OK.")
        return
    if args.command == "benchmark":
        from .benchmark import prepare_fixtures

        await prepare_fixtures()
    async with ServerSession(args.profile, args.command) as session:
        if args.command == "chat":
            await chat(session, args)
        elif args.command == "serve":
            print(f"Motor disponible en {session.data['runtime']['client']['url']}", flush=True)
            await asyncio.Event().wait()
        elif args.command == "benchmark":
            from .benchmark import benchmark

            await benchmark(session)
    if args.command == "benchmark":
        # Free the conversational models before loading independent ASR for validation.
        check = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "hf_voice.quality", str(session.measurements.path), cwd=ROOT
        )
        if await check.wait():
            raise RuntimeError("Falló la comprobación del texto pronunciado por TTS.")


def main():
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(parser().parse_args()))


if __name__ == "__main__":
    main()
