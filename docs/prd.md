# PRD：Aegis Ops Agent（飞书版）/ PRD: Aegis Ops Agent (Feishu Version)

## 1. 背景与目标 / Background and Objectives

### 1.1 背景 / 1.1 Background

当前 Kubernetes 集群已部署 Prometheus、Loki、Jaeger、Grafana、Promtail 等观测组件，但：

- 告警信息分散在 Alertmanager 与各类面板中，关联成本高；
- 故障发生时，SRE 需要在多种工具间来回切换，执行 PromQL / LogQL / Trace 查询；
- 一线运维同学对底层指标与日志格式不够熟悉，排障效率受限。

希望引入一个面向 SRE 的智能运维 Agent，将多源观测数据"汇聚到飞书群里"，让运维可以在聊天窗口完成 80% 的根因定位工作。

### 1.2 目标 / 1.2 Objectives

- 提供一个 **只读** 的运维 Agent：
  - 只能调用 Prometheus / Loki / Jaeger 的查询接口；
  - 不能执行任何变更或运维指令。
- 与飞书机器人深度集成：
  - 支持 Alertmanager 告警自动转发到飞书群；
  - 支持在群聊中自然语言提问并触发运维分析。
- 输出结构化运维结果：
  - 排序后的根因候选列表（包含主观概率）；
  - 对应的关键指标 / 日志 / 调用链证据；
  - 面向运维工程师的后续排查与修复建议。

## 2. 角色与使用场景 / Roles and Use Cases

### 2.1 角色 / 2.1 Roles

- SRE / 运维工程师：一线故障排查与处置人员。
- 平台工程师：负责部署与维护 Aegis Ops Agent。
- LLM 提供方：Ark / 其他兼容 OpenAI 协议的模型。

### 2.2 使用场景 / 2.2 Use Cases

#### 场景 A：告警驱动的被动运维 / Scenario A: Alert-Driven Passive Ops

1. 集群中某服务出现异常（错误率升高、延迟抖动、节点异常等）。
2. Prometheus 触发告警规则，Alertmanager 发送 Webhook 到 Aegis。
3. Aegis 在飞书告警群内 @所有人，汇总并展示关键信息。
4. 值班 SRE 在群内回复"@机器人帮我看下这波 502 的根因"，触发运维流程。
5. Agent 调用指标/日志/调用链工具进行分析，回复一条结构化运维结果消息，列出 1~3 个最可能根因及后续建议。

#### 场景 B：主动健康检查 / 回溯分析 / Scenario B: Proactive Health Check / Retrospective Analysis

1. SRE 在飞书群里输入：
   - "@机器人帮我看下昨天晚上 23 点订单超时的根因"
2. Agent 使用指定时间窗口进行历史回溯。
3. 返回与场景 A 类似的结构化运维结果，用于事后复盘。

## 3. 功能需求 / Functional Requirements

### 3.1 飞书集成 / 3.1 Feishu Integration

1. 支持企业自建应用模式，使用 `app_id` 和 `app_secret` 获取 `tenant_access_token`。
2. 支持事件订阅（长连接模式）：
   - `im.message.receive_v1`：接收群聊中@机器人的消息。
3. 支持通过 OpenAPI `im/v1/messages` 往指定 `chat_id` 发送文本消息。
4. 支持配置：
   - `FEISHU_DEFAULT_CHAT_ID`：默认告警/运维结果推送群。

### 3.2 Alertmanager 集成 / 3.2 Alertmanager Integration

1. 提供 HTTP 接口 `/alertmanager/webhook`，兼容标准 Alertmanager Webhook 格式。
2. 支持多条告警合并为一条飞书消息：
   - 显示 `alertname`、`severity`、`instance`/`pod`/`service` 等关键标签；
   - 显示 `summary` 或 `description` 注释；
   - 消息开头默认携带 `@所有人`。
3. Webhook 处理逻辑尽量快速返回，避免阻塞 Alertmanager。

### 3.3 运维 Agent 能力 / 3.3 Ops Agent Capabilities

1. 入口：
   - 飞书消息事件：自动将文本作为 `description`，并使用最近 15 分钟时间窗口。
   - HTTP API：`/api/ops/analyze` 和 `/api/ops/analyze/stream`，支持外部系统直接调用。
2. 工具集（只读）：
   - `prometheus_query_range`：查询指定 PromQL 在时间范围内的序列。
   - `loki_collect_evidence`：从 Loki 抓取含错误关键词/状态码的日志行，并按服务优先级聚合。
   - `jaeger_query_traces`：从 Jaeger 查询指定服务在时间范围内的代表性 Trace 简要信息。
3. 输出结构：
   - `summary`：中文自然语言总结。
   - `ranked_root_causes`：
     - 包含 `rank`、`service`、`probability`、`description`、`key_indicators`、`key_logs`。
     - 至多 3 条。
   - `next_actions`：后续建议。
4. Agent 行为约束：
   - 系统 Prompt 中明确禁止描述或假装执行任何变更动作。
   - 当没有数据被查询时，必须如实说明，不得编造指标或日志内容。

### 3.4 安全与权限 / 3.4 Security and Permissions

1. 所有对 Prometheus / Loki / Jaeger 的访问仅通过 HTTP 读接口完成。
2. 不在容器内挂载 kubeconfig / 云厂商 AK/SK 等高权限凭据。
3. 飞书 `app_secret`、`verification_token` 与 LLM `API_KEY` 均存放在 K8s Secret 中。
4. 提供只读的 HTTP API，不暴露任何写操作。

## 4. 非功能性需求 / Non-Functional Requirements

### 4.1 性能 / 4.1 Performance

- 单次运维分析默认控制在 30~60 秒内完成。
- 工具调用并发数受 LangChain Agent 策略控制，必要时可在后续迭代中增加限流。

### 4.2 可用性 / 4.2 Availability

- ops-service 在生产环境建议至少 2 副本，支持滚动升级。
- 内部错误不得影响 Alertmanager 和飞书的正常运行（即便失败也应返回 200/简单错误信息）。

### 4.3 可观测性 / 4.3 Observability

- ops-service 自身应输出结构化日志，方便在 Loki 中检索。
- 关键路径添加简单指标（如请求耗时、LLM 调用失败次数）可在后续迭代中补充。

## 5. 交付物 / Deliverables

1. `ops-service` 源码（Python + FastAPI + LangChain）。
2. 可直接构建的 Dockerfile。
3. Kubernetes 部署清单：
   - Namespace / ConfigMap / Secret / Deployment / Service。
4. 文档：
   - README（中英文）
   - `docs/api.md`：接口文档
   - `docs/architecture.md`：架构文档
   - `docs/user-manual.md`：使用手册（面向运维）

## 6. 未来迭代方向（非本期）/ Future Iteration Directions (Non-Current Phase)

- 支持多租户、多集群场景（通过标签/命名空间隔离）。
- 与更多观测后端集成（Tempo / OpenSearch / ClickHouse 等）。
- 引入规则引擎与知识库，将经验型 SRE 规则结构化沉淀。

---

# PRD: Aegis Ops Agent (Feishu Version)

## 1. Background and Objectives

### 1.1 Background

The Kubernetes cluster has already deployed observability components such as Prometheus, Loki, Jaeger, Grafana, and Promtail, but:

- Alert information is scattered across Alertmanager and various dashboards, with high correlation cost;
- When incidents occur, SREs need to switch between multiple tools to execute PromQL / LogQL / Trace queries;
- Frontline operations engineers are not familiar enough with underlying metrics and log formats, limiting troubleshooting efficiency.

The goal is to introduce an SRE-oriented intelligent Ops Agent that aggregates multi-source observability ability data "into Feishu groups", enabling operations to complete 80% of root cause localization work within chat window.

### 1.2 Objectives

- Provide a **read-only** Ops Agent:
  - Can only call query interfaces of Prometheus / Loki / Jaeger;
  - Cannot execute any changes or operations commands.
- Deep integration with Feishu Bot:
  - Support Alertmanager alert automatic forwarding to Feishu groups;
  - Support natural language questioning in group chats and trigger Ops analysis.
- Output structured Ops results:
  - Ranked root cause candidate list (including subjective probabilities);
  - Corresponding key metrics / logs / trace evidence;
  - Follow-up troubleshooting and remediation suggestions oriented towards operations engineers.

## 2. Roles and Use Cases

### 2.1 Roles

- SRE / Operations Engineer: Frontline incident troubleshooting and response personnel.
- Platform Engineer: Responsible for deployment and maintenance of Aegis Ops Agent.
- LLM Provider: Ark / Other OpenAI protocol compatible models.

### 2.2 Use Cases

#### Scenario A: Alert-Driven Passive Ops

1. A service anomaly occurs in cluster (error rate increase, latency jitter, node anomaly, etc.).
2. Prometheus triggers alert rules, Alertmanager sends Webhook to Aegis.
3. Aegis @mentions all in Feishu alert group, summarizes and displays key information.
4. On-duty SRE replies in the group "@bot help me check of root cause of this 502", triggering Ops workflow.
5. Agent calls metrics/logs/trace tools for analysis, replies with a structured Ops result message listing 1~3 most likely root causes and follow-up suggestions.

#### Scenario B: Proactive Health Check / Retrospective Analysis

1. SRE inputs in Feishu group:
   - "@bot help me check of root cause of order timeout last night at 23:00"
2. Agent performs historical retrospective using specified time window.
3. Returns structured Ops result similar to Scenario A, used for post-incident review.

## 3. Functional Requirements

### 3.1 Feishu Integration

1. Support enterprise self-built application mode, using `app_id` and `app_secret` to obtain `tenant_access_token`.
2. Support event subscription (long connection mode):
   - `im.message.receive_v1`: Receive messages where bot is @mentioned in group chats.
3. Support sending text messages to specified `chat_id` via OpenAPI `im/v1/messages`.
4. Support configuration:
   - `FEISHU_DEFAULT_CHAT_ID`: Default alert/Ops result push group.

### 3.2 Alertmanager Integration

1. Provide HTTP endpoint `/alertmanager/webhook`, compatible with standard Alertmanager Webhook format.
2. Support merging multiple alerts into a single Feishu message:
   - Display `alertname`, `severity`, `instance`/`pod`/`service` and other key labels;
   - Display `summary` or `description` annotations;
   - Message header defaults to include `@all`.
3. Webhook processing logic should return quickly to avoid blocking Alertmanager.

### 3.3 Ops Agent Capabilities

1. Entry Points:
   - Feishu message events: Automatically use text as `description`, using last 15 minutes as time window.
   - HTTP API: `/api/ops/analyze` and `/api/ops/analyze/stream`, supporting direct calls from external systems.
2. Tool Set (Read-Only):
   - `prometheus_query_range`: Query specified PromQL time series within time range.
   - `loki_collect_evidence`: Extract log lines containing error keywords/status codes from Loki, aggregated by service priority.
   - `jaeger_query_traces`: Query representative trace summary information for specified service within time range from Jaeger.
3. Output Structure:
   - `summary`: Chinese natural language summary.
   - `ranked_root_causes`:
     - Contains `rank`, `service`, `probability`, `description`, `key_indicators`, `key_logs`.
     - Maximum 3 entries.
   - `next_actions`: Follow-up suggestions.
4. Agent Behavior Constraints:
   - System Prompt explicitly prohibits describing or pretending to execute any change actions.
   - When no data is queried, must truthfully state so, must not fabricate metrics or log content.

### 3.4 Security and Permissions

1. All access to Prometheus / Loki / Jaeger is completed via HTTP read-only interfaces.
2. Do not mount kubeconfig / cloud provider AK/SK and other high-privilege credentials in containers.
3. Feishu `app_secret`, `verification_token` and LLM `API_KEY` are all stored in K8s Secret.
4. Provide read-only HTTP APIs, do not expose any write operations.

## 4. Non-Functional Requirements

### 4.1 Performance

- Single Ops analysis should be controlled within 30~60 seconds by default.
- Tool call concurrency is controlled by LangChain Agent strategy, can add rate limiting in future iterations if necessary.

### 4.2 Availability

- ops-service should have at least 2 replicas in production environment, supporting rolling upgrades.
- Internal errors must not affect Alertmanager and Feishu normal operation (should return 200/simple error information even on failure).

### 4.3 Observability

- ops-service should output structured logs itself, facilitating retrieval in Loki.
- Key paths add simple metrics (such as request duration, LLM call failure count) can be supplemented in future iterations.

## 5. Deliverables

1. `ops-service` source code (Python + FastAPI + LangChain).
2. Directly buildable Dockerfile.
3. Kubernetes deployment manifests:
   - Namespace / ConfigMap / Secret / Deployment / Service.
4. Documentation:
   - README (Chinese and English)
   - `docs/api.md`: API documentation
   - `docs/architecture.md`: Architecture documentation
   - `docs/user-manual.md`: User manual (operations-oriented)

## 6. Future Iteration Directions (Non-Current Phase)

- Support multi-tenant, multi-cluster scenarios (isolated via labels/namespaces).
- Integration with more observability backends (Tempo / OpenSearch / ClickClickHouse, etc.).
- Introduce rule engine and knowledge base to structure and沉淀 experience-based SRE rules.
