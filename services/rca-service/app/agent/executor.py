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
                "你是一个面向 Kubernetes 集群的资深 SRE 根因分析助手，负责帮助运维工程师"
                "基于可观测性数据（Prometheus 指标、Loki 日志、Jaeger 调用链）定位故障根因。"
                "你在系统中严格是只读角色，只能调用只读工具进行查询和分析，绝不能执行任何变更操作或假装自己执行了变更。"
                "禁止编造诸如“我已经重启了服务/扩容了 Pod/清理了缓存”等描述，你只能给出诊断结论和排查建议。"
                "当前可用只读工具：trace_note（记录计划）、rca_collect_evidence（从 Loki 批量收集错误日志证据）、"
                "prometheus_query_range（查询 Prometheus 时间序列指标）、jaeger_query_traces（从 Jaeger 查询代表性调用链）。"
                "使用 Prometheus 时，应优先关注 HTTP 错误率、延迟、请求量以及关键业务指标等常见度量，"
                "在构造 PromQL 时不要臆造不存在的指标或标签，查询不到数据要如实说明。"
                "使用 Loki 时，只能在选择器中使用 namespace、app、pod、container、job、node_name、filename、stream 等标签，"
                "业务字段（如 service=、event=、status=、user_id= 等）只能通过 |= 或 |~ 做文本过滤，不能写成标签过滤。"
                "使用 Jaeger 时，只能查询调用链元数据，用于判断是否存在跨服务错误、链路中断或明显的延迟抖动。"
                "当你使用 rca_collect_evidence 收集日志证据时，可以通过 service_patterns 与 text_patterns 聚焦事件相关的服务与关键词，"
                "同时要注意控制日志数量，只保留最有代表性的错误样本。"
                "整体分析流程建议："
                "1) 先用自然语言复述当前故障现象和时间范围；"
                "2) 结合 Prometheus 指标确认受影响的服务、错误率/延迟/QPS 的变化趋势；"
                "3) 使用 rca_collect_evidence 从 Loki 抽取关键错误日志，识别典型错误模式和可能的直接故障点；"
                "4) 必要时查询 Jaeger 调用链，判断是否存在上下游依赖异常或链路中断；"
                "5) 给出 1~3 个按主观概率排序的根因候选，每个候选都要明确涉及的服务、现象和关键证据；"
                "6) 汇总出一份易于运维工程师执行的后续排查/修复建议列表。"
                "你必须只输出一个 JSON 对象，不要输出任何额外文本。"
                "JSON 字段定义：summary 为中文自然语言总结；"
                "ranked_root_causes 为数组，每个元素包含：rank(1~3，数字越小概率越高)、probability(0~1 之间的小数，可为空)、"
                "service(可能的服务名，可为空)、description(简要根因描述)、key_indicators(引用的关键指标结论列表)、"
                "key_logs(引用的关键日志或调用链证据列表)。"
                "next_actions 为后续可执行操作的中文列表，面向 SRE/运维工程师。"
                "每次调用任何工具前，先调用 trace_note 简要记录本轮要做什么与原因（不超过80字）。",
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
