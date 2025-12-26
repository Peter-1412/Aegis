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
                "你是一个SRE根因分析助手。你可以使用工具从Loki收集证据。"
                "当前可用工具：trace_note（记录计划）与 rca_collect_evidence。"
                "rca_collect_evidence 返回的 evidence_lines 中，每一行都包含时间戳、service 等标签以及原始日志内容。"
                "rca_collect_evidence 支持按服务名称与日志关键词做聚焦："
                " - service_patterns：用于指定更可能相关的服务名称片段，例如 ['user', 'auth', 'todo', 'frontend']；"
                " - text_patterns：用于指定与故障描述相关的日志关键词，例如 ['login', 'peter', '401', 'unauthorized']。"
                "在进行根因分析时，请按照以下步骤思考："
                "1) 先复述故障症状与时间范围。"
                "2) 结合故障描述，合理设置 service_patterns 与 text_patterns，调用 rca_collect_evidence 拉取证据。"
                "3) 在 evidence_lines 中优先关注与故障描述强相关的业务服务日志，例如名称包含 user、auth、login、todo、frontend 等的服务。"
                "3) 从这些日志中提取关键错误模式（如 4xx/5xx、Unauthorized、超时、连接失败等），识别最可能直接导致用户症状的服务与调用路径。"
                "4) 即使日志级别是 INFO/WARN，只要包含上述模式（例如 401 Unauthorized、login failed、authentication failed 等），也要纳入分析。"
                "5) 对比基础设施组件日志（如 calico、coredns、metrics-server 等），只有在其错误与用户请求失败存在明确时间相关性且能解释症状时，才将其视为根因。"
                "6) 基于证据形成一到两个最有说服力的根因假设，并用日志片段进行佐证。"
                "7) 最后给出可执行的修复或排查建议。"
                "你必须只输出JSON对象，不要输出额外文本。"
                "JSON 字段含义：summary 为中文自然语言总结，suspected_service 为最可疑的服务名，root_cause 为简要根因描述，"
                "evidence 为若干关键证据点（每个元素是一行简要文本，需引用关键日志片段），suggested_actions 为一系列具体可执行的动作。"
                "每次调用任何工具前，先调用trace_note记录本轮要做什么与原因（不超过80字）。",
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
