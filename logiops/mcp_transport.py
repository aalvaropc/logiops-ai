import json
from collections.abc import Callable

from mcp.types import JSONRPCMessage
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


MAX_BODY_BYTES = 4 * 1024 * 1024


class McpRequestGuard:
    def __init__(self, app: ASGIApp, allow: Callable[[Request], bool], inspect_body: Callable[[Request], bool]) -> None:
        self.app = app
        self.allow = allow
        self.inspect_body = inspect_body

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] not in ("/mcp", "/mcp/"):
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        if not self.allow(request):
            await JSONResponse({"detail": "MCP rate limit exceeded"}, status_code=429)(scope, receive, send)
            return
        if scope["method"] != "POST" or not self.inspect_body(request):
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_BODY_BYTES:
                await JSONResponse({"detail": "MCP request body exceeds 4 MiB"}, status_code=413)(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        try:
            payload = json.loads(body)
        except (ValueError, RecursionError):
            code, reason = -32700, "Parse error"
        else:
            try:
                JSONRPCMessage.model_validate(payload)
            except (ValidationError, RecursionError):
                code, reason = -32600, "Invalid request"
            else:
                delivered = False

                async def replay() -> dict:
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()

                await self.app(scope, replay, send)
                return
        await JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": reason}}, status_code=400)(scope, receive, send)
