import json

from hf_voice.telemetry import LATENCY_KEY, Measurements


def test_native_timing_status_and_no_transcripts(tmp_path):
    metrics = Measurements(tmp_path)
    metrics.observe(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "transcript": "private words",
        }
    )
    metrics.observe({"type": "input_audio_buffer.speech_stopped"})
    metrics.observe({"type": "response.created", "response": {"id": "a"}})
    metrics.observe({"type": "response.output_audio.delta", "response_id": "a"})
    metrics.observe(
        {
            "type": "response.done",
            "response": {
                "id": "a",
                "status": "completed",
                "metadata": {LATENCY_KEY: json.dumps({"e2e_s": 1.5, "stt_s": 0.3})},
            },
        }
    )
    metrics.observe(
        {"type": "response.done", "response": {"id": "b", "status": "cancelled", "metadata": {}}}
    )
    summary = metrics.finish()
    assert summary["server_speech_end_to_audio_median_ms"] == 1500
    assert summary["cancelled"] == 1
    assert metrics.turns[0]["client_speech_stopped_to_audio_ms"] >= 0
    assert "private words" not in (metrics.path / "turns.jsonl").read_text()
