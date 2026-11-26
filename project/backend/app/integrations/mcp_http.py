"""Shared local HTTP authentication for private MCP entry points."""

import hmac


class BearerProtectedMCP:
    """ASGI guard for the local Streamable HTTP endpoint used by ChatGPT tunnels."""

    def __init__(self, app, token, *, path="/mcp"):
        if not token or len(token) < 32:
            raise ValueError(
                "El token Bearer de MCP debe tener al menos 32 caracteres."
            )
        self.app = app
        self.token = token.encode()
        self.path = path

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") == self.path:
            supplied = dict(scope.get("headers", [])).get(b"authorization", b"")
            expected = b"Bearer " + self.token
            if not hmac.compare_digest(supplied, expected):
                body = b"Unauthorized"
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                    }
                )
                await send(
                    {"type": "http.response.body", "body": body, "more_body": False}
                )
                return
        await self.app(scope, receive, send)
