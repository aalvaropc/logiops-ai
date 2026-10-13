"""Telemetry is off unless asked for, and then goes to OTLP or the console; the agent's spans carry LogiOps attributes."""

import asyncio
from pathlib import Path

import httpx

from logiops.api import create_app
from logiops.telemetry import telemetry_from_env


class FakeTelemetry:
    instances: list["FakeTelemetry"] = []

    def __init__(self):
        self.calls = []
        FakeTelemetry.instances.append(self)

    def setup_otlp_exporter(self):
        self.calls.append("otlp")
        return self

    def setup_console_exporter(self):
        self.calls.append("console")
        return self


def test_nothing_is_configured_unless_asked_for():
    FakeTelemetry.instances.clear()
    assert telemetry_from_env({}, FakeTelemetry) is None
    assert telemetry_from_env({"LOGIOPS_OTEL": "0", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318"}, FakeTelemetry) is None
    assert FakeTelemetry.instances == []


def test_the_exporter_follows_the_endpoint():
    FakeTelemetry.instances.clear()
    assert telemetry_from_env({"LOGIOPS_OTEL": "1"}, FakeTelemetry) == "console"
    assert telemetry_from_env({"LOGIOPS_OTEL": "1", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318"}, FakeTelemetry) == "otlp"
    assert [instance.calls for instance in FakeTelemetry.instances] == [["console"], ["otlp"]]


def test_the_app_reports_its_telemetry_and_the_agent_spans_name_the_run(tmp_path, monkeypatch):
    monkeypatch.delenv("LOGIOPS_OTEL", raising=False)

    async def health(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return (await client.get("/healthz")).json()

    assert asyncio.run(health(create_app(tmp_path / "off.sqlite3"))) == {"status": "ok", "telemetry": "off"}
    import logiops.api as api

    monkeypatch.setattr(api, "telemetry_from_env", lambda: "console")
    assert asyncio.run(health(create_app(tmp_path / "on.sqlite3")))["telemetry"] == "console"
    agent = (Path(__file__).resolve().parents[1] / "logiops" / "agent.py").read_text()
    assert '"logiops.client": type(client).__name__' in agent and '"logiops.required_tool"' in agent
