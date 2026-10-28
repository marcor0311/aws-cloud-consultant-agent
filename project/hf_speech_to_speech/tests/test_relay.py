import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from hf_voice.relay import RealtimeRelay
from hf_voice.telemetry import Measurements


async def test_native_protocol_and_manual_cancel(tmp_path):
    received = []

    async def backend(ws):
        await ws.send(json.dumps({"type": "session.created"}))
        async for message in ws:
            event = json.loads(message)
            received.append(event)
            if event["type"] == "response.cancel":
                await ws.send(
                    json.dumps(
                        {"type": "response.done", "response": {"id": "one", "status": "cancelled"}}
                    )
                )
            else:
                await ws.send(message)

    metrics = Measurements(tmp_path)
    async with serve(backend, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with RealtimeRelay(f"ws://127.0.0.1:{port}", 0, metrics) as relay:
            url = f"ws://127.0.0.1:{relay.server.sockets[0].getsockname()[1]}/v1/realtime"
            async with connect(url) as ws:
                assert json.loads(await ws.recv())["type"] == "session.created"
                message = json.dumps({"type": "session.update", "session": {"test": 1}})
                await ws.send(message)
                assert await ws.recv() == message
                async with connect(url) as second:
                    with pytest.raises(ConnectionClosed):
                        await asyncio.wait_for(second.recv(), 2)
                await relay.cancel()
                assert json.loads(await ws.recv())["response"]["status"] == "cancelled"
    assert received[-1] == {"type": "response.cancel"}
    assert metrics.finish()["cancelled"] == 1
