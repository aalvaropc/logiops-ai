"""The agent's jobs: investigate an incident, answer a follow-up, brief the queue."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import APIRouter, Request

from ..agent import (
    BRIEFING_TURNS, FOLLOWUP_TURNS, INVESTIGATE_TURNS, ConverseClient, ask_with_bedrock, brief_with_bedrock,
    investigate_with_bedrock, merged_facts,
)
from ..bedrock import BedrockError
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
START_WITH = re.compile(r"start with[*_`]*\s*[:：]\s*[*_`]*\s*(SHIP-\d+)", re.I)


def router(ctx: Context) -> APIRouter:
    app, service, preferences, bookings, memory, budget, bedrock = (
        ctx.app, ctx.service, ctx.preferences, ctx.bookings, ctx.memory, ctx.budget, ctx.bedrock)
    bedrock_client, followup_client, access_token, internal_key, public = (
        ctx.bedrock_client, ctx.followup_client, ctx.access_token, ctx.internal_key, ctx.public)
    routes = APIRouter()

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

    @routes.post("/incidents/{incident_id}/agent/investigate")
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

    @routes.post("/agent/briefing")
    async def agent_briefing(request: AgentBriefingRequest, http_request: Request) -> dict[str, Any]:
        """Brief the open incidents in inbox order and say which to open first; it reads, and changes nothing."""
        saved = preferences.get(profile_of(actor_of(http_request)))
        facts = merged_facts(
            *(known_figures(service.get(incident_id)["state"]) for incident_id in incident_ids()),
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
        start_with = found.group(1).upper() if found and found.group(1).upper() in incident_ids() else None
        return {**shown_run(labelled(run, run_mode, fallback), []), "start_with": start_with}

    return routes
