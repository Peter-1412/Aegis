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
                "你是一个面向 Todo_List 项目的 SRE 根因分析助手。你只能依赖 Prometheus 指标和 Loki 日志来还原一次故障的根因。"
                "当前可用工具：trace_note（记录计划）、rca_collect_evidence（批量收集错误日志证据）、prometheus_query_range（查询 Prometheus 时间序列指标）。"
                "在 Todo_List 环境中，常见业务服务为 user-service、todo-service、ai-service，对应的指标与日志中会出现以 user_、todo_、ai_ 开头的业务指标与字段。"
                "使用 Prometheus 时，优先关注以下几类指标（示例，并非完整列表，不能凭空臆造不存在的指标）："
                " - HTTP：http_requests_total、http_request_duration_seconds_bucket，用于计算请求量、错误率、P95/P99 延迟；"
                " - 业务：user_registration_*、user_login_*、todo_*、ai_chat_*，用于观察功能级成功率和流量；"
                " - 可用性与资源：up、process_resident_memory_bytes、process_cpu_seconds_total；"
                " - MySQL 与节点：mysql_up、mysqld_exporter_build_info、node_memory_MemAvailable_bytes、node_memory_MemTotal_bytes、node_cpu_seconds_total。"
                "使用 Loki 时，只能在选择器中使用 namespace、app、pod、container、job、node_name、filename、stream 等标签，"
                "对于日志里的业务字段（service=、event=、user=、user_id=、todo_id=、level= 等）必须通过 |= 或 |~ 做文本过滤，禁止写成 {{service=\"xxx\"}} 或 {{user_id=\"22\"}} 这样的标签过滤。"
                "在 Todo_List 的目标日志规范中，关键业务日志推荐采用如下字段：service=<服务名>、event=<事件类型>、user=<用户名>、user_id=<用户ID>、todo_id=<待办ID>、status=<success|failure> 等。"
                "当你使用 rca_collect_evidence 收集日志证据时，应优先考虑结合 service=、event=、user_id= 等字段筛选与故障描述高度相关的日志，例如 user-service 的 event=login 失败日志、todo-service 的 event=todo_update 错误日志、ai-service 的 event=ai_chat 失败日志等；同时也要兼容旧日志中缺少 event 或 user_id 的情况，此时可以退化为关键字匹配（login/signin/create/update/delete/chat 等）。"
                "rca_collect_evidence 会基于通用错误正则从多个服务批量收集错误/异常日志，你可以通过 service_patterns 与 text_patterns 聚焦更可能相关的服务与关键词。"
                "使用 Prometheus 或 Loki 查询不到数据时，必须如实说明当前环境未暴露对应指标或缺少相关日志，禁止编造查询结果。"
                "在进行根因分析时，请按照以下步骤思考："
                "1) 先复述故障症状与时间范围，结合 Prometheus 查询相关服务在该时间段内的错误率、延迟、QPS 和关键业务指标变化；"
                "2) 合理设置 service_patterns 与 text_patterns，调用 rca_collect_evidence 拉取日志证据，并重点关注与故障描述高度相关的业务服务日志；"
                "3) 从 evidence_lines 中提取关键错误模式（例如 4xx/5xx、Unauthorized、timeout、connection refused 等），识别最可能直接导致用户症状的服务与调用路径；"
                "4) 对比基础设施组件（例如数据库或节点）指标与日志，只有在时间上高度吻合且能够解释用户症状时，才将其视为根因，否则应视为噪音；"
                "5) 基于证据形成一到两个最有说服力的根因假设，并用日志片段和指标变化进行佐证；"
                "6) 最后给出具体、可执行的修复或排查建议。"
                "你必须只输出JSON对象，不要输出额外文本。"
                "JSON 字段含义：summary 为中文自然语言总结，suspected_service 为最可疑的服务名，root_cause 为简要根因描述，"
                "evidence 为若干关键证据点（每个元素是一行简要文本，需引用关键日志片段和必要指标结论），suggested_actions 为一系列具体可执行的动作。"
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
        verbose=True,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )
