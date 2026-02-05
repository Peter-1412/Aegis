# PRD：Aegis RCA Agent（飞书版）

## 1. 背景与目标

### 1.1 背景

当前 Kubernetes 集群已部署 Prometheus、Loki、Jaeger、Grafana、Promtail 等观测组件，但：

- 告警信息分散在 Alertmanager 与各类面板中，关联成本高；
- 故障发生时，SRE 需要在多种工具间来回切换，执行 PromQL / LogQL / Trace 查询；
- 一线运维同学对底层指标与日志格式不够熟悉，排障效率受限。

希望引入一个面向 SRE 的智能 RCA Agent，将多源观测数据“汇聚到飞书群里”，让运维可以在聊天窗口完成 80% 的根因定位工作。

### 1.2 目标

- 提供一个 **只读** 的 RCA Agent：
  - 只能调用 Prometheus / Loki / Jaeger 的查询接口；
  - 不能执行任何变更或运维指令。
- 与飞书机器人深度集成：
  - 支持 Alertmanager 告警自动转发到飞书群；
  - 支持在群聊中自然语言提问并触发 RCA 分析。
- 输出结构化 RCA 结果：
  - 排序后的根因候选列表（包含主观概率）；
  - 对应的关键指标/日志/调用链证据；
  - 面向运维工程师的后续排查与修复建议。

## 2. 角色与使用场景

### 2.1 角色

- SRE / 运维工程师：一线故障排查与处置人员。
- 平台工程师：负责部署与维护 Aegis RCA Agent。
- LLM 提供方：Ark / 其他兼容 OpenAI 协议的模型。

### 2.2 使用场景

#### 场景 A：告警驱动的被动 RCA

1. 集群中某服务出现异常（错误率升高、延迟抖动、节点异常等）。
2. Prometheus 触发告警规则，Alertmanager 发送 Webhook 到 Aegis。
3. Aegis 在飞书告警群内 @所有人，汇总并展示关键信息。
4. 值班 SRE 在群内回复“@机器人 帮我看下这波 502 的根因”，触发 RCA 流程。
5. Agent 调用指标/日志/调用链工具分析，回复一条结构化 RCA 结果消息，列出 1~3 个最可能根因及后续建议。

#### 场景 B：主动健康检查 / 回溯分析

1. SRE 在飞书群里输入：
   - “@机器人 帮我看一下昨天晚上 23 点订单超时的根因”
2. Agent 使用指定时间窗口进行历史回溯。
3. 返回与场景 A 类似的结构化 RCA 结果，用于事后复盘。

## 3. 功能需求

### 3.1 飞书集成

1. 支持企业自建应用模式，使用 `app_id` 和 `app_secret` 获取 `tenant_access_token`。
2. 支持事件订阅：
   - `im.message.receive_v1`：接收群聊中@机器人的消息。
3. 支持通过 OpenAPI `im/v1/messages` 往指定 `chat_id` 发送文本消息。
4. 支持 URL 校验流程（`url_verification`）。
5. 支持配置：
   - `FEISHU_DEFAULT_CHAT_ID`：默认告警/RCA 结果推送群。

### 3.2 Alertmanager 集成

1. 提供 HTTP 接口 `/alertmanager/webhook`，兼容标准 Alertmanager Webhook 格式。
2. 支持多条告警合并为一条飞书消息：
   - 显示 `alertname`、`severity`、`instance`/`pod`/`service` 等关键标签；
   - 显示 `summary` 或 `description` 注释；
   - 消息开头默认携带 `@所有人`。
3. Webhook 处理逻辑不阻塞 Alertmanager（只要入队成功即返回 200）。

### 3.3 RCA Agent 能力

1. 入口：
   - 飞书消息事件：自动将文本作为 `description`，并使用最近 15 分钟时间窗口。
   - HTTP API：`/api/rca/analyze` 和 `/api/rca/analyze/stream`，支持外部系统直接调用。
2. 工具集（只读）：
   - `prometheus_query_range`：查询指定 PromQL 在时间范围内的序列。
   - `rca_collect_evidence`：从 Loki 抓取含错误关键词/状态码的日志行，并按服务优先级聚合。
   - `jaeger_query_traces`：从 Jaeger 查询指定服务在时间范围内的代表性 Trace 简要信息。
   - `trace_note`：记录计划与意图，用于可观测 Agent 行为。
3. 输出结构：
   - `summary`：中文自然语言总结。
   - `ranked_root_causes`：
     - 包含 `rank`、`service`、`probability`、`description`、`key_indicators`、`key_logs`。
     - 至多 3 条。
   - `next_actions`：后续建议。
4. Agent 行为约束：
   - 系统 Prompt 中明确禁止描述或假装执行任何变更动作。
   - 查询不到数据时必须如实说明，不得编造指标或日志内容。

### 3.4 安全与权限

1. 所有对 Prometheus / Loki / Jaeger 的访问仅通过 HTTP 读接口完成。
2. 不在容器内挂载 kubeconfig / 云厂商 AK/SK 等高权限凭据。
3. 飞书 `app_secret`、`verification_token` 与 LLM `API_KEY` 均存放在 K8s Secret 中。
4. 提供只读的 HTTP API，不暴露任何写操作。

## 4. 非功能性需求

### 4.1 性能

- 单次 RCA 分析默认控制在 30~60 秒内完成。
- 工具调用并发数受 LangChain Agent 策略控制，必要时可在后续迭代中增加限流。

### 4.2 可用性

- rca-service 在生产环境建议至少 2 副本，支持滚动升级。
- 内部错误不得影响 Alertmanager 和飞书的正常运行（即便失败也应返回 200/简单错误信息）。

### 4.3 可观测性

- rca-service 自身应输出结构化日志，方便在 Loki 中检索。
- 关键路径添加简单指标（如请求耗时、LLM 调用失败次数）可在后续迭代中补充。

## 5. 交付物

1. `rca-service` 源码（Python + FastAPI + LangChain）。
2. 可直接构建的 Dockerfile。
3. Kubernetes 部署清单：
   - Namespace / ConfigMap / Secret / Deployment / Service。
4. 文档：
   - README（中英文）
   - `docs/api.md`：接口文档
   - `docs/architecture.md`：架构文档
   - `docs/user-manual.md`：使用手册（面向运维）

## 6. 未来迭代方向（非本期）

- 支持多租户、多集群场景（通过标签/命名空间隔离）。
- 与更多观测后端集成（Tempo / OpenSearch / ClickHouse 等）。
- 引入规则引擎与知识库，将经验型 SRE 规则结构化沉淀。

