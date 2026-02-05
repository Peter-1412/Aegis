from __future__ import annotations

import json
import logging
import os

import httpx
import lark_oapi as lark
from dotenv import load_dotenv
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1


load_dotenv()


RCA_SERVICE_BASE_URL = os.getenv("RCA_SERVICE_BASE_URL", "http://localhost:8002")
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID") or ""
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET") or ""
DEFAULT_CHAT_ID = os.getenv("FEISHU_DEFAULT_CHAT_ID") or ""


def _on_im_message(data: P2ImMessageReceiveV1) -> None:
    event = data.event
    if event is None or event.message is None:
        return
    message = event.message
    chat_id = message.chat_id or DEFAULT_CHAT_ID
    if not chat_id:
        return
    content_raw = message.content or "{}"
    try:
        content_obj = json.loads(content_raw)
    except Exception:
        content_obj = {}
    text = str(content_obj.get("text") or "").strip()
    if not text:
        logging.info("received empty text, ignore, chat_id=%s", chat_id)
        return
    logging.info("received feishu message, chat_id=%s, text=%s", chat_id, text)
    url = f"{RCA_SERVICE_BASE_URL}/feishu/receive"
    payload = {"chat_id": chat_id, "text": text}
    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.post(url, json=payload)
        logging.info("forwarded to rca-service, status=%s", r.status_code)
        r.raise_for_status()
    except Exception as exc:
        logging.exception("forward feishu message failed: %s", exc)


def main() -> None:
    app_id = FEISHU_APP_ID
    app_secret = FEISHU_APP_SECRET
    if not app_id or not app_secret:
        logging.error("Feishu app_id 或 app_secret 未配置")
        return
    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_on_im_message)
        .build()
    )
    cli = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )
    cli.start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
