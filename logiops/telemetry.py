"""Optional OpenTelemetry for the agent's runs: nothing is configured unless LOGIOPS_OTEL=1."""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping


def telemetry_from_env(environ: Mapping[str, str] | None = None, factory: Callable[[], Any] | None = None) -> str | None:
    """Set up the Strands tracer provider when LOGIOPS_OTEL=1: spans go to OTEL_EXPORTER_OTLP_ENDPOINT when it
    is set, to the console otherwise. Returns the exporter name, or None when telemetry stays off."""
    env = os.environ if environ is None else environ
    if env.get("LOGIOPS_OTEL", "").strip() != "1":
        return None
    if factory is None:
        from strands.telemetry import StrandsTelemetry

        factory = StrandsTelemetry
    telemetry = factory()
    if env.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        telemetry.setup_otlp_exporter()
        return "otlp"
    telemetry.setup_console_exporter()
    return "console"
