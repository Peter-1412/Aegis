from __future__ import annotations

from ..loki_client import LokiClient
from .trace_note import trace_note
from .predict_collect_features import make_predict_collect_features
from .prometheus_query_range import prometheus_query_range


def build_tools(loki: LokiClient):
    predict_tool = make_predict_collect_features(loki)
    return [trace_note, predict_tool, prometheus_query_range]
