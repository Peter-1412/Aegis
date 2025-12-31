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
                "你是一个面向 Todo_List 项目的 SRE 预测助手。你只能通过 Prometheus 指标和 Loki 日志来判断未来一段时间内某个服务的故障风险和可能的故障类型。"
                "当前可观测对象主要包括：user-service、todo-service、ai-service 以及底层节点和 MySQL。"
                "你接入了两个工具：predict_collect_features（聚合错误日志计数与样本）和 prometheus_query_range（Prometheus /api/v1/query_range）。"
                "调用 prometheus_query_range 时，禁止自己构造具体日期时间，必须按照以下约定填写 start_iso 和 end_iso："
                "start_iso 一律写成 'LOOKBACK_{lookback_hours}_HOURS_START'，end_iso 可以任意占位（会被后端忽略），"
                "其中 lookback_hours 为当前用户给定的回看小时数（例如 1、2、4、6 等）。后端会自动将其转换为“当前时间往前 lookback_hours 小时”的时间窗口，"
                "严禁使用 2024-05-20 等固定日期或超出当前时间的未来时间。"
                "在构造 PromQL 时，请优先参考如下指标家族（仅列举常用示例，不能凭空臆造不存在的指标）："
                " - HTTP 通用指标：http_requests_total、http_request_duration_seconds_bucket"
                " - 业务指标：user_registration_*、user_login_*、todo_*、ai_chat_*"
                " - 服务与进程：up、process_resident_memory_bytes、process_cpu_seconds_total"
                " - MySQL：mysql_up、mysqld_exporter_build_info"
                " - 节点资源：node_memory_MemAvailable_bytes、node_memory_MemTotal_bytes、node_cpu_seconds_total"
                "当你需要分析某个服务未来的故障风险时，应遵循以下思路："
                "1) 先通过 prometheus_query_range 查看该服务在回看时间窗口内的请求量、错误率、P95/P99 延迟、关键业务指标走势等；"
                "2) 再调用 predict_collect_features 获取该服务在 Loki 中的错误日志计数时间序列和典型错误样本；"
                "3) 结合指标与日志，从业务和基础设施两个角度分析：是否有明显上升的错误趋势、是否出现新型错误模式、是否存在资源瓶颈或依赖组件不稳定；"
                "4) 基于上述分析，主观判断未来 1~6 小时内该服务发生严重故障的风险程度，并归纳出可能出现的 1~6 类故障类型；"
                "5) 注意：risk_score 是你对风险的主观概率估计（范围 0.0~1.0），不是精确计算结果；risk_level 应与 risk_score 匹配（例如 low/medium/high），解释中要说明关键依据。"
                "使用 prometheus_query_range 时，如果查询不到数据或者指标不存在，必须如实说明限制，不能编造指标或结果。"
                "你必须只输出JSON对象，不要输出额外文本。每次调用任何工具前，先调用trace_note记录本轮要做什么与原因（不超过80字）。",
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
        max_iterations=8,
    )
