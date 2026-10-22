import json
from collections.abc import Awaitable, Callable

from mcp.types import JSONRPCMessage
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send


MAX_BODY_BYTES = 4 * 1024 * 1024
NO_STORE = {"Cache-Control": "no-store"}


class McpRequestGuard:

    def __init__(
        self, app: ASGIApp, admit: Callable[[Request], Awaitable[Response | None]], allow: Callable[[Request], bool],
        retry_after: int = 60,
    ) -> None:
        self.app = app
        self.admit = admit
        self.allow = allow
        self.retry_after = retry_after

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] not in ("/mcp", "/mcp/"):
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        refused = await self.admit(request)
        if refused is not None:
            await refused(scope, receive, send)
            return
        if not self.allow(request):
            await JSONResponse({"detail": "MCP rate limit exceeded"}, status_code=429,
                               headers={**NO_STORE, "Retry-After": str(self.retry_after)})(scope, receive, send)
            return
        if scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_BODY_BYTES:
                await JSONResponse({"detail": "MCP request body exceeds 4 MiB"}, status_code=413, headers=NO_STORE)(scope, receive, send)
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
        await JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": reason}},
                           status_code=400, headers=NO_STORE)(scope, receive, send)
