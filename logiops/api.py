"""Local HTTP interface for the first LogiOps vertical slice."""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from . import __version__
from .alerts import AlertWatcher
from .agent import (
    BRIEFING_TURNS, FOLLOWUP_TURNS, INVESTIGATE_TURNS, ConverseClient, ask_with_bedrock, brief_with_bedrock,
    investigate_with_bedrock, merged_facts,
)
from .bedrock import BedrockConverse, BedrockError
from .booking import BookingStore, receipt_html
from .evaluator import figures_in
from .budget import FALLBACK, BudgetedConverse, DailyModelBudget
from .service import APPROVER_MAX_LENGTH, LogiOpsService, WorkflowError
from .identity import actor_of, profile_of
from .mcp_server import create_mcp_server
from .memory import MemoryService
from .oauth import OAuthSettings, install_oauth
from .preferences import COST_LIMIT, NOTE_LIMIT, RULES, PreferenceStore, preference_for, with_preference_figures
from .presentation import customer_text, shown_run
from .replay import ReplayConverse
from .scenario import INCIDENT_ID, INCIDENT_IDS, known_figures, scenario_clock
from .security import SANDBOX_PATH, install_security
from .voice import PollyVoice

logger = logging.getLogger(__name__)

HOSTNAME = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?")
LOOPBACK_PAIRS = {"127.0.0.1": "localhost", "localhost": "127.0.0.1"}
START_WITH = re.compile(r"start with[*_`]*\s*[:：]\s*[*_`]*\s*(SHIP-\d+)", re.I)
SANDBOX_META = '<meta name="logiops-sandbox-origin" content="">'
DEMO_ASSETS = ("demo.css", "demo.js", "markdown.js", "intent.js", "route.js", "device.js")
ASSET_TYPES = {".css": "text/css", ".js": "text/javascript"}


class ApprovalRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=200)
    source_version: int = Field(ge=1)
    approved_by: str = Field(min_length=1, max_length=APPROVER_MAX_LENGTH)


class ExecutionRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=200)
    source_version: int = Field(ge=1)


class InventoryChange(BaseModel):
    available: int = Field(ge=0)
    incident_id: str = Field(default=INCIDENT_ID, min_length=1, max_length=40)


class ResetRequest(BaseModel):
    incident_id: str | None = Field(default=None, min_length=1, max_length=40)


class AgentInvestigationRequest(BaseModel):
    question: str = Field(default="What is happening, and which plan should we choose?", min_length=1, max_length=1000)


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=1000)


class AgentAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    history: list[ConversationTurn] = Field(default_factory=list, max_length=8)


class AgentBriefingRequest(BaseModel):
    question: str = Field(default="Any delays today? What needs my attention first?", min_length=1, max_length=1000)


class MemoryTurn(BaseModel):
    session: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]+$")
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=4000)
    incident: str | None = Field(default=None, max_length=40)


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class QuoteRequest(BaseModel):
    plan_id: str | None = Field(default=None, min_length=1, max_length=200)


class BookingConfirmation(BaseModel):
    confirmed_total_usd: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class PreferenceUpdate(BaseModel):
    rule: Literal[tuple(RULES)] = "balanced"  # type: ignore[valid-type]
    max_cost_usd: int | None = Field(default=None, ge=0, le=COST_LIMIT)
    note: str = Field(default="", max_length=NOTE_LIMIT)


PLAN_FIELDS = (
    "id", "kind", "label", "allocations", "orders", "projected_completion_eta",
    "projected_customer_delay_hours", "late_units", "incremental_cost_usd", "source_version",
)


def create_app(
    db_path: str | Path | None = None,
    bedrock_client: ConverseClient | None = None,
    *,
    followup_client: ConverseClient | None = None,
    access_token: str | None = None,
    mcp_limit_per_minute: int = 60,
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
    else:
        @app.get("/auth/config", include_in_schema=False)
        async def auth_off() -> dict[str, Any]:
            return {"enabled": False}
    static_dir = Path(__file__).resolve().parent / "static"
    demo_page_html = (static_dir / "demo.html").read_text(encoding="utf-8")
    demo_assets = {name: (static_dir / name).read_bytes() for name in DEMO_ASSETS}
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
        return HTMLResponse(demo_page_html.replace(SANDBOX_META, SANDBOX_META.replace('content=""', f'content="{html.escape(sandbox or "")}"')))

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
        policy = (
            "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; "
            f"connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors {host_origin}"
        )
        return HTMLResponse(sandbox_page, headers={
            "Content-Security-Policy": policy, "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
        })

    @app.get("/assets/{name}", include_in_schema=False)
    async def demo_asset(name: str) -> Response:
        """The demo's stylesheet and scripts: only the names in DEMO_ASSETS, read once at start-up."""
        body = demo_assets.get(name)
        if body is None:
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        return Response(body, media_type=ASSET_TYPES[Path(name).suffix])

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
    async def reset(request: ResetRequest | None = None) -> dict[str, Any]:
        """Restore every synthetic incident and forget the preferences and bookings, or reset only the incident named."""
        incident_id = request.incident_id if request else None
        if incident_id is None:
            preferences.clear_all()
        snapshot = service.reset(incident_id)
        bookings.clear(incident_id)
        alerts.clear(incident_id)
        return snapshot

    def visible_plans(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        executions = snapshot["executions"]
        version = executions[0]["source_version"] if executions else snapshot["source_version"]
        return [plan for plan in snapshot["plans"] if plan["source_version"] == version]

    @app.get("/operator/preferences")
    async def get_preferences(request: Request) -> dict[str, Any]:
        """Your saved preferences (they persist across sessions; a signed-in user has their own) and the rules on offer."""
        return {"preferences": preferences.get(profile_of(actor_of(request))), "rules": RULES}

    @app.put("/operator/preferences")
    async def put_preferences(update: PreferenceUpdate, request: Request) -> dict[str, Any]:
        """Save preferences for every incident; they steer the pick and never approve a plan."""
        try:
            saved = preferences.put(update.rule, update.max_cost_usd, update.note, subject=profile_of(actor_of(request)))
        except ValueError as exc:
            raise WorkflowError(str(exc), 422) from exc
        return {"preferences": saved, "rules": RULES}

    @app.delete("/operator/preferences")
    async def clear_preferences(request: Request) -> dict[str, Any]:
        preferences.clear(profile_of(actor_of(request)))
        return {"preferences": None, "rules": RULES}

    @app.post("/demo/inventory")
    async def change_inventory(change: InventoryChange) -> dict[str, Any]:
        """Inject a stock change at an incident's warehouse to demonstrate stale-plan protection; an
        incident that was already investigated is re-planned at once and gets an alert."""
        snapshot = service.set_local_inventory(change.incident_id, change.available)
        if alerts.check(change.incident_id):
            snapshot = service.get(change.incident_id)
        return snapshot

    @app.post("/memory/turns", status_code=202)
    async def remember_turn(turn: MemoryTurn, request: Request, background: BackgroundTasks) -> dict[str, Any]:
        """Remember one turn of the conversation for the person asking (never for a guest); written after the reply."""
        actor = actor_of(request)
        incident = turn.incident if turn.incident in INCIDENT_IDS else None
        background.add_task(memory.remember, actor, turn.session, turn.role, turn.text, incident)
        return {"accepted": actor.kind != "guest", "backend": memory.backend}

    @app.get("/memory")
    async def recall(request: Request, session: str | None = None) -> dict[str, Any]:
        """What the person said in their previous session, a welcome-back line, and long-term facts."""
        return await asyncio.to_thread(memory.recall, actor_of(request), session)

    @app.delete("/memory")
    async def forget(request: Request) -> dict[str, Any]:
        """Forget me: delete the person's remembered turns and records."""
        return {"forgotten": await asyncio.to_thread(memory.forget, actor_of(request)), "backend": memory.backend}

    async def remembered(request: Request, question: str, run_mode: str) -> list[str]:
        """Long-term facts about the person, for a live run only (the replay model ignores them)."""
        if run_mode == "replay":
            return []
        return (await asyncio.to_thread(memory.recall, actor_of(request), None, question)).get("facts", [])

    @app.get("/voice/config")
    async def voice_config() -> dict[str, Any]:
        """How the page should speak: Amazon Polly (with its voice) or the browser's own voice."""
        return voice.config()

    @app.post("/voice/speech")
    async def speech(request: SpeechRequest) -> Response:
        """MP3 of the reply read by Amazon Polly, cached per text and capped per day. A 503 with
        fallback "browser" means the page reads it with the browser's voice instead."""
        audio = await asyncio.to_thread(voice.speak, request.text)
        if audio is None:
            return JSONResponse(status_code=503, content={"detail": "Polly is not available; use the browser's voice", "fallback": "browser"})
        return Response(audio, media_type="audio/mpeg")

    @app.get("/alerts")
    async def list_alerts() -> dict[str, Any]:
        """Open proactive alerts, newest first: what changed, the plan it affects and the new pick. They never approve."""
        return {"alerts": alerts.open_alerts()}

    @app.post("/alerts/{alert_id}/dismiss")
    async def dismiss_alert(alert_id: str) -> dict[str, Any]:
        return alerts.dismiss(alert_id)

    @app.get("/incidents")
    async def list_incidents() -> dict[str, Any]:
        """The incident inbox: open first, then by critical units at risk, priority and due time."""
        return {"incidents": service.list_incidents()}

    @app.get("/incidents/{incident_id}")
    async def get_incident(incident_id: str, request: Request) -> dict[str, Any]:
        snapshot = service.get(incident_id)
        saved = preferences.get(profile_of(actor_of(request)))
        for event in snapshot["events"]:
            if event["name"] == "agent_investigation_completed":
                version_plans = [plan for plan in snapshot["plans"] if plan["source_version"] == event["data"]["source_version"]]
                event["data"]["display_answer"] = customer_text(event["data"]["answer"], version_plans)
        return {
            **snapshot, "operator_preferences": saved,
            "preference": preference_for(visible_plans(snapshot), saved),
            "bookings": bookings.for_incident(incident_id),
        }

    @app.post("/incidents/{incident_id}/investigate")
    async def investigate(incident_id: str) -> dict[str, Any]:
        plans = service.investigate(incident_id)
        return {"plans": plans, "source_version": plans[0]["source_version"]}

    @asynccontextmanager
    async def agent_client(
        custom: ConverseClient | None, max_calls: int, request: Request | None = None,
    ) -> AsyncIterator[tuple[ConverseClient, str, str | None]]:
        """(client, mode, fallback) for one agent request. A live request first reserves its run's
        maximum calls from the daily budget and releases what it did not use; when the run no longer
        fits, it runs on the replay model with fallback "daily_budget". A guest on the public
        deployment always runs on the replay model, with fallback "sign_in"."""
        mode = os.environ.get("LOGIOPS_AGENT_MODE", "bedrock")
        if mode not in ("bedrock", "replay"):
            raise BedrockError("LOGIOPS_AGENT_MODE must be bedrock or replay")
        if public and request is not None and actor_of(request).kind == "guest":
            yield ReplayConverse(), "replay", "sign_in"
        elif custom:
            yield custom, "custom", None
        elif mode == "replay":
            yield ReplayConverse(), "replay", None
        elif (day := budget.reserve(max_calls)) is None:
            yield ReplayConverse(), "replay", FALLBACK
        else:
            client = BudgetedConverse(bedrock, budget, day, max_calls)
            try:
                yield client, "bedrock", None
            finally:
                client.settle()

    def agent_token(request: Request) -> str | None:
        """The token the agent's in-process MCP calls carry: a signed-in user's own (so the tools apply
        their preferences), otherwise the operator token."""
        supplied = request.headers.get("authorization", "")
        if actor_of(request).kind == "user" and supplied[:7].lower() == "bearer ":
            return supplied[7:].strip()
        return access_token

    def labelled(run: dict[str, Any], mode: str, fallback: str | None) -> dict[str, Any]:
        return {**run, "mode": mode, **({"fallback": fallback} if fallback else {})}

    @app.post("/incidents/{incident_id}/agent/investigate")
    async def agent_investigate(incident_id: str, request: AgentInvestigationRequest, http_request: Request) -> dict[str, Any]:
        snapshot = service.get(incident_id)
        source_version = snapshot["source_version"]
        facts = with_preference_figures(known_figures(snapshot["state"]), preferences.get(profile_of(actor_of(http_request))))
        async with agent_client(bedrock_client, INVESTIGATE_TURNS, http_request) as (client, run_mode, fallback):
            recalled = await remembered(http_request, request.question, run_mode)
            facts = merged_facts(facts, figures_in(" ".join(recalled))) if recalled else facts
            try:
                run = await investigate_with_bedrock(
                    app, client, incident_id, request.question + memory.block({"facts": recalled}),
                    access_token=agent_token(http_request), internal_key=internal_key, facts=facts,
                )
            except BedrockError as exc:
                service.record_agent_event(
                    incident_id, "agent_run_failed", {"job": "investigate", "mode": run_mode, "error": str(exc)}
                )
                raise
        run = labelled(run, run_mode, fallback)
        recorded = service.record_agent_run(incident_id, source_version, run)
        picked = run["evaluations"][-1].get("recommended_plan_id") if run.get("evaluations") else None
        return {**shown_run(run, recorded["plans"]), **recorded, "recommended_plan_id": picked}

    @app.post("/incidents/{incident_id}/agent/ask")
    async def agent_ask(incident_id: str, request: AgentAskRequest, http_request: Request) -> dict[str, Any]:
        """Answer a follow-up from the latest investigation of the data being shown."""
        snapshot = service.get(incident_id)
        executions = snapshot["executions"]
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
            "current_approval": next(
                (item for item in snapshot["approvals"] if item["source_version"] == version), None
            ),
            "execution": executions[0] if executions else None,
        }
        saved = preferences.get(profile_of(actor_of(http_request)))
        preference = preference_for(context["plans"], saved)
        if preference:
            context["operator_preferences"] = preference
        asked = " ".join([request.question, *(turn.text for turn in request.history if turn.role == "user")])
        recorded = ["approved"] * bool(context["current_approval"] or executions) + ["executed"] * bool(executions)
        facts = merged_facts(
            with_preference_figures(known_figures(snapshot["state"]), saved), figures_in(asked), {"recorded_actions": recorded},
            bookings.figures(incident_id))
        async with agent_client(followup_client or bedrock_client, FOLLOWUP_TURNS, http_request) as (client, run_mode, fallback):
            recalled = await remembered(http_request, request.question, run_mode)
            if recalled:
                context = {**context, "memory": recalled}
                facts = merged_facts(facts, figures_in(" ".join(recalled)))
            try:
                run = await ask_with_bedrock(
                    app, client, incident_id, request.question, context,
                    [turn.model_dump() for turn in request.history],
                    access_token=agent_token(http_request), internal_key=internal_key, facts=facts,
                    plans=[plan for plan in snapshot["plans"] if plan["source_version"] == version],
                )
            except BedrockError as exc:
                service.record_agent_event(
                    incident_id, "agent_run_failed", {"job": "ask", "mode": run_mode, "error": str(exc)}
                )
                raise
        return {**shown_run(labelled(run, run_mode, fallback), context["plans"]), "source_version": version}

    @app.post("/agent/briefing")
    async def agent_briefing(request: AgentBriefingRequest, http_request: Request) -> dict[str, Any]:
        """Brief the open incidents in inbox order and say which to open first; it reads, and changes nothing."""
        saved = preferences.get(profile_of(actor_of(http_request)))
        facts = merged_facts(
            *(known_figures(service.get(incident_id)["state"]) for incident_id in INCIDENT_IDS),
            with_preference_figures({}, saved), figures_in(request.question))
        async with agent_client(followup_client or bedrock_client, BRIEFING_TURNS, http_request) as (client, run_mode, fallback):
            try:
                run = await brief_with_bedrock(
                    app, client, request.question, saved,
                    access_token=agent_token(http_request), internal_key=internal_key, facts=facts,
                )
            except BedrockError as exc:
                logger.warning("Briefing failed (%s mode): %s", run_mode, exc)
                raise
        found = START_WITH.search(run["answer"])
        start_with = found.group(1).upper() if found and found.group(1).upper() in INCIDENT_IDS else None
        return {**shown_run(labelled(run, run_mode, fallback), []), "start_with": start_with}

    @app.post("/incidents/{incident_id}/approvals")
    async def approve(incident_id: str, request: ApprovalRequest) -> dict[str, Any]:
        return service.approve(incident_id, request.plan_id, request.source_version, request.approved_by)

    @app.post("/incidents/{incident_id}/execute")
    async def execute(incident_id: str, request: ExecutionRequest) -> dict[str, Any]:
        return service.execute(incident_id, request.plan_id, request.source_version)

    @app.post("/incidents/{incident_id}/bookings/quote")
    async def quote_booking(incident_id: str, http_request: Request, request: QuoteRequest | None = None) -> dict[str, Any]:
        """Price the paid carriers and services of a current plan (the approved one by default):
        cost, service fee and IGV 18 %, valid for ten minutes. A quote charges nothing."""
        return bookings.quote(incident_id, request.plan_id if request else None, actor_of(http_request))

    @app.post("/quotes/{quote_id}/confirm")
    async def confirm_booking(quote_id: str, http_request: Request, request: BookingConfirmation) -> dict[str, Any]:
        """Book and pay a quote once. The confirmed total must equal the quoted total recalculated now,
        the quote must be valid, and the plan approved; the same idempotency key returns the same booking."""
        return bookings.confirm(quote_id, request.confirmed_total_usd, request.idempotency_key, actor_of(http_request))

    @app.get("/bookings/{number}")
    async def get_booking(number: str) -> dict[str, Any]:
        return bookings.get(number)

    @app.get("/bookings/{number}/receipt", response_class=HTMLResponse)
    async def booking_receipt(number: str) -> HTMLResponse:
        """A printable receipt."""
        return HTMLResponse(receipt_html(bookings.get(number)), headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
                                       "form-action 'none'; frame-ancestors 'none'",
        })

    app.mount("/", mcp.streamable_http_app())
    return app


app = create_app()
