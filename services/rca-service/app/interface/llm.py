from __future__ import annotations

from typing import Any, List, Optional
import logging
import time

import ollama
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from config.config import settings


class OllamaChat(BaseChatModel):
    model: str
    host: str
    streaming: bool = False
    disable_thinking: bool = True

    @property
    def _llm_type(self) -> str:
        return "ollama-chat"

    def _build_messages(self, messages: List[BaseMessage]) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        if self.disable_thinking:
            items.append(
                {
                    "role": "system",
                    "content": "不要输出思考过程或<think>标签，只给出最终答案，尽量简短直接。",
                }
            )
        for m in messages:
            role = getattr(m, "type", "") or getattr(m, "role", "")
            content = str(getattr(m, "content", "") or "")
            if not content:
                continue
            if role == "system":
                items.append({"role": "system", "content": content})
            elif role in ("human", "user"):
                items.append({"role": "user", "content": content})
            elif role in ("ai", "assistant"):
                items.append({"role": "assistant", "content": content})
            else:
                items.append({"role": "user", "content": content})
        return items

    def _strip_think_block(self, text: str) -> str:
        start = text.find("<think>")
        end = text.find("</think>")
        if start != -1 and end != -1 and end > start:
            head = text[:start]
            tail = text[end + len("</think>") :]
            return (head + tail).strip()
        return text

    def _apply_stop(self, text: str, stop: Optional[List[str]]) -> str:
        if not stop:
            return text
        earliest: int | None = None
        for token in stop:
            if not token:
                continue
            idx = text.find(token)
            if idx == -1:
                continue
            if earliest is None or idx < earliest:
                earliest = idx
        if earliest is None:
            return text
        return text[:earliest].rstrip()

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> ChatResult:
        t0 = time.monotonic()
        payload_messages = self._build_messages(messages)
        logging.info(
            "llm generate start, model=%s, msg_count=%s, streaming=%s",
            self.model,
            len(payload_messages),
            self.streaming,
        )
        options: dict[str, Any] = {
            "num_predict": settings.ollama_num_predict,
            "temperature": settings.ollama_temperature,
            "top_p": settings.ollama_top_p,
        }
        client = ollama.Client(host=self.host)
        res = client.chat(
            model=self.model,
            messages=payload_messages,
            stream=False,
            options=options,
        )
        content = ""
        try:
            message = res.get("message") or {}
            content = str(message.get("content") or "")
        except Exception:
            content = ""
        content = self._strip_think_block(content)
        content = self._apply_stop(content, stop)
        generation = ChatGeneration(message=AIMessage(content=content))
        dt = time.monotonic() - t0
        logging.info(
            "llm generate done, model=%s, duration_s=%.3f, output_len=%s",
            self.model,
            dt,
            len(content),
        )
        return ChatResult(generations=[generation])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> ChatResult:
        t0 = time.monotonic()
        payload_messages = self._build_messages(messages)
        logging.info(
            "llm agenerate start, model=%s, msg_count=%s, streaming=%s",
            self.model,
            len(payload_messages),
            self.streaming,
        )
        options: dict[str, Any] = {
            "num_predict": settings.ollama_num_predict,
            "temperature": settings.ollama_temperature,
            "top_p": settings.ollama_top_p,
        }
        client = ollama.AsyncClient(host=self.host)
        res = await client.chat(
            model=self.model,
            messages=payload_messages,
            stream=False,
            options=options,
        )
        content = ""
        try:
            message = res.get("message") or {}
            content = str(message.get("content") or "")
        except Exception:
            content = ""
        content = self._strip_think_block(content)
        content = self._apply_stop(content, stop)
        generation = ChatGeneration(message=AIMessage(content=content))
        dt = time.monotonic() - t0
        logging.info(
            "llm agenerate done, model=%s, duration_s=%.3f, output_len=%s",
            self.model,
            dt,
            len(content),
        )
        return ChatResult(generations=[generation])


def get_llm(streaming: bool = False, allow_thinking: bool = False) -> BaseChatModel:
    logging.info(
        "llm init, model=%s, base_url=%s, streaming=%s",
        settings.ollama_model,
        settings.ollama_base_url,
        streaming,
    )
    return OllamaChat(
        model=settings.ollama_model,
        host=settings.ollama_base_url,
        streaming=streaming,
        disable_thinking=settings.ollama_disable_thinking and not allow_thinking,
    )
