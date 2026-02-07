from __future__ import annotations

from typing import Any, List, Optional

import ollama
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from .settings import settings


class OllamaChat(BaseChatModel):
    model: str
    host: str
    streaming: bool = False

    @property
    def _llm_type(self) -> str:
        return "ollama-chat"

    def _build_messages(self, messages: List[BaseMessage]) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        if settings.ollama_disable_thinking:
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

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> ChatResult:
        payload_messages = self._build_messages(messages)
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
        generation = ChatGeneration(message=AIMessage(content=content))
        return ChatResult(generations=[generation])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> ChatResult:
        payload_messages = self._build_messages(messages)
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
        generation = ChatGeneration(message=AIMessage(content=content))
        return ChatResult(generations=[generation])


def get_llm(streaming: bool = False) -> BaseChatModel:
    return OllamaChat(
        model=settings.ollama_model,
        host=settings.ollama_base_url,
        streaming=streaming,
    )
