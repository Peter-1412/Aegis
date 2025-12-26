from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx


def _dt_to_ns(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000_000)


@dataclass(frozen=True)
class LokiQueryResult:
    raw: dict

    def flatten_log_lines(self, limit: int | None = None) -> list[str]:
        data = self.raw.get("data", {})
        results = data.get("result", []) or []
        lines: list[str] = []
        for item in results:
            stream = item.get("stream", {}) or {}
            values = item.get("values", []) or []
            for ts, line in values:
                labels = ",".join(f"{k}={v}" for k, v in sorted(stream.items()))
                lines.append(f"{ts} [{labels}] {line}")
        if limit is not None:
            return lines[:limit]
        return lines

    def extract_instant_number(self) -> float | None:
        data = self.raw.get("data", {})
        results = data.get("result", []) or []
        total = 0.0
        any_value = False
        for item in results:
            value = item.get("value")
            if not value or len(value) < 2:
                continue
            try:
                total += float(value[1])
                any_value = True
            except Exception:
                continue
        return total if any_value else None


class LokiClient:
    def __init__(self, base_url: str, tenant_id: str | None, timeout_s: float):
        self._base_url = base_url.rstrip("/")
        self._tenant_id = tenant_id
        self._timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        if self._tenant_id:
            return {"X-Scope-OrgID": self._tenant_id}
        return {}

    async def labels(self) -> list[str]:
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            r = await client.get(f"{self._base_url}/loki/api/v1/labels", headers=self._headers())
        r.raise_for_status()
        return (r.json().get("data") or [])[:]

    async def label_values(self, label: str) -> list[str]:
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            r = await client.get(f"{self._base_url}/loki/api/v1/label/{label}/values", headers=self._headers())
        r.raise_for_status()
        return (r.json().get("data") or [])[:]

    async def query_range(
        self,
        query: str,
        start: datetime,
        end: datetime,
        limit: int = 200,
        direction: str = "BACKWARD",
        step_seconds: int | None = None,
    ) -> LokiQueryResult:
        params: dict[str, str | int] = {
            "query": query,
            "start": _dt_to_ns(start),
            "end": _dt_to_ns(end),
            "limit": limit,
            "direction": direction,
        }
        if step_seconds is not None:
            params["step"] = step_seconds
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            r = await client.get(f"{self._base_url}/loki/api/v1/query_range", params=params, headers=self._headers())
        r.raise_for_status()
        return LokiQueryResult(raw=r.json())

    async def query_instant(self, query: str, at: datetime) -> LokiQueryResult:
        params: dict[str, str | int] = {"query": query, "time": _dt_to_ns(at)}
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            r = await client.get(f"{self._base_url}/loki/api/v1/query", params=params, headers=self._headers())
        r.raise_for_status()
        return LokiQueryResult(raw=r.json())

