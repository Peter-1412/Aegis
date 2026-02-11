from __future__ import annotations

import inspect
import json
import logging
import os
from datetime import datetime, timezone

import httpx
import lark_oapi as lark
from dotenv import load_dotenv
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

try:
    from lark_oapi.api.im.v1 import P2ImChatAccessEventBotP2pChatEnteredV1
except Exception:
    P2ImChatAccessEventBotP2pChatEnteredV1 = None


load_dotenv()


OPS_SERVICE_BASE_URL = os.getenv("OPS_SERVICE_BASE_URL", "http://localhost:8002")
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID") or ""
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET") or ""
DEFAULT_CHAT_ID = os.getenv("FEISHU_DEFAULT_CHAT_ID") or ""

PROCESSED_MESSAGE_IDS: set[str] = set()


logger = logging.getLogger(__name__)


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": "feishu-ws",
            "msg": record.getMessage(),
        }
        try:
            if record.exc_info:
                payload["exc"] = self.formatException(record.exc_info)
        except Exception:
            pass
        return json.dumps(payload, ensure_ascii=False)


def _on_im_message(data: P2ImMessageReceiveV1) -> None:
    event = data.event
    if event is None or event.message is None:
        logger.info("feishu ws message ignored: empty event")
        return
    message = event.message
    msg_id = getattr(message, "message_id", None)
    if msg_id:
        if msg_id in PROCESSED_MESSAGE_IDS:
            logger.info("duplicate feishu message ignored, message_id=%s", msg_id)
            return
        PROCESSED_MESSAGE_IDS.add(msg_id)
        if len(PROCESSED_MESSAGE_IDS) > 1000:
            PROCESSED_MESSAGE_IDS.pop()
    chat_id = message.chat_id or DEFAULT_CHAT_ID
    if not chat_id:
        logger.warning("feishu ws message missing chat_id, msg_id=%s", msg_id)
        return
    content_raw = message.content or "{}"
    try:
        content_obj = json.loads(content_raw)
    except Exception:
        content_obj = {}
    text = str(content_obj.get("text") or "").strip()
    if not text:
        logger.info("received empty text, ignore, chat_id=%s", chat_id)
        return
    logger.info("received feishu message, chat_id=%s, text=%s", chat_id, text)
    url = f"{OPS_SERVICE_BASE_URL}/feishu/receive"
    payload = {"chat_id": chat_id, "text": text}
    try:
        with httpx.Client(timeout=600.0) as client:
            r = client.post(url, json=payload)
        logger.info("forwarded to ops-service, status=%s", r.status_code)
        r.raise_for_status()
    except Exception as exc:
        logger.exception("forward feishu message failed: %s", exc)


def _on_bot_p2p_chat_entered(data: P2ImChatAccessEventBotP2pChatEnteredV1) -> None:
    logger.info("ignored bot_p2p_chat_entered event")


def main() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = _JSONFormatter()
    if root.handlers:
        for handler in root.handlers:
            handler.setFormatter(formatter)
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root.addHandler(handler)
    logger.info(
        "starting feishu ws client, base_url=%s, has_app_id=%s, has_app_secret=%s",
        OPS_SERVICE_BASE_URL,
        bool(FEISHU_APP_ID),
        bool(FEISHU_APP_SECRET),
    )
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        raise RuntimeError("FEISHU_APP_ID / FEISHU_APP_SECRET 未配置")
    client = lark.Client.builder().app_id(FEISHU_APP_ID).app_secret(FEISHU_APP_SECRET).build()
    builder = lark.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(_on_im_message)
    if P2ImChatAccessEventBotP2pChatEnteredV1 is not None and hasattr(
        builder, "register_p2_im_chat_access_event_bot_p2p_chat_entered_v1"
    ):
        builder = builder.register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(_on_bot_p2p_chat_entered)
    elif hasattr(builder, "register"):
        builder = builder.register("im.chat.access_event.bot_p2p_chat_entered_v1", _on_bot_p2p_chat_entered)
    else:
        logger.warning("bot_p2p_chat_entered handler not registered due to sdk version")
    handler = builder.build()
    ws_args = []
    if hasattr(lark.ws, "WithLogLevel"):
        ws_args.append(lark.ws.WithLogLevel(logging.INFO))
    if hasattr(lark.ws, "WithEventHandler"):
        ws_args.append(lark.ws.WithEventHandler(handler))
    else:
        logger.warning("WithEventHandler not available, fallback to legacy args")
    if hasattr(lark.ws, "WithReconnectInterval"):
        ws_args.append(lark.ws.WithReconnectInterval(5))

    use_client = True
    param_names: list[str] = []
    try:
        sig = inspect.signature(lark.ws.Client)
        param_names = [p.name for p in sig.parameters.values()]
        if "app_id" in param_names or "appId" in param_names:
            use_client = False
        elif "client" in param_names:
            use_client = True
    except Exception:
        use_client = True

    ws = None
    if use_client:
        try:
            ws = lark.ws.Client(client, *ws_args)
            logger.info("feishu ws client started with client object")
        except Exception as exc:
            logger.warning("ws client init with client failed: %s", exc)
    if ws is None:
        try:
            kwargs = {}
            if "event_handler" in param_names:
                kwargs["event_handler"] = handler
            elif "handler" in param_names:
                kwargs["handler"] = handler
            if "log_level" in param_names and hasattr(lark.ws, "LogLevel"):
                kwargs["log_level"] = lark.ws.LogLevel.INFO
            ws = lark.ws.Client(FEISHU_APP_ID, FEISHU_APP_SECRET, **kwargs)
            logger.info("feishu ws client started with app_id/app_secret")
        except Exception as exc:
            logger.error("ws client init failed: %s", exc)
            raise
    ws.start()


if __name__ == "__main__":
    main()
