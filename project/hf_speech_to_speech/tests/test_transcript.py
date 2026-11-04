from io import StringIO

from rich.console import Console

from hf_voice.audio import MicrophoneClient
from hf_voice.transcript import TranscriptDisplay


def display():
    output = StringIO()
    return TranscriptDisplay(Console(file=output, force_terminal=False, width=120)), output


def test_snapshots_replace_previous_hypothesis_and_final_is_unique():
    renderer, output = display()
    renderer.update("Tú", "a", "Me llamo")
    assert "Me llamo" in output.getvalue()  # Visible before finalization.
    renderer.update("Tú", "a", "Me llamo Marco")
    assert renderer.texts[("Tú", "a")] == "Me llamo Marco"
    renderer.update("Tú", "a", "Me llamo Marco.", final=True)
    renderer.update("Tú", "a", "Me llamo Marco.", final=True)
    renderer.update("Tú", "a", "out of order snapshot")
    assert output.getvalue().count("Marco.") == 1
    assert "out of order" not in output.getvalue()


def test_client_renders_user_and_agent_before_done_events():
    client = MicrophoneClient("ws://127.0.0.1:1/v1/realtime")
    client.transcript, output = display()
    client.handle_event(
        {
            "type": "speech_to_speech.input_audio_transcription.snapshot",
            "item_id": "u",
            "transcript": "Hola",
        }
    )
    client.handle_event(
        {
            "type": "response.output_audio_transcript.delta",
            "response_id": "r",
            "item_id": "a",
            "delta": "Hola, ",
        }
    )
    client.handle_event(
        {
            "type": "response.output_audio_transcript.delta",
            "response_id": "r",
            "item_id": "a",
            "delta": "Marco.",
        }
    )
    assert "Tú: Hola" in output.getvalue()
    assert "Agente: Hola, Marco." in output.getvalue()
    assert client.transcript.texts[("Agente", "a")] == "Hola, Marco."


async def test_manual_interrupt_preserves_partial_as_interrupted():
    client = MicrophoneClient("ws://127.0.0.1:1/v1/realtime")
    client.transcript, output = display()
    client.handle_event(
        {"type": "response.output_audio_transcript.delta", "response_id": "r", "delta": "Ya tengo"}
    )
    await client.cancel()
    assert "Ya tengo (interrumpido)" in output.getvalue()


def test_snapshots_and_committed_deltas_do_not_duplicate_words():
    client = MicrophoneClient("ws://127.0.0.1:1/v1/realtime")
    client.transcript, output = display()
    for event in [
        {"type": "speech_to_speech.input_audio_transcription.snapshot", "transcript": "Hola Marco"},
        {"type": "conversation.item.input_audio_transcription.delta", "delta": "Hola "},
        {"type": "conversation.item.input_audio_transcription.delta", "delta": "Marco"},
    ]:
        client.handle_event({**event, "item_id": "u"})
    assert client.transcript.texts[("Tú", "u")] == "Hola Marco"
    assert "Hola MarcoHola" not in output.getvalue()
    client.handle_event(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "u",
            "transcript": "Hola, Marco.",
        }
    )
    assert not client.user_deltas and not client.user_snapshots


def test_output_panel_does_not_repeat_identical_final_line():
    renderer, output = display()
    renderer.update("Agente", "a", "Hola, Marco.")
    renderer.update("Agente", "a", "Hola, Marco.", final=True)
    assert output.getvalue().count("Agente: Hola, Marco.") == 1


def test_ide_dumb_terminal_emits_partial_immediately(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    output = StringIO()
    renderer = TranscriptDisplay(Console(file=output, force_terminal=True))
    renderer.update("Tú", "u", "Ya estoy hablando")
    assert "Ya estoy hablando" in output.getvalue()
    assert renderer.live is None
