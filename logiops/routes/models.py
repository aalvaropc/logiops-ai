"""Request bodies of the HTTP routes."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..preferences import COST_LIMIT, NOTE_LIMIT, RULES
from ..scenario import INCIDENT_ID
from ..service import APPROVER_MAX_LENGTH


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


class IncidentDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=40)
    kind: str = Field(min_length=1, max_length=40)
    kind_label: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    shipment: dict[str, Any]
    orders: list[dict[str, Any]] = Field(min_length=1, max_length=20)
    inventory: dict[str, dict[str, Any]] = Field(default_factory=dict)
    carriers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    options: list[dict[str, Any]] = Field(min_length=1, max_length=20)


class ScenarioPack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    incidents: list[IncidentDefinition] = Field(min_length=1, max_length=50)


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
