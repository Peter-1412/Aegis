from __future__ import annotations

from typing import Any, List, Optional
import logging
import time
import os

import ollama
from openai import OpenAI, AsyncOpenAI
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
            "llm generate done, model=%s, duration_s=%.3f, output_len=%s, content=%s",
            self.model,
            dt,
            len(content),
            content[:500].replace("\n", "\\n") + ("..." if len(content) > 500 else ""),
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
            "llm agenerate done, model=%s, duration_s=%.3f, output_len=%s, content=%s",
            self.model,
            dt,
            len(content),
            content[:500].replace("\n", "\\n") + ("..." if len(content) > 500 else ""),
        )
        return ChatResult(generations=[generation])


class DoubaoChat(BaseChatModel):
    model: str
    base_url: str
    api_key: str | None
    streaming: bool = False
    thinking_enabled: bool = True
    thinking_effort: str = "high"

    @property
    def _llm_type(self) -> str:
        return "doubao-chat"

    def _build_messages(self, messages: List[BaseMessage]) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
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

    def _format_prompt(self, messages: List[BaseMessage]) -> str:
        items = self._build_messages(messages)
        parts: list[str] = []
        for item in items:
            role = item.get("role") or "user"
            content = item.get("content") or ""
            parts.append(f"{role}: {content}")
        return "\n\n".join(parts).strip()

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

    def _build_extra_body(self) -> dict[str, Any]:
        if self.thinking_enabled:
            return {"thinking": {"type": "enabled"}}
        return {"thinking": {"type": "disabled"}}

    def _extract_content(self, response: Any) -> str:
        content = ""
        try:
            content = str(getattr(response, "output_text", "") or "")
            if content:
                return content
            output = getattr(response, "output", None) or []
            for item in output:
                parts = getattr(item, "content", None) or []
                for part in parts:
                    text = getattr(part, "text", None)
                    if text:
                        content += str(text)
        except Exception:
            content = ""
        return content.strip()

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> ChatResult:
        t0 = time.monotonic()
        if not self.api_key:
            raise RuntimeError("doubao api_key 未配置")
        prompt = self._format_prompt(messages)
        logging.info(
            "llm generate start, model=%s, msg_len=%s, streaming=%s",
            self.model,
            len(prompt),
            self.streaming,
        )
        client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        res = client.responses.create(
            model=self.model,
            input=prompt,
            temperature=settings.doubao_temperature,
            max_output_tokens=settings.doubao_max_tokens,
            extra_body=self._build_extra_body(),
        )
        content = self._extract_content(res)
        content = self._apply_stop(content, stop)
        generation = ChatGeneration(message=AIMessage(content=content))
        dt = time.monotonic() - t0
        logging.info(
            "llm generate done, model=%s, duration_s=%.3f, output_len=%s, content=%s",
            self.model,
            dt,
            len(content),
            content[:500].replace("\n", "\\n") + ("..." if len(content) > 500 else ""),
        )
        return ChatResult(generations=[generation])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> ChatResult:
        t0 = time.monotonic()
        if not self.api_key:
            raise RuntimeError("doubao api_key 未配置")
        prompt = self._format_prompt(messages)
        logging.info(
            "llm agenerate start, model=%s, msg_len=%s, streaming=%s",
            self.model,
            len(prompt),
            self.streaming,
        )
        client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
        res = await client.responses.create(
            model=self.model,
            input=prompt,
            temperature=settings.doubao_temperature,
            max_output_tokens=settings.doubao_max_tokens,
            extra_body=self._build_extra_body(),
        )
        content = self._extract_content(res)
        content = self._apply_stop(content, stop)
        generation = ChatGeneration(message=AIMessage(content=content))
        dt = time.monotonic() - t0
        logging.info(
            "llm agenerate done, model=%s, duration_s=%.3f, output_len=%s, content=%s",
            self.model,
            dt,
            len(content),
            content[:500].replace("\n", "\\n") + ("..." if len(content) > 500 else ""),
        )
        return ChatResult(generations=[generation])


def _normalize_model_name(name: str | None) -> str:
    if not name:
        return settings.default_model
    lowered = name.strip().lower()
    if lowered in {"qwen", "glm", "deepseek", "doubao"}:
        return lowered
    return settings.default_model


def get_llm(model_name: str | None = None, streaming: bool = False, allow_thinking: bool = False) -> BaseChatModel:
    selected = _normalize_model_name(model_name)
    if selected == "doubao":
        api_key = settings.doubao_api_key or os.getenv("ARK_API_KEY")
        logging.info(
            "llm init, model=%s, base_url=%s, streaming=%s",
            settings.doubao_model,
            settings.doubao_base_url,
            streaming,
        )
        return DoubaoChat(
            model=settings.doubao_model,
            base_url=settings.doubao_base_url,
            api_key=api_key,
            streaming=streaming,
            thinking_enabled=settings.doubao_thinking_enabled,
            thinking_effort=settings.doubao_thinking_effort,
        )
    if selected == "glm":
        model = settings.ollama_glm_model
    elif selected == "deepseek":
        model = settings.ollama_deepseek_model
    else:
        model = settings.ollama_qwen_model
    logging.info(
        "llm init, model=%s, base_url=%s, streaming=%s",
        model,
        settings.ollama_base_url,
        streaming,
    )
    return OllamaChat(
        model=model,
        host=settings.ollama_base_url,
        streaming=streaming,
        disable_thinking=settings.ollama_disable_thinking and not allow_thinking,
    )
