"""Back-transcribe synthetic benchmark responses to catch unintelligible TTS output."""

import json
import re
import sys
import unicodedata
from pathlib import Path


def words(text):
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return re.findall(r"\w+", normalized)


def similarity(reference, transcript):
    expected, actual = words(reference), words(transcript)
    row = list(range(len(actual) + 1))
    for i, word in enumerate(expected, 1):
        updated = [i]
        for j, candidate in enumerate(actual, 1):
            updated.append(min(updated[-1] + 1, row[j] + 1, row[j - 1] + (word != candidate)))
        row = updated
    return max(0.0, 1 - row[-1] / max(len(expected), len(actual), 1))


def check(path):
    import mlx.core as mx
    import soundfile as sf
    import soxr
    from lightning_whisper_mlx import LightningWhisperMLX

    mx.set_cache_limit(256 * 1024**2)
    model = LightningWhisperMLX(model="small", batch_size=1, quant=None)
    benchmark = json.loads((path / "benchmark.json").read_text())
    results = []
    for index, turn in enumerate(benchmark["turns"]):
        if turn["status"] != "completed":
            continue
        audio, rate = sf.read(path / f"assistant-{index}.wav", dtype="float32")
        if rate != 16000:
            audio = soxr.resample(audio, rate, 16000)
        result = model.transcribe(audio, language="es")
        transcript = result["text"].strip()
        score = similarity(turn["text"], transcript)
        results.append(
            {
                "turn": index + 1,
                "reference": turn["text"],
                "back_transcription": transcript,
                "word_similarity": score,
                "passed": score >= 0.55,
            }
        )
    report = {
        "method": "synthetic TTS → independent Whisper decoding; lexical comparison",
        "not_a_subjective_naturalness_score": True,
        "turns": results,
        "passed": bool(results) and all(item["passed"] for item in results),
    }
    (path / "tts-roundtrip.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        "Verificación del texto pronunciado:",
        [round(item["word_similarity"], 2) for item in results],
        flush=True,
    )
    if not report["passed"]:
        raise RuntimeError(
            f"La voz no reproduce el texto esperado. Revisa {path / 'tts-roundtrip.json'}"
        )


if __name__ == "__main__":
    check(Path(sys.argv[1]).resolve())
