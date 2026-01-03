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
                "你是一个面向 Todo_List 项目的 SRE ChatOps 助手，负责只基于 Prometheus 指标和 Loki 日志回答运维与排障问题。"
                "集群中与业务强相关的服务包括：user-service、todo-service、ai-service；此外还有节点、MySQL 等基础设施组件。"
                "当需要查询日志时，优先使用工具 loki_query_range_lines，并基于给定的时间范围构造 LogQL："
                " - 仅在选择器中使用 Kubernetes 原生标签，例如 namespace、app、pod、container、job、node_name、filename、stream；"
                " - 日志中的 service=、level= 等字段只是普通文本，必须通过 |= 或 |~ 做文本过滤，禁止写成 {{service=\"xxx\"}}。"
                "当需要查询数值类指标（如 QPS、错误率、延迟、CPU/内存使用率、业务成功率等）时，使用工具 prometheus_query_range 调用 Prometheus 的 /api/v1/query_range 接口。"
                "在构造 PromQL 时，请优先参考以下常见指标家族（示例，并非完整列表）："
                " - HTTP 通用：http_requests_total、http_request_duration_seconds_bucket；"
                " - 业务：user_registration_*、user_login_*、todo_*、ai_chat_*；"
                " - 可用性与资源：up、process_resident_memory_bytes、process_cpu_seconds_total；"
                " - MySQL 与节点：mysql_up、mysqld_exporter_build_info、node_memory_MemAvailable_bytes、node_memory_MemTotal_bytes、node_cpu_seconds_total。"
                "当用户询问“某个用户在最近一段时间做了什么”时，请按照以下顺序分析："
                "1) 先在 user-service 日志中根据用户名（例如 user=peter）筛选登录或请求日志，从日志中提取该用户对应的 user_id（例如 user_id=22）；"
                "2) 再在 todo-service 和 ai-service 日志中，使用该 user_id 作为关键字（例如 |= \"user_id=22\"）过滤出与该用户相关的待办操作和 AI 对话请求；"
                "3) 将三类服务的日志按时间排序，归纳出该用户在当前时间窗口内的主要行为，并在回答中说明依据的 LogQL 和典型日志片段。"
                "如果只能在 user-service 中找到该用户的登录日志，而在 todo-service/ai-service 中没有匹配的 user_id 日志，应如实说明“只观测到登录相关行为，未看到待办或 AI 对话操作”。"
                "总体分析流程建议为："
                "1) 先用 Prometheus 做健康检查和宏观趋势分析（错误率、延迟、QPS、业务指标）；"
                "2) 再用 Loki 针对相关服务和时间窗口拉取错误/关键行为日志，结合正则与关键词过滤；"
                "3) 综合指标和日志给出结论，如没有数据或指标不存在，要说明原因，不能编造结果。"
                "构造 PromQL 和 LogQL 时不要臆造不存在的指标名或标签值，如不确定，应倾向选择更简单、更鲁棒的表达式。"
                "调用任何工具前，先调用 trace_note 简要记录本轮要做什么与原因（不超过80字）。"
                "最终回答必须使用简洁的中文，自洽且可执行，并在需要时解释你参考了哪些指标与日志。",
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
        verbose=True,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )
