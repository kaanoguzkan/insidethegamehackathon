"""Tracing: OpenTelemetry spans to Azure Application Insights, visible next to the agents in Microsoft Foundry.

Every request to the Brain becomes a trace. The Agent Framework adds a span for each agent run and each model call
(latency, token counts, model name), and ``run_fast`` adds one around a whole batch with the Router, Cache, Repairer
and deadline numbers as attributes. Prompts and answers are NOT recorded unless ``MATCHMIND_TRACE_CONTENT=1``.

Off unless ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set, and a failure here never stops the service.
"""

from __future__ import annotations

import os

_started = False


def setup_tracing(service_name: str = "matchmind-brain") -> bool:
    """Start exporting traces. Call once, before the web app object is created, so its requests are instrumented too."""
    global _started
    conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if _started or not conn:
        return _started
    try:
        os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
        from agent_framework.observability import enable_instrumentation
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(connection_string=conn)
        enable_instrumentation(enable_sensitive_data=os.environ.get("MATCHMIND_TRACE_CONTENT") == "1")
        _started = True
    except Exception as e:  # noqa: BLE001 - tracing is optional: say so and carry on
        print(f"WARN tracing is off: {type(e).__name__}: {e}", flush=True)
    return _started
