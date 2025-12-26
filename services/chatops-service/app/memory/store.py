from __future__ import annotations

from datetime import datetime, timedelta, timezone

from langchain.memory import ConversationBufferMemory


_memories: dict[str, tuple[ConversationBufferMemory, datetime]] = {}


def get_memory(session_id: str | None) -> ConversationBufferMemory | None:
    if not session_id:
        return None
    now = datetime.now(timezone.utc)
    ttl = timedelta(hours=1)
    for key, (_, ts) in list(_memories.items()):
        if now - ts > ttl:
            _memories.pop(key, None)
    existing = _memories.get(session_id)
    if existing is not None:
        memory, _ = existing
        _memories[session_id] = (memory, now)
        return memory
    memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
    _memories[session_id] = (memory, now)
    return memory

