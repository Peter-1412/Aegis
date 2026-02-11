# 系统架构文档 / System Architecture

## 1. 总体架构 / Overall Architecture

Aegis Ops Agent 运行在 Kubernetes 集群中，通过只读方式消费可观测性数据，并通过飞书机器人将分析结果反馈给运维工程师。

核心组件：

- Kubernetes 集群（3 master + 3 worker 节点）
- 观测组件（部署在 `monitoring` 命名空间）：
  - Prometheus（NodePort）
  - Loki + Promtail（ClusterIP）
  - Jaeger（NodePort）
- Aegis `ops-service`（部署在 `aegis` 命名空间）
- Alertmanager（可选，用于告警推送）
- 飞书开放平台 + 飞书机器人

数据流向可概括为两条主线：

1. 告警驱动：Alertmanager → ops-service → 飞书群消息
2. 人工提问驱动：飞书群消息 →（lark-oapi 长连接网关）→ ops-service → Prometheus/Loki/Jaeger → 飞书回复

## 2. 组件说明 / Component Description

### 2.1 ops-service

- 技术栈：FastAPI + LangChain
- 镜像构建：
  - `services/ops-service/Dockerfile`
- 核心模块：
  - `app/interface/api.py`：HTTP 接口、流式输出、飞书/Alertmanager 集成
  - `app/interface/feishu_ws_client.py`：飞书长连接事件网关
  - `app/agent/executor.py`：Agent Prompt + 工具装配（只读工具）
  - `app/tools/`：
    - `prometheus_query_range`：Prometheus 范围查询
    - `loki_collect_evidence`：从 Loki 批量抽取错误日志证据
    - `jaeger_query_traces`：从 Jaeger 查询代表性调用链
  - `app/memory/store.py`：会话短时记忆
  - `app/models/`：Ops 请求、根因候选、响应结构
  - `config/config.py`：配置项（通过环境变量/ConfigMap/Secret 注入）

### 2.2 只读访问保证 / Read-Only Access Guarantee

从架构上保证 Agent 只能"读"不能"写"：

- 工具层：
  - 所有工具均为 HTTP GET/POST 查询 Prometheus / Loki / Jaeger 的公开查询接口，仅返回 JSON 结果。
  - 工具实现中不包含任何对 Kubernetes API、业务数据库、缓存系统的写入调用。
- Prompt 约束：
  - 系统 Prompt 明确说明 Agent 的角色是"只读 SRE 助手"，禁止描述或假装执行任何变更操作。
  - 当模型试图输出"已经重启服务/扩容"等内容时，会被提示为不符合角色设定。
- 部署层：
  - ops-service Pod 不挂载集群敏感凭据（如 kubeconfig、数据库密码等），仅暴露查询型 HTTP 入口。

## 3. 时序流程 / Sequence Flow

### 3.1 Alertmanager 告警 → 飞书通知 / Alertmanager Alert → Feishu Notification

1. Prometheus 触发告警规则。
2. Alertmanager 将告警以 Webhook 形式 POST 到 `/alertmanager/webhook`。
3. ops-service 解析告警列表，按严重级别、alertname、重要标签生成汇总文本。
4. ops-service 通过飞书 OpenAPI `im/v1/messages` 将文本消息发送到预配置的 `chat_id`，并添加 `@所有人` 提示。

该流程仅进行告警转发，不自动执行 RCA，避免在告警风暴时造成额外负载。

### 3.2 飞书群聊 @机器人 → 运维分析 / Feishu Group Chat @Bot → Ops Analysis

1. 运维在告警群内 @ 机器人，并用自然语言描述问题。
2. 基于 `lark-oapi` 的长连接事件网关从飞书接收 `im.message.receive_v1` 事件。
3. 事件网关将消息内容转发给 ops-service（调用 `/feishu/receive`）。
4. ops-service 以"最近 15 分钟"为时间窗口构造 `OpsRequest` 并调用内部 RCA。
5. LangChain Agent 基于 Prompt 和工具执行以下步骤：
   - 规划分析步骤。
   - 调用 `prometheus_query_range` 检查关键服务的错误率、延迟、QPS 等指标。
   - 调用 `loki_collect_evidence` 从 Loki 拉取错误日志样本。
   - 必要时调用 `jaeger_query_traces` 检查调用链中是否存在跨服务错误或明显延迟。
   - 整理出 1~3 个根因候选，并生成 `summary` 与 `next_actions`。
6. ops-service 将结果整理成飞书文本消息发送回相同 `chat_id`。

## 4. 配置与环境变量 / Configuration and Environment Variables

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
  - `OLLAMA_BASE_URL`（用于本地模型）
  - `OLLAMA_MODEL`（例如：`qwen2.5:32b`、`glm-4.7-flash:latest`、`deepseek-r1:32b`）
  - `DOUBAO_BASE_URL`（用于云端模型）
  - `DOUBAO_API_KEY`
  - `DOUBAO_MODEL`（例如：`ep-20260207075658-4d5bg`）
  - `DEFAULT_MODEL`（默认使用的模型：`qwen`、`glm`、`deepseek` 或 `doubao`）
- 飞书：
  - `FEISHU_APP_ID`
  - `FEISHU_APP_SECRET`
  - `FEISHU_VERIFICATION_TOKEN`
  - `FEISHU_DEFAULT_CHAT_ID`

所有配置均为只读访问观测组件与飞书的必要信息，不包含业务写入权限。

## 5. 部署拓扑 / Deployment Topology

在你的集群中，典型部署示意：

- 命名空间 `monitoring`：
  - `prometheus` Service：`ClusterIP 10.106.83.175:9090` + `NodePort 30090`
  - `loki` Service：`ClusterIP 10.103.11.30:3100`
  - `jaeger` Service：`NodePort 30686`（UI）、`4317/4318`（OTLP）
- 命名空间 `aegis`：
  - `ops-service` Deployment + Service（NodePort 对外暴露，仅供内部系统或网关调用）
  - ConfigMap `aegis-config`
  - Secret `aegis-secrets`

通过 Ingress / API Gateway 按需将 `ops-service` 的以下路径公开到公司内网：

- `/alertmanager/webhook`（供 Alertmanager 调用，也可仅在集群内使用 ClusterIP）
- `/api/ops/analyze` 与 `/api/ops/analyze/stream`（如需给其他系统或长连接网关调用）

---

# System Architecture

## 1. Overall Architecture

Aegis Ops Agent runs in a Kubernetes cluster, consuming observability data in a read-only manner and providing analysis results to SRE engineers via Feishu bot.

Core Components:

- Kubernetes Cluster (3 master + 3 worker nodes)
- Observability Stack (deployed in `monitoring` namespace):
  - Prometheus (NodePort)
  - Loki + Promtail (ClusterIP)
  - Jaeger (NodePort)
- Aegis `ops-service` (deployed in `aegis` namespace)
- Alertmanager (optional, for alert push notifications)
- Feishu Open Platform + Feishu Bot

Data flow can be summarized into two main lines:

1. Alert-driven: Alertmanager → ops-service → Feishu Group Message
2. Manual query-driven: Feishu Group Message → (lark-oapi long connection gateway) → ops-service → Prometheus/Loki/Jaeger → Feishu Reply

## 2. Component Description

### 2.1 ops-service

- Tech Stack: FastAPI + LangChain
- Build Artifacts:
  - `services/ops-service/Dockerfile`
- Core Modules:
  - `app/interface/api.py`: HTTP endpoints, streaming output, Feishu/Alertmanager integration
  - `app/interface/feishu_ws_client.py`: Feishu long connection event gateway
  - `app/agent/executor.py`: Agent Prompt + tool assembly (read-only tools)
  - `app/tools/`:
    - `prometheus_query_range`: Prometheus range query
    - `loki_collect_evidence`: Batch extract error log evidence from Loki
    - `jaeger_query_traces`: Query representative traces from Jaeger
  - `app/memory/store.py`: Session short-term memory
  - `app/models/`: Ops request, root cause candidate, response structures
  - `config/config.py`: Configuration items (injected via environment variables/ConfigMap/Secret)

### 2.2 Read-Only Access Guarantee

From architecture perspective, ensuring Agent can only "read" but not "write":

- Tool Layer:
  - All tools are HTTP GET/POST query interfaces to Prometheus / Loki / Jaeger public query endpoints, returning only JSON results.
  - Tool implementations do not contain any write calls to Kubernetes API, business databases, or cache systems.
- Prompt Constraints:
  - System Prompt explicitly states Agent's role is "read-only SRE assistant", prohibiting describing or pretending to execute any change operations.
  - When model attempts to output "already restarted service / scaled up" etc., it will be prompted as not conforming to role setting.
- Deployment Layer:
  - ops-service Pod does not mount cluster sensitive credentials (such as kubeconfig, database passwords, etc.), only exposing query-type HTTP entry points.

## 3. Sequence Flow

### 3.1 Alertmanager Alert → Feishu Notification

1. Prometheus triggers alert rules.
2. Alertmanager sends alerts via Webhook POST to `/alertmanager/webhook`.
3. ops-service parses alert list, generates summary text by severity level, alertname, and important labels.
4. ops-service sends text message to pre-configured `chat_id` via Feishu OpenAPI `im/v1/messages`, adding `@all` mention.

This flow only performs alert forwarding, does not automatically execute RCA, to avoid additional load during alert storms.

### 3.2 Feishu Group Chat @Bot → Ops Analysis

1. SRE @mentions bot in alert group and describes to issue in natural language.
2. Based on `lark-oapi` long connection event gateway, receives `im.message.receive_v1` event from Feishu.
3. Event gateway forwards message content to ops-service (calling `/feishu/receive`).
4. ops-service constructs `OpsRequest` using "last 15 minutes" as time window and calls internal ops analysis.
5. LangChain Agent executes to following steps based on Prompt and tools:
   - Plan analysis steps.
   - Call `prometheus_query_range` to check key service error rates, latency, QPS, and other metrics.
   - Call `loki_collect_evidence` to extract error log samples from Loki.
   - Optionally call `jaeger_query_traces` to check for cross-service errors or obvious latency in call chains.
   - Organize 1~3 root cause candidates and generate `summary` and `next_actions`.
6. ops-service organizes results into Feishu text message and sends back to same `chat_id`.

## 4. Configuration and Environment Variables

Injected via `k8s/configmap.yaml` and `k8s/secret.yaml`:

- Loki:
  - `LOKI_BASE_URL`, example: `http://loki.monitoring.svc.cluster.local:3100`
  - `LOKI_TENANT_ID` (optional)
  - `LOKI_SERVICE_LABEL_KEY` (e.g., `app`)
  - `LOKI_SELECTOR_TEMPLATE` (e.g., `{{{label_key}="{service}"}}`)
- Prometheus:
  - `PROMETHEUS_BASE_URL`, example: `http://prometheus.monitoring.svc.cluster.local:9090`
- Jaeger:
  - `JAEGER_BASE_URL`, example: `http://jaeger.monitoring.svc.cluster.local:16686`
- LLM:
  - `OLLAMA_BASE_URL` (for local models)
  - `OLLAMA_MODEL` (e.g., `qwen2.5:32b`, `glm-4.7-flash:latest`, `deepseek-r1:32b`)
  - `DOUBAO_BASE_URL` (for cloud models)
  - `DOUBAO_API_KEY`
  - `DOUBAO_MODEL` (e.g., `ep-20260207075658-4d5bg`)
  - `DEFAULT_MODEL` (default model to use: `qwen`, `glm`, `deepseek`, or `doubao`)
- Feishu:
  - `FEISHU_APP_ID`
  - `FEISHU_APP_SECRET`
  - `FEISHU_VERIFICATION_TOKEN`
  - `FEISHU_DEFAULT_CHAT_ID`

All configurations are read-only access information for observability components and Feishu, without business write permissions.

## 5. Deployment Topology

Typical deployment in your cluster:

- Namespace `monitoring`:
  - `prometheus` Service: `ClusterIP 10.106.83.175:9090` + `NodePort 30090`
  - `loki` Service: `ClusterIP 10.103.11.30:3100`
  - `jaeger` Service: `NodePort 30686` (UI), `4317/4318` (OTLP)
- Namespace `aegis`:
  - `ops-service` Deployment + Service (NodePort exposed externally, only for internal systems or gateway calls)
  - ConfigMap `aegis-config`
  - Secret `aegis-secrets`

Expose the following paths of `ops-service` to company intranet via Ingress / API Gateway as needed:

- `/alertmanager/webhook` (for Alertmanager calls, can also use ClusterIP within cluster only)
- `/api/ops/analyze` and `/api/ops/analyze/stream` (if needed for other internal systems or long connection gateway calls)
