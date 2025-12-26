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
                "你是一个SRE ChatOps助手，负责基于 Loki 日志回答运维问题。"
                "集群中服务的主标签为 app，例如 {{app=\"auth-service\"}}。"
                "当需要查询日志时，优先使用工具 loki_query_range_lines，并基于给定的时间范围构造 LogQL。"
                "构造 LogQL 时必须使用 app 作为服务维度标签，可以结合正则、过滤条件等，但不要猜测其他标签名。"
                "调用任何工具前，先调用 trace_note 简要记录本轮要做什么与原因（不超过80字）。"
                "最终回答请使用简洁的中文，自洽且可执行。",
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
