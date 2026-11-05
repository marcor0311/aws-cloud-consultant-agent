import asyncio
import json

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed


class RealtimeRelay:
    """Transparent, single-session relay: HF owns VAD, context, generation and cancellation."""

    def __init__(self, backend_url, port, measurements):
        self.backend_url, self.port, self.measurements = backend_url, port, measurements
        self.active = None
        self.server = None

    async def _handle(self, client):
        if self.active is not None:
            await client.close(code=1013, reason="Hay una conversación activa.")
            return
        # Reserve the sole session before opening the upstream connection.
        self.active = False
        try:
            async with connect(
                self.backend_url + "/v1/realtime", max_size=8 * 1024 * 1024
            ) as backend:
                self.active = backend

                async def upload():
                    async for message in client:
                        await backend.send(message)

                async def download():
                    async for message in backend:
                        self.measurements.observe(json.loads(message))
                        await client.send(message)

                tasks = [asyncio.create_task(upload()), asyncio.create_task(download())]
                try:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except ConnectionClosed:
            pass
        finally:
            self.active = None

    async def cancel(self):
        if self.active:
            await self.active.send(json.dumps({"type": "response.cancel"}))

    async def __aenter__(self):
        self.server = await serve(self._handle, "127.0.0.1", self.port, max_size=8 * 1024 * 1024)
        return self

    async def __aexit__(self, *_):
        self.server.close()
        await self.server.wait_closed()
