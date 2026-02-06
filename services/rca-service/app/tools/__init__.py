from __future__ import annotations

from ..loki_client import LokiClient
from .loki_collect_evidence import make_loki_collect_evidence
from .prometheus_query_range import prometheus_query_range
from .jaeger_query_traces import jaeger_query_traces


def build_tools(loki: LokiClient):
    loki_tool = make_loki_collect_evidence(loki)
    return [loki_tool, prometheus_query_range, jaeger_query_traces]
