"""Local HTTP interface for the first LogiOps vertical slice."""

from __future__ import annotations

import html
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from .agent import ConverseClient, ask_with_bedrock, investigate_with_bedrock
from .bedrock import BedrockConverse, BedrockError
from .service import LogiOpsService, WorkflowError
from .mcp_server import create_mcp_server
from .replay import ReplayConverse
from .security import SANDBOX_PATH, install_security

HOSTNAME = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?")
LOOPBACK_PAIRS = {"127.0.0.1": "localhost", "localhost": "127.0.0.1"}
SANDBOX_META = '<meta name="logiops-sandbox-origin" content="">'


class ApprovalRequest(BaseModel):
    plan_id: str = Field(min_length=1)
    source_version: int = Field(ge=1)
    approved_by: str = Field(min_length=1)


class ExecutionRequest(BaseModel):
    plan_id: str = Field(min_length=1)
    source_version: int = Field(ge=1)


class InventoryChange(BaseModel):
    available: int = Field(ge=0)


class AgentInvestigationRequest(BaseModel):
    question: str = Field(default="What is happening, and which plan should we choose?", min_length=1, max_length=1000)


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=1000)


class AgentAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    history: list[ConversationTurn] = Field(default_factory=list, max_length=8)


PLAN_FIELDS = (
    "id", "kind", "label", "allocations", "projected_completion_eta",
    "projected_customer_delay_hours", "incremental_cost_usd", "source_version",
)


def create_app(
    db_path: str | Path | None = None,
    bedrock_client: ConverseClient | None = None,
    *,
    followup_client: ConverseClient | None = None,
    access_token: str | None = None,
    mcp_limit_per_minute: int = 60,
    agent_limit_per_minute: int | None = None,
) -> FastAPI:
    access_token = access_token or os.environ.get("LOGIOPS_ACCESS_TOKEN")
    public_host = os.environ.get("LOGIOPS_PUBLIC_HOST", "").strip().lower()
    if public_host and (not HOSTNAME.fullmatch(public_host) or ".." in public_host):
        raise RuntimeError("LOGIOPS_PUBLIC_HOST must be one exact hostname without a scheme or port")
    if os.environ.get("LOGIOPS_PUBLIC") == "1" and (not access_token or len(access_token) < 32):
        raise RuntimeError("Public mode requires LOGIOPS_ACCESS_TOKEN with at least 32 characters")
    if os.environ.get("LOGIOPS_PUBLIC") == "1" and not public_host:
        raise RuntimeError("Public mode requires LOGIOPS_PUBLIC_HOST")
    # MCP Apps: web hosts must render views through a sandbox proxy on another origin.
    sandbox_host = os.environ.get("LOGIOPS_SANDBOX_HOST", "").strip().lower()
    if sandbox_host and (not HOSTNAME.fullmatch(sandbox_host) or ".." in sandbox_host):
        raise RuntimeError("LOGIOPS_SANDBOX_HOST must be one exact hostname without a scheme or port")
    if sandbox_host and sandbox_host == public_host:
        raise RuntimeError("LOGIOPS_SANDBOX_HOST must differ from LOGIOPS_PUBLIC_HOST")
    path = Path(db_path or os.environ.get("LOGIOPS_DB_PATH", "data/logiops.sqlite3"))
    service = LogiOpsService(path)
    mcp = create_mcp_server(service, public_host=public_host or None)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="LogiOps AI", version="0.1.0", lifespan=lifespan)
    # Per-process secret that marks the agent's in-process MCP calls; never leaves the server.
    internal_key = secrets.token_hex(32)
    if agent_limit_per_minute is None:
        agent_limit_per_minute = int(os.environ.get("LOGIOPS_AGENT_LIMIT_PER_MINUTE", "10"))
    install_security(
        app, access_token,
        internal_key=internal_key,
        limit_per_minute=mcp_limit_per_minute,
        agent_limit_per_minute=agent_limit_per_minute,
        trust_cloudfront=os.environ.get("LOGIOPS_TRUST_CLOUDFRONT") == "1",
        sandbox_host=sandbox_host or None,
    )
    static_dir = Path(__file__).resolve().parent / "static"
    demo_assets = {
        "demo.html": (static_dir / "demo.html").read_bytes(),
        "demo.css": (static_dir / "demo.css").read_bytes(),
        "demo.js": (static_dir / "demo.js").read_bytes(),
        "markdown.js": (static_dir / "markdown.js").read_bytes(),
        "intent.js": (static_dir / "intent.js").read_bytes(),
    }
    sandbox_page = (static_dir / "mcp_app_sandbox.html").read_text(encoding="utf-8")

    def origins(request: Request) -> tuple[str | None, str | None]:
        """(page origin, sandbox origin) for this request; (None, None) if there is no safe pair.

        Public mode uses the two configured HTTPS hostnames. Locally, 127.0.0.1 and
        localhost are different origins on the same server, so each one sandboxes the other.
        """
        if public_host:
            return f"https://{public_host}", (f"https://{sandbox_host}" if sandbox_host else None)
        name, _, port = request.headers.get("host", "").partition(":")
        other = LOOPBACK_PAIRS.get(name.lower())
        if other is None or (port and not port.isdigit()):
            return None, None
        scheme = request.url.scheme
        suffix = f":{port}" if port else ""
        return f"{scheme}://{name.lower()}{suffix}", f"{scheme}://{other}{suffix}"

    @app.get("/demo", include_in_schema=False)
    async def demo_page(request: Request) -> HTMLResponse:
        _page, sandbox = origins(request)
        page = demo_assets["demo.html"].decode("utf-8")
        return HTMLResponse(page.replace(SANDBOX_META, SANDBOX_META.replace('content=""', f'content="{html.escape(sandbox or "")}"')))

    @app.get(SANDBOX_PATH, include_in_schema=False)
    async def mcp_app_sandbox(request: Request) -> Response:
        """Sandbox proxy for MCP Apps views; served only on the sandbox origin, never with data."""
        if public_host:
            if not sandbox_host or request.headers.get("host", "").split(":")[0].lower() != sandbox_host:
                return JSONResponse(status_code=404, content={"detail": "Not found"})
            host_origin = f"https://{public_host}"
        else:
            _self, host_origin = origins(request)
            if host_origin is None:
                return JSONResponse(status_code=404, content={"detail": "Not found"})
        # Views are loaded through srcdoc and inherit this policy, so it allows inline
        # code but no network; each view also gets its own, stricter policy.
        policy = (
            "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; "
            f"connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors {host_origin}"
        )
        return HTMLResponse(sandbox_page, headers={
            "Content-Security-Policy": policy, "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
        })

    @app.get("/assets/demo.css", include_in_schema=False)
    async def demo_style() -> Response:
        return Response(demo_assets["demo.css"], media_type="text/css")

    @app.get("/assets/markdown.js", include_in_schema=False)
    async def markdown_script() -> Response:
        return Response(demo_assets["markdown.js"], media_type="text/javascript")

    @app.get("/assets/intent.js", include_in_schema=False)
    async def intent_script() -> Response:
        return Response(demo_assets["intent.js"], media_type="text/javascript")

    @app.get("/assets/demo.js", include_in_schema=False)
    async def demo_script() -> Response:
        return Response(demo_assets["demo.js"], media_type="text/javascript")

    @app.exception_handler(WorkflowError)
    async def workflow_error_handler(_request: Any, exc: WorkflowError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(BedrockError)
    async def bedrock_error_handler(_request: Any, exc: BedrockError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/demo/reset")
    async def reset() -> dict[str, Any]:
        """Restore the synthetic scenario; local development only."""
        return service.reset()

    @app.post("/demo/inventory")
    async def change_inventory(change: InventoryChange) -> dict[str, Any]:
        """Inject a stock change to demonstrate stale-plan protection."""
        return service.set_local_inventory("SHIP-421", change.available)

    @app.get("/incidents/{incident_id}")
    async def get_incident(incident_id: str) -> dict[str, Any]:
        return service.get(incident_id)

    @app.post("/incidents/{incident_id}/investigate")
    async def investigate(incident_id: str) -> dict[str, Any]:
        plans = service.investigate(incident_id)
        return {"plans": plans, "source_version": plans[0]["source_version"]}

    @app.post("/incidents/{incident_id}/agent/investigate")
    async def agent_investigate(incident_id: str, request: AgentInvestigationRequest) -> dict[str, Any]:
        source_version = service.get(incident_id)["source_version"]
        mode = os.environ.get("LOGIOPS_AGENT_MODE", "bedrock")
        if mode not in ("bedrock", "replay"):
            raise BedrockError("LOGIOPS_AGENT_MODE must be bedrock or replay")
        client = bedrock_client or (ReplayConverse() if mode == "replay" else BedrockConverse())
        run_mode = "custom" if bedrock_client else mode
        try:
            run = await investigate_with_bedrock(
                app, client, incident_id, request.question,
                access_token=access_token, internal_key=internal_key,
            )
        except BedrockError as exc:
            # Failed runs belong in the audit trail too, not only in the HTTP response.
            service.record_agent_event(
                incident_id, "agent_run_failed", {"job": "investigate", "mode": run_mode, "error": str(exc)}
            )
            raise
        run["mode"] = run_mode
        recorded = service.record_agent_run(incident_id, source_version, run)
        return {**run, **recorded}

    @app.post("/incidents/{incident_id}/agent/ask")
    async def agent_ask(incident_id: str, request: AgentAskRequest) -> dict[str, Any]:
        """Answer a follow-up from the latest investigation of the data being shown."""
        snapshot = service.get(incident_id)
        executions = snapshot["executions"]
        # After execution the version moves on; follow-ups still refer to the executed plans.
        version = executions[0]["source_version"] if executions else snapshot["source_version"]
        latest = next((
            event for event in reversed(snapshot["events"])
            if event["name"] == "agent_investigation_completed" and event["data"]["source_version"] == version
        ), None)
        if latest is None:
            raise WorkflowError("Ask for an investigation of the current data first")
        context = {
            "source_version": version,
            "status": snapshot["state"]["status"],
            "latest_assessment": latest["data"]["answer"],
            "plans": [
                {key: plan[key] for key in PLAN_FIELDS}
                for plan in snapshot["plans"] if plan["source_version"] == version
            ],
            # After execution the version moves on, so match the approval to the plans shown.
            "current_approval": next(
                (item for item in snapshot["approvals"] if item["source_version"] == version), None
            ),
            "execution": executions[0] if executions else None,
        }
        mode = os.environ.get("LOGIOPS_AGENT_MODE", "bedrock")
        if mode not in ("bedrock", "replay"):
            raise BedrockError("LOGIOPS_AGENT_MODE must be bedrock or replay")
        custom = followup_client or bedrock_client
        client = custom or (ReplayConverse() if mode == "replay" else BedrockConverse())
        run_mode = "custom" if custom else mode
        try:
            run = await ask_with_bedrock(
                app, client, incident_id, request.question, context,
                [turn.model_dump() for turn in request.history],
                access_token=access_token, internal_key=internal_key,
            )
        except BedrockError as exc:
            # Answers change nothing and are not stored, but failed paid calls are audited.
            service.record_agent_event(
                incident_id, "agent_run_failed", {"job": "ask", "mode": run_mode, "error": str(exc)}
            )
            raise
        return {**run, "mode": run_mode, "source_version": version}

    @app.post("/incidents/{incident_id}/approvals")
    async def approve(incident_id: str, request: ApprovalRequest) -> dict[str, Any]:
        return service.approve(incident_id, request.plan_id, request.source_version, request.approved_by)

    @app.post("/incidents/{incident_id}/execute")
    async def execute(incident_id: str, request: ExecutionRequest) -> dict[str, Any]:
        return service.execute(incident_id, request.plan_id, request.source_version)

    app.mount("/", mcp.streamable_http_app())
    return app


app = create_app()
