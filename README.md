<div align="center">

# Aegis Ops Agent

An intelligent operations assistant for Kubernetes clusters, integrated with Feishu Bot.

面向 Kubernetes 集群的智能运维助手，支持与飞书机器人集成。

[简体中文](#chinese-overview) | [English](#english-overview)

</div>

---

# Aegis Ops Agent

## 1. Project Overview

Aegis is an intelligent operations assistant designed to help SRE and operations engineers analyze Kubernetes cluster issues by consuming observability data in a read-only manner.

Aegis 部署在你的 Kubernetes 集群中，通过只读方式接入：

- Prometheus（指标）
- Loki + Promtail（日志）
- Jaeger（分布式调用链）
- Alertmanager（告警 Webhook，可选）
- 飞书机器人（作为 Chat 前端）

核心目标：

- 当 Alertmanager 产生告警时，Agent 自动在飞书告警群内 @ 运维同学，汇总关键告警信息。
- 当运维在群内 @ 机器人并描述故障现象时，Agent 自动调用 Prometheus / Loki / Jaeger 工具完成一次运维分析，并在群内给出按概率排序的根因候选列表及后续排查建议。
- Agent 始终以只读身份工作，**绝不执行任何变更操作**。

## 2. Key Features

- 多源观测数据融合：指标 + 日志 + 调用链
- LangChain Agent + 工具编排，自动选择合适的查询策略
- 根因候选结果按主观概率排序，给出关键指标与日志证据
- 与飞书机器人深度集成：
  - 接收 Alertmanager Webhook，将告警转发至群组并 @所有人
  - 接收群聊中的手工运维请求，自动发起分析并回复结构化结论
- Kubernetes 原生部署，支持 NodePort/Ingress 暴露 HTTP 接口
- 多模型支持：
  - 本地模型：Qwen、GLM-4.7-Flash、DeepSeek-R1
  - 云端模型：豆包（Doubao）
  - 支持用户在飞书中指定模型：`@AegisBot qwen/glm/deepseek/doubao 问题`

## 3. Directory Structure

```text
Aegis/
├── services/
│   └── ops-service/          Ops 微服务（FastAPI + LangChain Agent）
├── k8s/                      Kubernetes 部署清单
│   ├── namespace.yaml
│   ├── configmap.yaml        只读访问配置（Loki/Prometheus/Jaeger/Feishu）
│   ├── secret.yaml           LLM 与飞书密钥（需自行填写）
│   └── ops-service.yaml      Ops Service 部署与 Service
└── docs/                     文档（接口、架构、PRD 等）
```

ops-service 内部关键模块：

- `app/interface/api.py`：FastAPI 入口、HTTP 接口、飞书/Alertmanager 集成
- `app/interface/feishu_ws_client.py`：飞书长连接事件网关
- `app/agent/executor.py`：LangChain AgentExecutor 与系统 Prompt
- `app/tools/`：Prometheus/Loki/Jaeger 等只读工具
- `app/models/`：Ops 请求 / 响应及根因候选数据结构
- `config/config.py`：配置（通过环境变量/K8s ConfigMap/Secret 注入）

## 4. API Overview

详细说明见 [`docs/api.md`](docs/api.md)，这里给出主要接口一览：

| 服务        | 方法 | 路径                     | 说明                                      |
|-------------|------|--------------------------|-------------------------------------------|
| ops-service | GET  | `/healthz`               | 健康检查                                  |
| ops-service | POST | `/api/ops/analyze`       | 同步运维分析                             |
| ops-service | POST | `/api/ops/analyze/stream`| 流式运维分析（NDJSON）                   |
| ops-service | POST | `/alertmanager/webhook`  | Alertmanager Webhook 回调入口             |

## 5. Deployment Guide (Kubernetes)

1. 创建命名空间与基础配置：

   ```bash
   kubectl apply -f k8s/namespace.yaml
   kubectl apply -f k8s/configmap.yaml
   kubectl apply -f k8s/secret.yaml
   ```

   在应用前，你需要根据实际环境修改：

   - `k8s/configmap.yaml` 中的 `LOKI_BASE_URL`、`PROMETHEUS_BASE_URL`、`JAEGER_BASE_URL`
   - `k8s/configmap.yaml` 中的 `FEISHU_DEFAULT_CHAT_ID`
   - `k8s/secret.yaml` 中的 `DOUBAO_API_KEY`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_VERIFICATION_TOKEN`

2. 部署 Ops Service：

   ```bash
   kubectl apply -f k8s/ops-service.yaml
   ```

3. 根据需要暴露 HTTP 接口：

   - 通常仅需在集群内访问 `/alertmanager/webhook`（由 Alertmanager 调用）；
   - `/api/ops/analyze`、`/api/ops/analyze/stream` 可按需通过 Ingress 或 API Gateway 暴露给其他内部系统。

4. 在 Alertmanager 中配置 Webhook 通知地址为 `/alertmanager/webhook`。

## 6. Feishu Integration Guide (Overview)

详细步骤见 [`docs/prd.md`](docs/prd.md) 与 [`docs/user-manual.md`](docs/user-manual.md)，这里给出概要流程：

- 在飞书开放平台创建企业自建应用，获取 `app_id` 与 `app_secret`
- 在应用后台开启"长连接事件订阅"能力，并订阅：
  - 机器人收到消息 `im.message.receive_v1`
- 在 K8s Secret 中配置 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`
- ops-service 在启动时使用 `lark-oapi` 建立与飞书的长连接，自动接收群聊消息并触发运维分析
- 将应用添加到对应飞书群组，获取群组 `chat_id` 并填入 `FEISHU_DEFAULT_CHAT_ID`

## 7. Local Development and Debugging

以 ops-service 为例：

```bash
cd services/ops-service
pip install -r requirements.txt
export LOKI_BASE_URL="http://localhost:3100"
export PROMETHEUS_BASE_URL="http://localhost:9090"
export JAEGER_BASE_URL="http://localhost:16686"
export DOUBAO_API_KEY="your-llm-api-key"

uvicorn app.interface.api:app --host 0.0.0.0 --port 8002 --reload
```

使用任意 HTTP 客户端调用 `/api/ops/analyze` 即可本地体验运维分析能力。

更多细节请参考：

- [`docs/api.md`](docs/api.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/prd.md`](docs/prd.md)
- [`docs/user-manual.md`](docs/user-manual.md)

---

## English Overview

### 1. What Is Aegis Ops Agent

Aegis is an intelligent operations assistant designed to help SRE and operations engineers analyze Kubernetes cluster issues by consuming observability data in a read-only manner.

The agent runs inside your cluster and consumes observability data in a read-only way:

- Prometheus for metrics
- Loki + Promtail for logs
- Jaeger for distributed traces
- Alertmanager webhooks (optional)
- Feishu Bot as chat front-end

Typical workflow:

- Alertmanager fires alerts and sends them to Aegis via webhook.
- Aegis posts a summarized alert notification to a Feishu chat and mentions on-call engineers.
- When engineers mention the bot and describe an incident, Aegis runs an ops analysis flow by calling Prometheus/Loki/Jaeger tools and replies with ranked root-cause candidates and next actions.

The agent is strictly **read-only**. It never performs any write or mutation to your cluster.

### 2. Key Features

- Metrics + logs + traces correlation
- LangChain-based agent with tool orchestration
- Ranked root-cause candidates with probabilities and evidence
- Deep integration with Feishu Bot and Alertmanager
- Kubernetes-native deployment with simple configuration via ConfigMap/Secret
- Multi-model support:
  - Local models: Qwen, GLM-4.7-Flash, DeepSeek-R1
  - Cloud model: Doubao
  - User can specify model in Feishu: `@AegisBot qwen/glm/deepseek/doubao question`

### 3. Deployment

See Chinese sections above and detailed documents:

- [`docs/api.md`](docs/api.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/prd.md`](docs/prd.md)
- [`docs/user-manual.md`](docs/user-manual.md)

The English version focuses on high-level concepts; operational documents are currently in Chinese.
