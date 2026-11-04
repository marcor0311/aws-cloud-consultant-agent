from hf_voice.quality import similarity


def test_roundtrip_ignores_punctuation_and_accents():
    assert similarity("¡Hola, Marco! ¿Cómo estás?", "hola marco como estas") == 1


def test_roundtrip_rejects_noise_and_missing_speech():
    assert similarity("Hola Marco, podemos revisar tu proyecto.", "jajajajaja") == 0
    assert similarity("Hola Marco, podemos revisar tu proyecto.", "") == 0
    assert (
        similarity(
            "Hola Marco, podemos revisar tu proyecto.", "Hola Marcos podemos revisar tu proyecto"
        )
        > 0.55
    )
