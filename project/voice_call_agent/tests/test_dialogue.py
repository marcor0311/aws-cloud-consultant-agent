import pytest

from voice_call_agent.config import Config
from voice_call_agent.dialogue import History, PhraseBuffer


def test_bounded_history_preserves_current_question_and_system():
    history = History("Habla español", max_turns=2, max_characters=80)
    for i in range(8):
        history.add("user", f"Pregunta {i}")
        history.add("assistant", f"Respuesta {i}")
    messages = history.messages()
    assert messages[0] == {"role": "system", "content": "Habla español"}
    assert messages[1]["role"] == "user"
    assert len(messages) <= 5
    assert sum(len(m["content"]) for m in messages[1:]) <= 80
    assert messages[-1]["content"] == "Respuesta 7"
    messages[-1]["content"] = "mutated"
    assert history.messages()[-1]["content"] == "Respuesta 7"


def test_chunking_speaks_before_full_answer_and_does_not_drop_tail():
    buffer = PhraseBuffer(20, 50)
    chunks = []
    text = (
        "La primera explicación termina aquí. La siguiente continúa y ofrece más detalles sin pausa"
    )
    for token in [text[:5], text[5:35], text[35:60], text[60:]]:
        chunks.extend(buffer.feed(token))
    chunks.append(buffer.flush())
    assert all(len(chunk) <= 50 for chunk in chunks)
    assert " ".join(chunks) == text
    assert len(chunks) >= 2


def test_remote_inference_is_rejected(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[models]\nollama_url="https://api.example.com"\n')
    with pytest.raises(ValueError, match="loopback"):
        Config.load(path)


def test_invalid_endpoint_settings_are_rejected(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[vad]\nonset_ms=320\npre_roll_ms=96\n")
    with pytest.raises(ValueError, match="pre-roll"):
        Config.load(path)
