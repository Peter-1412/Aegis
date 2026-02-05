from __future__ import annotations

from ..loki_client import LokiClient
from .trace_note import trace_note
from .rca_collect_evidence import make_rca_collect_evidence
from .prometheus_query_range import prometheus_query_range
from .jaeger_query_traces import jaeger_query_traces


def build_tools(loki: LokiClient):
    rca_tool = make_rca_collect_evidence(loki)
    return [trace_note, rca_tool, prometheus_query_range, jaeger_query_traces]
