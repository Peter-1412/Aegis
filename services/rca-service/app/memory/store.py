from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from langchain.memory import ConversationBufferMemory


_memories: dict[str, tuple[ConversationBufferMemory, datetime]] = {}


def get_memory(session_id: str | None) -> ConversationBufferMemory | None:
    if not session_id:
        return None
    now = datetime.now(timezone.utc)
    ttl = timedelta(hours=1)
    expired = 0
    for key, (_, ts) in list(_memories.items()):
        if now - ts > ttl:
            _memories.pop(key, None)
            expired += 1
    if expired:
        logging.info("memory cleanup, expired=%s, remaining=%s", expired, len(_memories))
    existing = _memories.get(session_id)
    if existing is not None:
        memory, _ = existing
        _memories[session_id] = (memory, now)
        logging.info("memory hit, session_id=%s", session_id)
        return memory
    memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
    _memories[session_id] = (memory, now)
    logging.info("memory created, session_id=%s, total=%s", session_id, len(_memories))
    return memory
