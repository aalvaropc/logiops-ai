"""Scenario packs: the built-in template and your own incidents."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..scenario import PACK_VERSION, ScenarioPackError, builtin_incidents, register_pack
from .context import Context
from .models import ScenarioPack


def router(ctx: Context) -> APIRouter:
    service = ctx.service
    routes = APIRouter()

    @routes.get("/scenario/packs/builtin")
    async def builtin_pack() -> dict[str, Any]:
        """The four built-in incidents in pack form: the template for a pack of your own."""
        return {"version": PACK_VERSION, "incidents": builtin_incidents()}

    @routes.post("/scenario/packs", status_code=201)
    async def upload_pack(pack: ScenarioPack) -> dict[str, Any]:
        """Register the incidents of a scenario pack and seed them; they live in this process until it restarts
        (set LOGIOPS_SCENARIO_PACK to load a pack at every start). A pack with one bad incident registers nothing."""
        try:
            registered = register_pack(pack.model_dump())
        except ScenarioPackError as exc:
            raise HTTPException(status_code=422, detail={"message": "The pack was not registered", "errors": exc.errors}) from exc
        service.seed_missing()
        return {"registered": registered, "incidents": service.list_incidents()}

    return routes
