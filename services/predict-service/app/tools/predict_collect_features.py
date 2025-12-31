from __future__ import annotations

from datetime import datetime, timedelta, timezone

from langchain_core.tools import tool

from ..loki_client import LokiClient
from ..settings import settings


def make_predict_collect_features(loki: LokiClient):
    @tool("predict_collect_features", description="从 Loki 拉取错误计数时间序列与日志样本，作为预测特征。")
    async def predict_collect_features(service_name: str, lookback_hours: int = 24) -> dict:
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=lookback_hours)

        selector = settings.loki_selector_template.format(
            label_key=settings.loki_service_label_key,
            service=service_name,
        )
        error_regex = (
            r'(?i)('
            r'error|exception|traceback|panic|fatal|timeout|'
            r'unauthorized|forbidden|denied|permission denied|'
            r'authentication failed|login failed|invalid password|'
            r'4\d\d|5\d\d|'
            r'connection refused|connection reset'
            r')'
        )

        log_query = f'{selector} |~ "{error_regex}"'
        counts: list[float] = []
        evidence: list[str] = []
        bucket_count = max(1, int(lookback_hours * 60 / 5))
        buckets = [0.0] * bucket_count

        try:
            logs_res = await loki.query_range(log_query, start=start, end=now, limit=5000, direction="BACKWARD")
            data = logs_res.raw.get("data", {})
            results = data.get("result", []) or []
            for item in results:
                values = item.get("values") or []
                for ts, _line in values:
                    try:
                        ts_ns = float(ts)
                        dt = datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=timezone.utc)
                    except Exception:
                        continue
                    if dt < start or dt > now:
                        continue
                    offset_s = (dt - start).total_seconds()
                    idx = int(offset_s // 300)
                    if 0 <= idx < bucket_count:
                        buckets[idx] += 1.0
            counts = buckets
            evidence = logs_res.flatten_log_lines(limit=120)
        except Exception:
            counts = []
            evidence = []

        return {
            "service_name": service_name,
            "lookback_hours": lookback_hours,
            "counts": counts[-288:],
            "logs": evidence,
            "logql": log_query,
            "loki_api": {"path": "/loki/api/v1/query_range"},
        }

    return predict_collect_features
