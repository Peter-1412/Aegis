from __future__ import annotations

import time
from typing import Any
import json

import httpx

from .settings import settings


class FeishuClient:
    def __init__(self):
        self._tenant_access_token: str | None = None
        self._expire_at: float = 0.0

    async def _refresh_token(self) -> str:
        app_id = settings.feishu_app_id
        app_secret = settings.feishu_app_secret
        if not app_id or not app_secret:
            raise RuntimeError("Feishu app_id 或 app_secret 未配置")
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {"app_id": app_id, "app_secret": app_secret}
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
        code = data.get("code", 0)
        if code != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: code={code}, msg={data.get('msg')}")
        token = data.get("tenant_access_token")
        expire = data.get("expire", 3600)
        self._tenant_access_token = token
        self._expire_at = time.time() + float(expire) * 0.9
        return token

    async def _get_token(self) -> str:
        now = time.time()
        if self._tenant_access_token and now < self._expire_at:
            return self._tenant_access_token
        return await self._refresh_token()

    async def send_text_message(self, chat_id: str, text: str) -> dict[str, Any]:
        token = await self._get_token()
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        params = {"receive_id_type": "chat_id"}
        headers = {"Authorization": f"Bearer {token}"}
        body = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, params=params, json=body, headers=headers)
        data = r.json()
        if r.status_code >= 400 or data.get("code", 0) != 0:
            raise RuntimeError(f"发送飞书消息失败: http={r.status_code}, code={data.get('code')}, msg={data.get('msg')}")
        return data


feishu_client = FeishuClient()
