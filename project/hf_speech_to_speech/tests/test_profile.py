import pytest
import yaml

from hf_voice.cli import block_microphone
from hf_voice.settings import DEFAULT_PROFILE, load_profile, loopback


def test_profile_uses_official_apple_backends():
    data, backend, client, _ = load_profile(DEFAULT_PROFILE)
    assert backend == "ws://127.0.0.1:8777"
    assert client.port == 8778
    assert [value["backend"] for value in data["blocks"].values()] == [
        "silero",
        "whisper-mlx",
        "chat-completions",
        "qwen3",
    ]


@pytest.mark.parametrize("url", ["http://example.com", "https://127.0.0.1", "file:///tmp"])
def test_reject_remote_services(url):
    with pytest.raises(ValueError):
        loopback(url, {"http"})


def test_reject_shared_port(tmp_path):
    data = yaml.safe_load(DEFAULT_PROFILE.read_text())
    data["runtime"]["client"]["url"] = "ws://127.0.0.1:8777/v1/realtime"
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="distintos"):
        load_profile(path)


@pytest.mark.parametrize(
    "name, blocked",
    [
        ("MacBook Pro Speakers", True),
        ("AirPods Pro", False),
        ("USB Headset", False),
        ("Unknown USB audio", True),
    ],
)
def test_speaker_echo_protection(name, blocked):
    assert block_microphone("auto", name) is blocked
    assert block_microphone("enter", name) is True
    assert block_microphone("voice", name) is False
