from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = ROOT / "spanish-mac.yaml"


def loopback(url, schemes):
    parsed = urlparse(url)
    if parsed.scheme not in schemes or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("El prototipo solo acepta servicios en loopback local.")
    return parsed


def load_profile(path):
    path = Path(path).resolve()
    data = yaml.safe_load(path.read_text())
    server = data["runtime"]["server"]
    if server["host"] != "127.0.0.1":
        raise ValueError("El servidor HF debe escuchar en 127.0.0.1.")
    client = loopback(data["runtime"]["client"]["url"], {"ws"})
    llm = loopback(data["blocks"]["llm"]["settings"]["responses_api_base_url"], {"http"})
    if not client.port or client.port == server["port"]:
        raise ValueError("Usa puertos distintos para HF y el relay de métricas.")
    return data, f"ws://127.0.0.1:{server['port']}", client, llm


def has_headphones(name):
    return any(
        word in name.casefold()
        for word in (
            "headphone",
            "headset",
            "airpods",
            "earphone",
            "auricular",
            "earbud",
            "buds",
        )
    )
