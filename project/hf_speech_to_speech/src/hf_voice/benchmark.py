"""Exercise the real HF audio protocol; synthetic speech is explicitly labeled."""

import asyncio
import base64
import json
import sys
import wave
from types import SimpleNamespace

import numpy as np
import soundfile as sf
import soxr
from websockets.asyncio.client import connect

from .settings import ROOT

FIXTURES = ROOT / "outputs/fixtures"
SENTENCES = [
    "Me llamo Marco. Estoy desarrollando una consultora de AWS. Recuérdalo y salúdame brevemente.",
    "¿Cómo me llamo y en qué proyecto estoy trabajando?",
    "Explícame en cinco frases cómo organizar el proyecto, su arquitectura y sus costos.",
    "Espera, prefiero que solo me digas mi nombre y mi proyecto.",
]


async def prepare_fixtures():
    if all((FIXTURES / f"user-{i}.wav").exists() for i in range(len(SENTENCES))):
        return
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "hf_voice.benchmark")
    if await process.wait():
        raise RuntimeError("No se pudo generar el audio de prueba local.")


def fixtures():
    from mlx_audio.tts.utils import load_model

    from .worker import configure_espeak

    configure_espeak()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    model = load_model("mlx-community/Kokoro-82M-bf16")
    for index, text in enumerate(SENTENCES):
        segments = list(model.generate(text, voice="ef_dora", lang_code="e", speed=1.05))
        sf.write(
            FIXTURES / f"user-{index}.wav",
            np.concatenate([np.asarray(part.audio).reshape(-1) for part in segments]),
            segments[0].sample_rate,
        )
    print("Audio sintético de prueba generado localmente.", flush=True)


async def send_audio(ws, index):
    samples, rate = sf.read(FIXTURES / f"user-{index}.wav", dtype="float32")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    samples = soxr.resample(samples, rate, 16000)
    samples = np.concatenate([np.zeros(2560), samples, np.zeros(16000)])
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    deadline = asyncio.get_running_loop().time()
    for offset in range(0, len(pcm), 1024):
        await ws.send(
            json.dumps(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(pcm[offset : offset + 1024]).decode(),
                }
            )
        )
        deadline += 0.032
        await asyncio.sleep(max(0, deadline - asyncio.get_running_loop().time()))


async def benchmark(session):
    results = {
        "input": "synthetic Spanish Kokoro WAV, paced in real time",
        "hardware_audio_test": False,
        "turns": [],
    }
    async with connect(session.data["runtime"]["client"]["url"], max_size=8 * 1024 * 1024) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "type": "realtime",
                        "extensions": ["speech_to_speech.input_audio_transcription.snapshot"],
                        "instructions": session.data["blocks"]["llm"]["settings"][
                            "init_chat_prompt"
                        ],
                        "audio": {
                            "input": {
                                "turn_detection": {"type": "server_vad", "interrupt_response": True}
                            },
                            "output": {"voice": session.data["runtime"]["client"]["voice"]},
                        },
                    },
                }
            )
        )
        while True:
            event = json.loads(await asyncio.wait_for(ws.recv(), 30))
            if event["type"] == "error":
                raise RuntimeError(event)
            if event["type"] == "session.updated":
                break

        async def receive(cancel=False):
            audio, text, transcript = bytearray(), "", ""
            partials, live_partials, stopped = 0, 0, False
            cancelled = False
            async with asyncio.timeout(120):
                while True:
                    event = json.loads(await ws.recv())
                    kind = event["type"]
                    if kind == "input_audio_buffer.speech_stopped":
                        stopped = True
                    if kind == "speech_to_speech.input_audio_transcription.snapshot":
                        partials += 1
                        if not stopped:
                            live_partials += 1
                    if kind == "error":
                        raise RuntimeError(event)
                    if kind == "conversation.item.input_audio_transcription.completed":
                        transcript = event.get("transcript", "")
                    if kind == "response.output_audio.delta":
                        audio.extend(base64.b64decode(event["delta"]))
                        if cancel and not cancelled:
                            await ws.send(json.dumps({"type": "response.cancel"}))
                            cancelled = True
                    if kind == "response.output_audio_transcript.delta":
                        text += event["delta"]
                    if kind == "response.done":
                        return {
                            "status": event["response"]["status"],
                            "text": text,
                            "transcript": transcript,
                            "audio": audio,
                            "transcript_partials": partials,
                            "partials_before_speech_stopped": live_partials,
                        }

        for index in range(4):
            receiving = asyncio.create_task(receive(cancel=index == 2))
            try:
                await send_audio(ws, index)
                result = await receiving
            finally:
                if not receiving.done():
                    receiving.cancel()
                await asyncio.gather(receiving, return_exceptions=True)
            audio = result.pop("audio")
            with wave.open(
                str(session.measurements.path / f"assistant-{index}.wav"), "wb"
            ) as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(audio)
            result["audio_seconds"] = len(audio) / 32000
            results["turns"].append(result)
            print(f"Turno {index + 1}: {result['status']} · {result['text']}", flush=True)

    turns = results["turns"]
    results["checks"] = {
        "spanish_audio_input": all(turn["transcript"] for turn in turns),
        "live_transcription": all(turn["partials_before_speech_stopped"] > 0 for turn in turns),
        "audible_response": all(
            turn["audio_seconds"] > (0 if turn["status"] == "cancelled" else 1) for turn in turns
        ),
        "speech_duration": all(
            turn["audio_seconds"] <= max(6, len(turn["text"].split()) * 1.2 + 2)
            for turn in turns
            if turn["status"] == "completed"
        ),
        "context": "marco" in turns[1]["text"].lower() and "aws" in turns[1]["text"].lower(),
        "explicit_cancel": turns[2]["status"] == "cancelled",
        "recovery": turns[3]["status"] == "completed" and "marco" in turns[3]["text"].lower(),
    }
    (session.measurements.path / "benchmark.json").write_text(json.dumps(results, indent=2) + "\n")
    if not all(results["checks"].values()):
        raise RuntimeError(f"Benchmark incompleto: {results['checks']}")
    await asyncio.sleep(0.1)
    await benchmark_voice(session)
    print(f"Audio, contexto, cancelación y recuperación: OK. {results['checks']}", flush=True)


async def benchmark_voice(session):
    """Use the same client event handler, draining playback at real audio speed."""
    from speech_to_speech.api.openai_realtime.audio_client import build_session_update

    from .audio import MicrophoneClient

    client = MicrophoneClient(
        session.data["runtime"]["client"]["url"],
        blocked=False,
        instructions=session.data["blocks"]["llm"]["settings"]["init_chat_prompt"],
        voice=session.data["runtime"]["client"]["voice"],
    )
    cleared = 0
    responses = []
    answer = ""
    sender = interruption = None
    started = detected = None

    async def drain():
        while True:
            client.output_callback(
                bytearray(1024), 512, SimpleNamespace(currentTime=0, outputBufferDacTime=0), None
            )
            await asyncio.sleep(0.032)

    async def interrupt(ws):
        nonlocal started
        await asyncio.sleep(0.5)
        started = asyncio.get_running_loop().time() + 0.16  # Remove fixture's silent lead-in.
        await send_audio(ws, 1)

    draining = asyncio.create_task(drain())
    try:
        async with connect(client.config.url, max_size=8 * 1024 * 1024) as ws:
            client.ws = ws
            await ws.send(json.dumps(build_session_update(client.config)))
            async with asyncio.timeout(120):
                async for message in ws:
                    event = json.loads(message)
                    kind = event["type"]
                    if kind == "session.updated":
                        sender = asyncio.create_task(send_audio(ws, 0))
                    if kind == "input_audio_buffer.speech_started" and started is not None:
                        cleared = client.playback.buffered_bytes
                        detected = asyncio.get_running_loop().time()
                    client.handle_event(event)
                    if kind == "response.output_audio.delta" and interruption is None:
                        # Uplink 0 has finished before the assistant can produce audio.
                        if sender:
                            await sender
                        interruption = asyncio.create_task(interrupt(ws))
                    if kind == "response.output_audio_transcript.delta":
                        answer += event["delta"]
                    if kind == "response.done":
                        responses.append(event["response"]["status"])
                        if len(responses) == 2:
                            break
            if interruption:
                await interruption
    finally:
        tasks = [task for task in (draining, sender, interruption) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    result = {
        "input": "synthetic Spanish speech over native Realtime audio",
        "hardware_audio_test": False,
        "response_statuses": responses,
        "discarded_playback_seconds": cleared / 32000,
        "voice_onset_to_playback_clear_ms": (detected - started) * 1000
        if detected is not None and started is not None
        else None,
        "context": "marco" in answer.lower() and "aws" in answer.lower(),
    }
    (session.measurements.path / "voice-interruption.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    if cleared <= 0 or not result["context"] or responses[-1] != "completed":
        raise RuntimeError(f"La interrupción por voz no pasó: {result}")
    print(f"Interrupción por voz: {result}", flush=True)


if __name__ == "__main__":
    fixtures()
