"""The HTTP application: resolves the settings, builds the stores and clients, and mounts the routers and the MCP server."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from . import __version__
from .alerts import AlertWatcher
from .agent import ConverseClient
from .bedrock import BedrockConverse, BedrockError
from .booking import BookingStore
from .budget import DailyModelBudget
from .mcp_server import create_mcp_server
from .memory import MemoryService
from .oauth import OAuthSettings, install_oauth
from .preferences import PreferenceStore
from .routes import account, agent, bookings as booking_routes, incidents, pages, scenario
from .routes.context import Context
from .routes.pages import ASSET_TYPES
from .scenario import ScenarioPackError, load_scenario_pack, scenario_clock
from .security import install_security
from .service import LogiOpsService, WorkflowError
from .telemetry import telemetry_from_env
from .voice import PollyVoice

logger = logging.getLogger(__name__)

HOSTNAME = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?")
STATIC_DIR = Path(__file__).resolve().parent / "static"
DEMO_ASSETS = tuple(sorted(
    path.relative_to(STATIC_DIR).as_posix() for path in STATIC_DIR.rglob("*") if path.is_file() and path.suffix in ASSET_TYPES
))


def create_app(
    db_path: str | Path | None = None,
    bedrock_client: ConverseClient | None = None,
    *,
    followup_client: ConverseClient | None = None,
    access_token: str | None = None,
    mcp_limit_per_minute: int | None = None,
    agent_limit_per_minute: int | None = None,
    voice: PollyVoice | None = None,
    oauth: OAuthSettings | None = None,
    memory: MemoryService | None = None,
) -> FastAPI:
    access_token = access_token or os.environ.get("LOGIOPS_ACCESS_TOKEN")
    public_host = os.environ.get("LOGIOPS_PUBLIC_HOST", "").strip().lower()
    if public_host and (not HOSTNAME.fullmatch(public_host) or ".." in public_host):
        raise RuntimeError("LOGIOPS_PUBLIC_HOST must be one exact hostname without a scheme or port")
    if os.environ.get("LOGIOPS_PUBLIC") == "1" and (not access_token or len(access_token) < 32):
        raise RuntimeError("Public mode requires LOGIOPS_ACCESS_TOKEN with at least 32 characters")
    if os.environ.get("LOGIOPS_PUBLIC") == "1" and not public_host:
        raise RuntimeError("Public mode requires LOGIOPS_PUBLIC_HOST")
    sandbox_host = os.environ.get("LOGIOPS_SANDBOX_HOST", "").strip().lower()
    if sandbox_host and (not HOSTNAME.fullmatch(sandbox_host) or ".." in sandbox_host):
        raise RuntimeError("LOGIOPS_SANDBOX_HOST must be one exact hostname without a scheme or port")
    if sandbox_host and sandbox_host == public_host:
        raise RuntimeError("LOGIOPS_SANDBOX_HOST must differ from LOGIOPS_PUBLIC_HOST")
    path = Path(db_path or os.environ.get("LOGIOPS_DB_PATH", "data/logiops.sqlite3"))
    try:
        scenario_day = scenario_clock(os.environ.get("LOGIOPS_SCENARIO_ANCHOR"))
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    telemetry = telemetry_from_env() or "off"
    pack_path = os.environ.get("LOGIOPS_SCENARIO_PACK", "").strip()
    if pack_path:
        try:
            load_scenario_pack(pack_path)
        except ScenarioPackError as exc:
            raise RuntimeError(f"LOGIOPS_SCENARIO_PACK could not be loaded: {exc}") from exc
    service = LogiOpsService(path, scenario_day=scenario_day)
    preferences = PreferenceStore(path)
    bookings = BookingStore(path, service)
    alerts = AlertWatcher(path, service, preferences)
    voice = voice or PollyVoice(path)
    memory = memory or MemoryService(path)
    budget = DailyModelBudget.from_env(path)
    bedrock = BedrockConverse()
    mcp = create_mcp_server(
        service, preferences=preferences, bookings=bookings, alerts=alerts, public_host=public_host or None)
    oauth = oauth if oauth is not None else OAuthSettings.from_env()
    public = os.environ.get("LOGIOPS_PUBLIC") == "1"
    scan_seconds = float(os.environ.get("LOGIOPS_ALERT_SCAN_SECONDS", "30"))

    async def watch() -> None:
        while True:
            await asyncio.sleep(scan_seconds)
            try:
                await asyncio.to_thread(alerts.scan)
            except Exception:
                logger.exception("The alert scan failed")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        watcher = asyncio.create_task(watch()) if scan_seconds > 0 else None
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            if watcher:
                watcher.cancel()

    app = FastAPI(title="LogiOps AI", version=__version__, lifespan=lifespan)
    internal_key = secrets.token_hex(32)
    if agent_limit_per_minute is None:
        agent_limit_per_minute = int(os.environ.get("LOGIOPS_AGENT_LIMIT_PER_MINUTE", "10"))
    if mcp_limit_per_minute is None:
        mcp_limit_per_minute = int(os.environ.get("LOGIOPS_MCP_LIMIT_PER_MINUTE", "60"))
    install_security(
        app, access_token,
        internal_key=internal_key,
        limit_per_minute=mcp_limit_per_minute,
        agent_limit_per_minute=agent_limit_per_minute,
        trust_cloudfront=os.environ.get("LOGIOPS_TRUST_CLOUDFRONT") == "1",
        sandbox_host=sandbox_host or None,
        oauth=oauth,
        public_host=public_host or None,
    )
    if oauth:
        install_oauth(app, oauth, public_host or None)
    static_dir = STATIC_DIR
    demo_page_html = (static_dir / "demo.html").read_text(encoding="utf-8")
    console_page_html = (static_dir / "console.html").read_text(encoding="utf-8")
    demo_assets = {name: (static_dir / name).read_bytes() for name in DEMO_ASSETS}
    sandbox_page = (static_dir / "mcp_app_sandbox.html").read_text(encoding="utf-8")

    static_dir = STATIC_DIR
    context = Context(
        app=app, service=service, preferences=preferences, bookings=bookings, alerts=alerts, voice=voice, memory=memory,
        budget=budget, bedrock=bedrock, bedrock_client=bedrock_client, followup_client=followup_client,
        access_token=access_token, internal_key=internal_key, public=public, public_host=public_host, sandbox_host=sandbox_host,
        telemetry=telemetry, demo_page_html=(static_dir / "demo.html").read_text(encoding="utf-8"),
        console_page_html=(static_dir / "console.html").read_text(encoding="utf-8"),
        demo_assets={name: (static_dir / name).read_bytes() for name in DEMO_ASSETS},
        sandbox_page=(static_dir / "mcp_app_sandbox.html").read_text(encoding="utf-8"),
    )
    app.include_router(pages.router(context, auth_enabled=bool(oauth)))
    app.include_router(incidents.router(context))
    app.include_router(account.router(context))
    app.include_router(agent.router(context))
    app.include_router(scenario.router(context))
    app.include_router(booking_routes.router(context))

    @app.exception_handler(WorkflowError)
    async def workflow_error_handler(_request: Any, exc: WorkflowError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(BedrockError)
    async def bedrock_error_handler(_request: Any, exc: BedrockError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    app.mount("/", mcp.streamable_http_app())
    return app


app = create_app()
