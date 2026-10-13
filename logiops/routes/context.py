"""What every router needs: the stores, the clients and the settings create_app resolved."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

from ..agent import ConverseClient
from ..alerts import AlertWatcher
from ..bedrock import BedrockConverse
from ..booking import BookingStore
from ..budget import DailyModelBudget
from ..memory import MemoryService
from ..preferences import PreferenceStore
from ..service import LogiOpsService
from ..voice import PollyVoice


@dataclass(frozen=True)
class Context:
    app: FastAPI
    service: LogiOpsService
    preferences: PreferenceStore
    bookings: BookingStore
    alerts: AlertWatcher
    voice: PollyVoice
    memory: MemoryService
    budget: DailyModelBudget
    bedrock: BedrockConverse
    bedrock_client: ConverseClient | None
    followup_client: ConverseClient | None
    access_token: str | None
    internal_key: str
    public: bool
    public_host: str
    sandbox_host: str
    telemetry: str
    demo_page_html: str
    console_page_html: str
    demo_assets: dict[str, bytes]
    sandbox_page: str


def visible_plans(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    executions = snapshot["executions"]
    version = executions[0]["source_version"] if executions else snapshot["source_version"]
    return [plan for plan in snapshot["plans"] if plan["source_version"] == version]
