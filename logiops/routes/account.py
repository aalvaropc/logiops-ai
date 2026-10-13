"""The person's side: saved preferences, remembered conversations and the voice."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse, Response

from ..identity import actor_of, profile_of
from ..preferences import RULES
from ..scenario import incident_ids
from ..service import WorkflowError
from .context import Context
from .models import MemoryTurn, PreferenceUpdate, SpeechRequest


def router(ctx: Context) -> APIRouter:
    preferences, memory, voice = ctx.preferences, ctx.memory, ctx.voice
    routes = APIRouter()

    @routes.get("/operator/preferences")
    async def get_preferences(request: Request) -> dict[str, Any]:
        """Your saved preferences (they persist across sessions; a signed-in user has their own) and the rules on offer."""
        return {"preferences": preferences.get(profile_of(actor_of(request))), "rules": RULES}

    @routes.put("/operator/preferences")
    async def put_preferences(update: PreferenceUpdate, request: Request) -> dict[str, Any]:
        """Save preferences for every incident; they steer the pick and never approve a plan."""
        try:
            saved = preferences.put(update.rule, update.max_cost_usd, update.note, subject=profile_of(actor_of(request)))
        except ValueError as exc:
            raise WorkflowError(str(exc), 422) from exc
        return {"preferences": saved, "rules": RULES}

    @routes.delete("/operator/preferences")
    async def clear_preferences(request: Request) -> dict[str, Any]:
        preferences.clear(profile_of(actor_of(request)))
        return {"preferences": None, "rules": RULES}

    @routes.post("/memory/turns", status_code=202)
    async def remember_turn(turn: MemoryTurn, request: Request, background: BackgroundTasks) -> dict[str, Any]:
        """Remember one turn of the conversation for the person asking (never for a guest); written after the reply."""
        actor = actor_of(request)
        incident = turn.incident if turn.incident in incident_ids() else None
        background.add_task(memory.remember, actor, turn.session, turn.role, turn.text, incident)
        return {"accepted": actor.kind != "guest", "backend": memory.backend}

    @routes.get("/memory")
    async def recall(request: Request, session: str | None = None) -> dict[str, Any]:
        """What the person said in their previous session, a welcome-back line, and long-term facts."""
        return await asyncio.to_thread(memory.recall, actor_of(request), session)

    @routes.delete("/memory")
    async def forget(request: Request) -> dict[str, Any]:
        """Forget me: delete the person's remembered turns and records."""
        return {"forgotten": await asyncio.to_thread(memory.forget, actor_of(request)), "backend": memory.backend}

    @routes.get("/voice/config")
    async def voice_config() -> dict[str, Any]:
        """How the page should speak: Amazon Polly (with its voice) or the browser's own voice."""
        return voice.config()

    @routes.post("/voice/speech")
    async def speech(request: SpeechRequest) -> Response:
        """MP3 of the reply read by Amazon Polly, cached per text and capped per day. A 503 with
        fallback "browser" means the page reads it with the browser's voice instead."""
        audio = await asyncio.to_thread(voice.speak, request.text)
        if audio is None:
            return JSONResponse(status_code=503, content={"detail": "Polly is not available; use the browser's voice", "fallback": "browser"})
        return Response(audio, media_type="audio/mpeg")

    return routes
