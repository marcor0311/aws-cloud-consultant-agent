import asyncio
import json

import httpx
import pytest

from voice_call_agent.backends import Ollama
from voice_call_agent.config import Config


async def test_stream_uses_bounded_local_context_and_extracts_generation_metrics():
    async def handle(request):
        body = json.loads(request.content)
        assert request.url.host == "127.0.0.1" and request.url.path == "/api/chat"
        assert body["think"] is False
        assert body["options"]["num_ctx"] == 4096
        assert body["options"]["num_predict"] == 160
        assert body["messages"][-1]["content"] == "Hola"
        content = "\n".join(
            [
                json.dumps({"message": {"content": "Buenos "}, "done": False}),
                json.dumps({"message": {"content": "días."}, "done": False}),
                json.dumps(
                    {
                        "message": {"content": ""},
                        "done": True,
                        "eval_count": 3,
                        "eval_duration": 100000000,
                    }
                ),
            ]
        )
        return httpx.Response(200, content=content)

    model = Ollama(Config())
    await model.client.aclose()
    model.client = httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://127.0.0.1:11434"
    )
    try:
        answer = "".join(
            [part async for part in model.stream([{"role": "user", "content": "Hola"}])]
        )
        assert answer == "Buenos días."
        assert model.stats["eval_count"] == 3
    finally:
        await model.close()


async def test_cancel_closes_the_in_flight_http_stream():
    class Body(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b'{"message":{"content":"Primera frase"},"done":false}\n'
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    body = Body()
    model = Ollama(Config())
    await model.client.aclose()
    model.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=body)),
        base_url="http://127.0.0.1:11434",
    )
    try:
        stream = model.stream([{"role": "user", "content": "Hola"}])
        assert await anext(stream) == "Primera frase"
        waiting = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert body.closed
    finally:
        await model.close()
