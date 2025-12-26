from __future__ import annotations

import os

from langchain_core.language_models.chat_models import BaseChatModel

from .settings import settings


def get_llm() -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    api_key = settings.ark_api_key or os.environ.get("ARK_API_KEY")
    base_url = settings.ark_base_url or os.environ.get("ARK_BASE_URL")

    return ChatOpenAI(
        model=settings.llm_model,
        api_key=api_key,
        base_url=base_url,
        temperature=0,
    )
