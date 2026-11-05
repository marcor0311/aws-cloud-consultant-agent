import asyncio
import os
from types import SimpleNamespace

from voice_call_agent.cli import enter_to_interrupt


async def test_enter_interrupts_without_a_blocked_executor_thread(monkeypatch):
    read, write = os.pipe()
    calls = []
    with os.fdopen(read) as stream:
        monkeypatch.setattr(
            "sys.stdin",
            SimpleNamespace(
                isatty=lambda: True,
                fileno=stream.fileno,
                readline=stream.readline,
            ),
        )
        engine = SimpleNamespace(interrupt=calls.append)
        try:
            with enter_to_interrupt(engine) as enabled:
                assert enabled
                os.write(write, b"\n")
                for _ in range(10):
                    if calls:
                        break
                    await asyncio.sleep(0.001)
                assert calls == ["manual_interrupt"]
        finally:
            os.close(write)
