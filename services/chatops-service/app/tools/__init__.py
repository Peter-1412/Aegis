from __future__ import annotations

from ..loki_client import LokiClient
from .trace_note import trace_note
from .loki_query_range_lines import make_loki_query_range_lines
from .prometheus_query_range import prometheus_query_range


def build_tools(loki: LokiClient):
    loki_query_tool = make_loki_query_range_lines(loki)
    return [trace_note, loki_query_tool, prometheus_query_range]
