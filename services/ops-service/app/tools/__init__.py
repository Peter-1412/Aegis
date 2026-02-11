from app.tools.jaeger_tool import jaeger_query_traces
from app.tools.loki_tool import LokiClient, make_loki_collect_evidence
from app.tools.prometheus_tool import prometheus_query_range


def build_tools(loki: LokiClient):
    return [
        prometheus_query_range,
        make_loki_collect_evidence(loki),
        jaeger_query_traces,
    ]
