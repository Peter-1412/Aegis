# 系统架构文档

## 1. 总体架构

Aegis RCA Agent 运行在 Kubernetes 集群中，通过只读方式消费可观测性数据，并通过飞书机器人将分析结果反馈给运维工程师。

核心组件：

- Kubernetes 集群（3 master + 3 worker）
- 观测组件（部署在 `monitoring` 命名空间）：
  - Prometheus（NodePort）
  - Loki + Promtail（ClusterIP）
  - Jaeger（NodePort）
- Aegis `rca-service`（部署在 `aegis` 命名空间）
- Alertmanager（可选，用于告警推送）
- 飞书开放平台 + 飞书机器人

数据流向可概括为两条主线：

1. 告警驱动：Alertmanager → rca-service → Feishu 群消息
2. 人工提问驱动：Feishu 群消息 →（lark-oapi 长连接网关）→ rca-service → Prometheus/Loki/Jaeger → Feishu 回复

## 2. 组件说明

### 2.1 rca-service

- 技术栈：FastAPI + LangChain
- 镜像构建：
  - `services/rca-service/Dockerfile`
- 核心模块：
  - `app/main.py`：HTTP 接口、流式输出、Feishu/Alertmanager 回调处理
  - `app/agent/executor.py`：Agent Prompt + 工具装配（只读工具）
  - `app/tools/`：
    - `prometheus_query_range`：Prometheus 范围查询
    - `rca_collect_evidence`：从 Loki 批量抽取错误日志证据
    - `jaeger_query_traces`：从 Jaeger 查询代表性调用链
    - `trace_note`：记录 Agent 的计划与意图
  - `app/models.py`：RCA 请求、根因候选、响应结构
  - `app/settings.py`：配置项（通过环境变量/ConfigMap/Secret 注入）

### 2.2 只读访问保证

从架构上保证 Agent 只能“读”不能“写”：

- 工具层：
  - 所有工具均为 HTTP GET/POST 查询 Prometheus / Loki / Jaeger 的公开查询接口，仅返回 JSON 结果。
  - 工具实现中不包含任何对 Kubernetes API、业务数据库、缓存系统的写入调用。
- Prompt 约束：
  - 系统 Prompt 明确说明 Agent 的角色是“只读 SRE 助手”，禁止描述或假装执行任何变更操作。
  - 当模型试图输出“已经重启服务/扩容”等内容时，会被提示为不符合角色设定。
- 部署层：
  - rca-service Pod 不挂载集群敏感凭据（如 kubeconfig、数据库密码等），仅暴露查询型 HTTP 入口。

## 3. 时序流程

### 3.1 Alertmanager 告警 → 飞书通知

1. Prometheus 触发告警规则。
2. Alertmanager 将告警以 Webhook 形式 POST 到 `/alertmanager/webhook`。
3. rca-service 解析告警列表，按严重级别、alertname、重要标签生成汇总文本。
4. rca-service 通过 Feishu OpenAPI `im/v1/messages` 将文本消息发送到预配置的 `chat_id`，并添加 `@所有人` 提示。

该流程仅进行告警转发，不自动执行 RCA，避免在告警风暴时造成额外负载。

### 3.2 飞书群聊 @机器人 → RCA 分析

1. 运维在告警群内 @ 机器人，并用自然语言描述问题。
2. 基于 `lark-oapi` 的长连接事件网关从飞书接收 `im.message.receive_v1` 事件。
3. 事件网关将消息内容转发给 rca-service（调用 `/api/rca/analyze` 或内部封装接口）。
4. rca-service 以“最近 15 分钟”为时间窗口构造 `RCARequest` 并调用内部 `_run_rca`。
5. LangChain Agent 基于 Prompt 和工具执行以下步骤：
   - 调用 `trace_note` 记录当前分析计划。
   - 调用 `prometheus_query_range` 检查关键服务的错误率、延迟、QPS 等指标。
   - 调用 `rca_collect_evidence` 从 Loki 拉取错误日志样本。
   - 必要时调用 `jaeger_query_traces` 检查调用链中是否存在跨服务错误或明显延迟。
   - 整理出 1~3 个根因候选，并生成 `summary` 与 `next_actions`。
6. rca-service 将结果整理成飞书文本消息发送回相同 `chat_id`。

## 4. 配置与环境变量

通过 `k8s/configmap.yaml` 与 `k8s/secret.yaml` 注入：

- Loki：
  - `LOKI_BASE_URL`，示例：`http://loki.monitoring.svc.cluster.local:3100`
  - `LOKI_TENANT_ID`（可选）
  - `LOKI_SERVICE_LABEL_KEY`（例如 `app`）
  - `LOKI_SELECTOR_TEMPLATE`（例如 `{{{label_key}="{service}"}}`）
- Prometheus：
  - `PROMETHEUS_BASE_URL`，示例：`http://prometheus.monitoring.svc.cluster.local:9090`
- Jaeger：
  - `JAEGER_BASE_URL`，示例：`http://jaeger.monitoring.svc.cluster.local:16686`
- LLM：
  - `LLM_MODEL`
  - `ARK_BASE_URL`
  - `ARK_API_KEY`
- Feishu：
  - `FEISHU_APP_ID`
  - `FEISHU_APP_SECRET`
  - `FEISHU_VERIFICATION_TOKEN`
  - `FEISHU_DEFAULT_CHAT_ID`

所有配置均为只读访问观测组件与 Feishu 的必要信息，不包含业务写入权限。

## 5. 部署拓扑

在你的集群中，典型部署示意：

- 命名空间 `monitoring`：
  - `prometheus` Service：`ClusterIP 10.106.83.175:9090` + `NodePort 30090`
  - `loki` Service：`ClusterIP 10.103.11.30:3100`
  - `jaeger` Service：`NodePort 30686`（UI）、`4317/4318`（OTLP）
- 命名空间 `aegis`：
  - `rca-service` Deployment + Service（NodePort 对外暴露，仅供内部系统或网关调用）
  - ConfigMap `aegis-config`
  - Secret `aegis-secrets`

通过 Ingress / API Gateway 按需将 `rca-service` 的以下路径公开到公司内网：

- `/alertmanager/webhook`（供 Alertmanager 调用，也可仅在集群内使用 ClusterIP）
- `/api/rca/analyze` 与 `/api/rca/analyze/stream`（如需给其他系统或长连接网关调用）

