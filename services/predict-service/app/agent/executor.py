from __future__ import annotations

from langchain.agents import AgentExecutor
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.memory import ConversationBufferMemory


try:
    from langchain.agents import create_tool_calling_agent
except Exception:
    from langchain.agents import create_openai_functions_agent as create_tool_calling_agent


def build_executor(llm: BaseChatModel, tools, memory: ConversationBufferMemory | None) -> AgentExecutor:
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是一个SRE预测助手。你必须只输出JSON对象，不要输出额外文本。每次调用任何工具前，先调用trace_note记录本轮要做什么与原因（不超过80字）。",
            ),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )
    agent = create_tool_calling_agent(llm, tools, prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        memory=memory,
        verbose=False,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )
