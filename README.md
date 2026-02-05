<div align="center">

# Aegis RCA Agent

面向 Kubernetes 集群的智能根因分析 Agent，支持与飞书机器人集成。

An enterprise-grade RCA agent for Kubernetes, integrated with Feishu Bot.

[简体中文](#aegis-rca-agent) | [English](#english-overview)

</div>

---

## Aegis RCA Agent

### 1. 项目简介

Aegis 现聚焦于一个能力：**RCA（Root Cause Analysis）根因故障定位**。

Agent 部署在你的 Kubernetes 集群中，通过只读方式接入：

- Prometheus（指标）
- Loki + Promtail（日志）
- Jaeger（分布式调用链）
- Alertmanager（告警 Webhook，可选）
- 飞书机器人（作为 Chat 前端）

核心目标：

- 当 Alertmanager 产生告警时，Agent 自动在飞书告警群内 @ 运维同学，汇总关键告警信息。
- 当运维在群内 @ 机器人并描述故障现象时，Agent 自动调用 Prometheus / Loki / Jaeger 工具完成一次 RCA，并在群内给出按概率排序的根因候选列表及后续排查建议。
- Agent 始终以只读身份工作，**绝不执行任何变更操作**。

### 2. 功能特性

- 多源观测数据融合：指标 + 日志 + 调用链
- LangChain Agent + 工具编排，自动选择合适的查询策略
- 根因候选结果按主观概率排序，给出关键指标与日志证据
- 与飞书机器人深度集成：
  - 接收 Alertmanager Webhook，将告警转发至群组并 @所有人
  - 接收群聊中的手工 RCA 请求，自动发起分析并回复结构化结论
- Kubernetes 原生部署，支持 NodePort/Ingress 暴露 HTTP 接口

### 3. 目录结构

```text
Aegis/
├── services/
│   └── rca-service/          RCA 微服务（FastAPI + LangChain Agent）
├── k8s/                      Kubernetes 部署清单
│   ├── namespace.yaml
│   ├── configmap.yaml        只读访问配置（Loki/Prometheus/Jaeger/Feishu）
│   ├── secret.yaml           LLM 与飞书密钥（需自行填写）
│   └── rca-service.yaml      RCA Service 部署与 Service
└── docs/                     文档（接口、架构、PRD 等）
```

rca-service 内部关键模块：

- app/main.py：FastAPI 入口、HTTP 接口、飞书/Alertmanager 集成
- app/agent/executor.py：LangChain AgentExecutor 与系统 Prompt
- app/tools/：Prometheus/Loki/Jaeger/trace_note 等工具
- app/models.py：RCA 请求 / 响应及根因候选数据结构
- app/settings.py：配置（可通过环境变量/K8s ConfigMap 注入）

### 4. 接口概览

详细说明见 [`docs/api.md`](docs/api.md)，这里给出主要接口一览：

| 服务        | 方法 | 路径                     | 说明                            |
|-------------|------|--------------------------|---------------------------------|
| rca-service | GET  | `/healthz`               | 健康检查                        |
| rca-service | POST | `/api/rca/analyze`       | 同步 RCA 分析                   |
| rca-service | POST | `/api/rca/analyze/stream`| 流式 RCA 分析（NDJSON）         |
| rca-service | POST | `/feishu/events`         | 飞书事件订阅回调（消息事件）    |
| rca-service | POST | `/alertmanager/webhook`  | Alertmanager Webhook 回调入口   |

### 5. 部署说明（Kubernetes）

1. 创建命名空间与基础配置：

   ```bash
   kubectl apply -f k8s/namespace.yaml
   kubectl apply -f k8s/configmap.yaml
   kubectl apply -f k8s/secret.yaml
   ```

   在应用前，你需要根据实际环境修改：

   - `k8s/configmap.yaml` 中的 `LOKI_BASE_URL`、`PROMETHEUS_BASE_URL`、`JAEGER_BASE_URL`
   - `k8s/configmap.yaml` 中的 `FEISHU_DEFAULT_CHAT_ID`
   - `k8s/secret.yaml` 中的 `ARK_API_KEY`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_VERIFICATION_TOKEN`

2. 部署 RCA Service：

   ```bash
   kubectl apply -f k8s/rca-service.yaml
   ```

3. 将 `/feishu/events` 与 `/alertmanager/webhook` 暴露到集群外（例如通过 Ingress 或 API Gateway），用于：

   - 飞书开放平台事件订阅回调
   - Alertmanager Webhook 回调

4. 在 Alertmanager 中配置 Webhook 通知地址为 `/alertmanager/webhook`，并在飞书开发者后台配置事件订阅地址为 `/feishu/events`。

### 6. 飞书集成说明（概览）

详细步骤见 [`docs/prd.md`](docs/prd.md) 与 [`docs/user-manual.md`](docs/user-manual.md)，这里给出概要流程：

- 在飞书开放平台创建企业自建应用，获取 `app_id` 与 `app_secret`
- 配置事件订阅，至少开启：
  - 机器人收到消息 `im.message.receive_v1`
- 将应用添加到对应飞书群组，获取群组 `chat_id` 并填入 `FEISHU_DEFAULT_CHAT_ID`
- 在服务器防火墙与飞书开放平台中放通出入口 IP（可使用飞书“获取事件出口 IP”接口）

### 7. 本地开发与调试

以 rca-service 为例：

```bash
cd services/rca-service
pip install -r requirements.txt
export LOKI_BASE_URL="http://localhost:3100"
export PROMETHEUS_BASE_URL="http://localhost:9090"
export JAEGER_BASE_URL="http://localhost:16686"
export ARK_API_KEY="your-llm-api-key"

uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

使用任意 HTTP 客户端调用 `/api/rca/analyze` 即可本地体验 RCA 能力。

更多细节请参考：

- [`docs/api.md`](docs/api.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/prd.md`](docs/prd.md)
- [`docs/user-manual.md`](docs/user-manual.md)

---

## English Overview

### 1. What Is Aegis RCA Agent

Aegis is now focused on a single capability: **Root Cause Analysis (RCA)** for Kubernetes clusters.

The agent runs inside your cluster and consumes observability data in a read-only way:

- Prometheus for metrics
- Loki + Promtail for logs
- Jaeger for distributed traces
- Alertmanager webhooks (optional)
- Feishu Bot as the chat front-end

Typical workflow:

- Alertmanager fires alerts and sends them to Aegis via webhook.
- Aegis posts a summarized alert notification to a Feishu chat and mentions on-call engineers.
- When engineers mention the bot and describe the incident, Aegis runs an RCA flow by calling Prometheus/Loki/Jaeger tools and replies with ranked root-cause candidates and next actions.

The agent is strictly **read-only**. It never performs any write or mutation to your cluster.

### 2. Key Features

- Metrics + logs + traces correlation
- LangChain-based agent with tool orchestration
- Ranked root-cause candidates with probabilities and evidence
- Deep integration with Feishu Bot and Alertmanager
- Kubernetes-native deployment with simple configuration via ConfigMap/Secret

### 3. Deployment

See the Chinese sections above and the detailed documents:

- [`docs/api.md`](docs/api.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/prd.md`](docs/prd.md)
- [`docs/user-manual.md`](docs/user-manual.md)

The English version focuses on high-level concepts; operational documents are currently in Chinese.
