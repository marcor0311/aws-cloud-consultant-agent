import asyncio
import contextlib
import os
import signal
import socket
import sys
import time
from urllib.parse import urlparse

from .relay import RealtimeRelay
from .settings import ROOT, load_profile
from .telemetry import Measurements


def require_free(port):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))


class ServerSession:
    def __init__(self, profile, mode):
        self.profile = profile
        self.data, self.backend, self.client_url, self.ollama = load_profile(profile)
        self.measurements = Measurements(root=ROOT / "outputs", mode=mode)
        self.process = None
        self.relay = None
        self.memory_stop = asyncio.Event()
        self.memory_task = None

    async def __aenter__(self):
        try:
            require_free(urlparse(self.backend).port)
            require_free(self.client_url.port)
            self.log = (self.measurements.path / "server.log").open("w")
            self.process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                "-m",
                "hf_voice.worker",
                str(self.profile),
                "--memory-file",
                str((self.measurements.path / "mlx-memory.json").resolve()),
                stdout=self.log,
                stderr=self.log,
                cwd=ROOT,
                env={
                    **os.environ,
                    "TOKENIZERS_PARALLELISM": "false",
                    "HF_HUB_DISABLE_XET": os.environ.get("HF_HUB_DISABLE_XET", "1"),
                },
            )
            base = f"http://{self.ollama.hostname}:{self.ollama.port or 11434}"
            self.memory_task = asyncio.create_task(
                self.measurements.sample_memory(self.process.pid, base, self.memory_stop)
            )
            print("Cargando el servidor oficial de Hugging Face…", flush=True)
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                if self.process.returncode is not None:
                    raise RuntimeError((self.measurements.path / "server.log").read_text()[-6000:])
                try:
                    reader, writer = await asyncio.open_connection(
                        "127.0.0.1", urlparse(self.backend).port
                    )
                    writer.close()
                    await writer.wait_closed()
                    break
                except OSError:
                    await asyncio.sleep(0.3)
            else:
                raise TimeoutError(
                    f"Modelos sin preparar; revisa {self.measurements.path / 'server.log'}"
                )
            self.relay = await RealtimeRelay(
                self.backend, self.client_url.port, self.measurements
            ).__aenter__()
            print("Modelos listos.", flush=True)
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, *_):
        if self.relay:
            await self.relay.__aexit__(None, None, None)
        if self.process and self.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.process.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(self.process.wait(), timeout=10)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.memory_stop.set()
        if self.memory_task:
            await self.memory_task
        if hasattr(self, "log"):
            self.log.close()
        self.measurements.finish()
        print(f"Métricas: {self.measurements.path / 'summary.json'}", flush=True)
