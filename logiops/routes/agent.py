"""The agent's jobs: investigate an incident, answer a follow-up, brief the queue."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from ..agent import (
    BRIEFING_TURNS, FOLLOWUP_TURNS, INVESTIGATE_TURNS, ConverseClient, ask_with_bedrock, brief_with_bedrock,
    investigate_with_bedrock, merged_facts,
)
from ..strands_runtime import OnStep
from ..bedrock import BedrockError, BedrockUnavailable
from ..budget import FALLBACK, BudgetedConverse
from ..evaluator import figures_in
from ..identity import actor_of, profile_of
from ..preferences import preference_for, with_preference_figures
from ..presentation import shown_run
from ..replay import ReplayConverse
from ..scenario import incident_ids, known_figures
from ..service import WorkflowError
from .context import Context
from .models import PLAN_FIELDS, AgentAskRequest, AgentBriefingRequest, AgentInvestigationRequest

logger = logging.getLogger(__name__)
PING_SECONDS = 10
UNAVAILABLE = "model_unavailable"
REST_SECONDS = 300
START_WITH = re.compile(r"start with[*_`]*\s*[:：]\s*[*_`]*\s*(SHIP-\d+)", re.I)


def router(ctx: Context) -> APIRouter:
    app, service, preferences, bookings, memory, budget, bedrock = (
        ctx.app, ctx.service, ctx.preferences, ctx.bookings, ctx.memory, ctx.budget, ctx.bedrock)
    bedrock_client, followup_client, access_token, internal_key, public = (
        ctx.bedrock_client, ctx.followup_client, ctx.access_token, ctx.internal_key, ctx.public)
    routes = APIRouter()
    outage = {"until": 0.0}

    async def remembered(request: Request, question: str, run_mode: str) -> list[str]:
        """Long-term facts about the person, for a live run only (the replay model ignores them)."""
        if run_mode == "replay":
            return []
        return (await asyncio.to_thread(memory.recall, actor_of(request), None, question)).get("facts", [])

    @asynccontextmanager
    async def agent_client(
        custom: ConverseClient | None, max_calls: int, request: Request | None = None,
    ) -> AsyncIterator[tuple[ConverseClient, str, str | None]]:
        """(client, mode, fallback) for one agent request. A live request first reserves its run's
        maximum calls from the daily budget and releases what it did not use; when the run no longer
        fits, it runs on the replay model with fallback "daily_budget". For REST_SECONDS after the model
        service failed, live requests run on the replay model with fallback "model_unavailable". A guest
        on the public deployment always runs on the replay model, with fallback "sign_in"."""
        mode = os.environ.get("LOGIOPS_AGENT_MODE", "bedrock")
        if mode not in ("bedrock", "replay"):
            raise BedrockError("LOGIOPS_AGENT_MODE must be bedrock or replay")
        if public and request is not None and actor_of(request).kind == "guest":
            yield ReplayConverse(), "replay", "sign_in"
        elif custom:
            yield custom, "custom", None
        elif mode == "replay":
            yield ReplayConverse(), "replay", None
        elif time.monotonic() < outage["until"]:
            yield ReplayConverse(), "replay", UNAVAILABLE
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

    async def attempt(
        job: str, incident_id: str | None, custom: ConverseClient | None, max_calls: int, request: Request,
        go: Callable[[ConverseClient, str], Awaitable[dict[str, Any]]], restart: Callable[[], Awaitable[None]] | None = None,
    ) -> tuple[dict[str, Any], str, str | None]:
        """(run, mode, fallback) for one agent job. A failed run is recorded; when the live model service
        itself failed, the job runs again on the replay model with fallback "model_unavailable", after the
        live run gave back its unused calls. The agent's own guards still fail the request."""
        async with agent_client(custom, max_calls, request) as (client, run_mode, fallback):
            try:
                return await go(client, run_mode), run_mode, fallback
            except BedrockError as exc:
                unavailable = run_mode == "bedrock" and isinstance(exc, BedrockUnavailable)
                failure = {"job": job, "mode": run_mode, "error": str(exc), **({"fallback": UNAVAILABLE} if unavailable else {})}
                if incident_id is None:
                    logger.warning("Briefing failed (%s mode): %s", run_mode, exc)
                else:
                    service.record_agent_event(incident_id, "agent_run_failed", failure)
                if not unavailable:
                    raise
                outage["until"] = time.monotonic() + REST_SECONDS
        if restart is not None:
            await restart()
        return await go(ReplayConverse(), "replay"), "replay", UNAVAILABLE

    async def investigation(
        incident_id: str, question: str, http_request: Request, on_step: OnStep | None = None,
        on_restart: Callable[[], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        snapshot = service.get(incident_id)
        source_version = snapshot["source_version"]
        facts = with_preference_figures(known_figures(snapshot["state"]), preferences.get(profile_of(actor_of(http_request))))

        async def go(client: ConverseClient, run_mode: str) -> dict[str, Any]:
            recalled = await remembered(http_request, question, run_mode)
            return await investigate_with_bedrock(
                app, client, incident_id, question + memory.block({"facts": recalled}),
                access_token=agent_token(http_request), internal_key=internal_key,
                facts=merged_facts(facts, figures_in(" ".join(recalled))) if recalled else facts, on_step=on_step,
            )

        run, run_mode, fallback = await attempt("investigate", incident_id, bedrock_client, INVESTIGATE_TURNS, http_request, go, on_restart)
        run = labelled(run, run_mode, fallback)
        recorded = service.record_agent_run(incident_id, source_version, run)
        picked = run["evaluations"][-1].get("recommended_plan_id") if run.get("evaluations") else None
        return {**shown_run(run, recorded["plans"]), **recorded, "recommended_plan_id": picked}

    @routes.post("/incidents/{incident_id}/agent/investigate")
    async def agent_investigate(incident_id: str, request: AgentInvestigationRequest, http_request: Request) -> dict[str, Any]:
        return await investigation(incident_id, request.question, http_request)

    @routes.post("/incidents/{incident_id}/agent/investigate/stream")
    async def agent_investigate_stream(incident_id: str, request: AgentInvestigationRequest, http_request: Request) -> StreamingResponse:
        """The same investigation as server-sent events: a `step` for each MCP tool call as it returns, a
        `ping` every PING_SECONDS while the model thinks, then `done` with exactly what the plain route
        returns, or `error` with its status and detail. The steps are tool calls, not model tokens. When the
        live model fails mid-run, a `restart` says the steps begin again on the replay model."""
        service.get(incident_id)
        events: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def on_step(step: dict[str, Any]) -> None:
            await events.put(("step", step))

        async def on_restart() -> None:
            await events.put(("restart", {"fallback": UNAVAILABLE}))

        async def run() -> None:
            try:
                await events.put(("done", await investigation(incident_id, request.question, http_request, on_step, on_restart)))
            except WorkflowError as exc:
                await events.put(("error", {"status": exc.status_code, "detail": str(exc)}))
            except BedrockError as exc:
                await events.put(("error", {"status": 502, "detail": str(exc)}))
            except Exception:
                logger.exception("streamed investigation of %s failed", incident_id)
                await events.put(("error", {"status": 500, "detail": "The investigation failed"}))

        async def stream() -> AsyncIterator[str]:
            task = asyncio.create_task(run())
            try:
                while True:
                    try:
                        kind, data = await asyncio.wait_for(events.get(), PING_SECONDS)
                    except asyncio.TimeoutError:
                        yield "event: ping\ndata: {}\n\n"
                        continue
                    yield f"event: {kind}\ndata: {json.dumps(jsonable_encoder(data))}\n\n"
                    if kind not in ("step", "restart"):
                        return
            finally:
                if not task.done():
                    task.cancel()

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"})

    @routes.post("/incidents/{incident_id}/agent/ask")
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

        async def go(client: ConverseClient, run_mode: str) -> dict[str, Any]:
            recalled = await remembered(http_request, request.question, run_mode)
            return await ask_with_bedrock(
                app, client, incident_id, request.question, {**context, "memory": recalled} if recalled else context,
                [turn.model_dump() for turn in request.history],
                access_token=agent_token(http_request), internal_key=internal_key,
                facts=merged_facts(facts, figures_in(" ".join(recalled))) if recalled else facts,
                plans=[plan for plan in snapshot["plans"] if plan["source_version"] == version],
            )

        run, run_mode, fallback = await attempt("ask", incident_id, followup_client or bedrock_client, FOLLOWUP_TURNS, http_request, go)
        return {**shown_run(labelled(run, run_mode, fallback), context["plans"]), "source_version": version}

    @routes.post("/agent/briefing")
    async def agent_briefing(request: AgentBriefingRequest, http_request: Request) -> dict[str, Any]:
        """Brief the open incidents in inbox order and say which to open first; it reads, and changes nothing."""
        saved = preferences.get(profile_of(actor_of(http_request)))
        facts = merged_facts(
            *(known_figures(service.get(incident_id)["state"]) for incident_id in incident_ids()),
            with_preference_figures({}, saved), figures_in(request.question))

        async def go(client: ConverseClient, _run_mode: str) -> dict[str, Any]:
            return await brief_with_bedrock(
                app, client, request.question, saved,
                access_token=agent_token(http_request), internal_key=internal_key, facts=facts,
            )

        run, run_mode, fallback = await attempt("briefing", None, followup_client or bedrock_client, BRIEFING_TURNS, http_request, go)
        found = START_WITH.search(run["answer"])
        start_with = found.group(1).upper() if found and found.group(1).upper() in incident_ids() else None
        return {**shown_run(labelled(run, run_mode, fallback), []), "start_with": start_with}

    return routes
