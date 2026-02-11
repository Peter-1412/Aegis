# API 参考文档 / API Reference

> 本文档只覆盖当前仍在使用的 **Ops Service** 能力，所有接口均为只读，不会对集群或业务产生任何修改。

## 1. 基础信息

- 服务名称：`ops-service`
- 技术栈：FastAPI + LangChain
- 默认监听端口：`8002`
- 所有接口返回 JSON，除 `/api/ops/analyze/stream` 为 `application/x-ndjson`

---

## 2. 健康检查

- 方法：`GET`
- 路径：`/healthz`

### 响应示例

```json
{
  "status": "ok",
  "service": "ops-service"
}
```

---

## 3. 同步运维分析接口

- 方法：`POST`
- 路径：`/api/ops/analyze`
- 说明：一次性返回运维总结、按概率排序的根因候选列表，以及后续建议

### 请求体

```json
{
  "description": "20:15 开始用户反馈任务列表页面访问很慢，部分请求 502。",
  "time_range": {
    "start": "2025-01-15T20:00:00+08:00",
    "end": "2025-01-15T20:30:00+08:00"
  },
  "session_id": "optional-session-id"
}
```

- `description`：故障描述，中文自然语言，必填。
- `time_range.start`：开始时间（ISO8601），建议使用 CST（UTC+8）。
- `time_range.end`：结束时间（ISO8601），必须大于 `start`。
- `session_id`：会话标识，用于在多轮对话中保留上下文，可选。

### 响应体

```json
{
  "summary": "本次故障主要表现为 todo-service 在 20:10~20:20 突然出现 5xx 峰值和延迟抖动，疑似下游 MySQL 短暂不可用。",
  "ranked_root_causes": [
    {
      "rank": 1,
      "service": "todo-service",
      "probability": 0.78,
      "description": "todo-service 访问数据库出现大量连接超时和死锁，导致接口 5xx 和请求排队。",
      "key_indicators": [
        "todo-service http_requests_total 5xx 在 20:12~20:18 明显升高",
        "对应时间段 http_request_duration_seconds P95 接近 3s"
      ],
      "key_logs": [
        "2025-01-15T12:13:05Z [app=todo-service] ... connect to mysql timeout ...",
        "2025-01-15T12:13:08Z [app=todo-service] ... Deadlock found when trying to get lock ..."
      ]
    }
  ],
  "next_actions": [
    "在 Grafana 中进一步放大 todo-service 相关面板，确认是否存在资源瓶颈或连接池耗尽。",
    "检查数据库慢查询与锁等待情况，评估是否需要优化索引或拆分热点表。"
  ],
  "trace": {
    "steps": [
      {
        "index": 0,
        "tool": "prometheus_query_range",
        "tool_input": "{\"query\":\"sum(rate(http_requests_total{service=\\\"todo-service\\\",status=~\\\"5..\\\"}[5m]))\",\"start_iso\":\"2025-01-15T20:10:00+08:00\",\"end_iso\":\"2025-01-15T20:25:00+08:00\",\"step\":\"30s\"}",
        "observation": null,
        "log": null
      }
    ]
  }
}
```

字段说明：

- `summary`：整体中文总结，面向 SRE/运维工程师。
- `ranked_root_causes`：根因候选列表，按 `rank` 从 1 递增排序。
  - `rank`：排序序号，1 表示最可能的根因。
  - `service`：最相关的服务名，可能为空（无法定位到单一服务）。
  - `probability`：主观概率，0.0~1.0 之间，可为空。
  - `description`：根因简要描述。
  - `key_indicators`：用于支持结论的关键指标结论列表。
  - `key_logs`：关键日志或调用链证据片段。
- `next_actions`：后续建议操作列表，按优先级排序。
- `trace`：Agent 工具调用轨迹，便于审计与故障回放。

---

## 4. 流式运维分析接口

- 方法：`POST`
- 路径：`/api/ops/analyze/stream`
- 返回类型：`application/x-ndjson`

该接口与 `/api/ops/analyze` 请求体完全一致，但响应为多行 NDJSON，每行一个 JSON 对象，便于前端实时展示 Agent 思考过程。

### 响应事件类型

- `start`：分析开始事件
- `llm_start` / `llm_token` / `llm_end`：LLM 调用过程
- `agent_thought`：Agent 思考过程（规划阶段）
- `agent_action`：执行某个工具
- `tool_start` / `tool_end`：具体工具调用前后
- `agent_observation`：Agent 对工具返回结果的观察
- `error`：流程中发生错误
- `final`：最终运维分析结果（结构同 `/api/ops/analyze`，附加事件字段）
- `end`：整个流式会话结束

客户端只需逐行读取并解析 JSON，根据 `event` 字段进行 UI 更新。

---

## 5. 飞书长连接事件处理

ops-service 提供独立的飞书事件网关（长连接），使用 `lark-oapi` 订阅 `im.message.receive_v1` 事件：

- 当用户在飞书群中 @机器人并发送文本消息时：
  - SDK 通过长连接收到事件；
  - 事件网关将消息转发到 ops-service 的 `/feishu/receive`；
  - ops-service 将消息文本作为 `description`，使用最近 15 分钟时间窗口执行运维分析；
  - 分析完成后，通过开放平台接口向同一个 `chat_id` 发送结构化文本结果。

该模式下不再暴露 `/feishu/events` HTTP 回调接口，也不需要配置任何公网 IP 或域名。

实际发送消息的错误会记录在服务日志中。

---

## 6. Alertmanager Webhook 接口

- 方法：`POST`
- 路径：`/alertmanager/webhook`

Alertmanager 配置示例（仅片段）：

```yaml
receivers:
  - name: "aegis-ops"
    webhook_configs:
      - url: "http://aegis-ops-service.example.com/alertmanager/webhook"
```

### 请求体结构（与标准 Alertmanager Webhook 一致，示意）

```json
{
  "status": "firing",
  "receiver": "aegis-ops",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "KubernetesPodCrashLooping",
        "severity": "critical",
        "instance": "todo-service-7c9f7d44bb-p2x7b"
      },
      "annotations": {
        "summary": "todo-service pod is restarting too frequently"
      },
      "startsAt": "2025-01-15T12:10:00Z",
      "endsAt": "0001-01-01T00:00:00Z"
    }
  ]
}
```

ops-service 行为：

- 将所有告警汇总成一条飞书文本消息
- 自动在消息开头加入 `@所有人` 提示
- 按序列列出每条告警的名称、严重级别、实例与摘要

### 响应示例

```json
{
  "status": "ok",
  "sent_to": "oc_xxx",
  "alert_count": 3
}
```

如果未配置 `FEISHU_DEFAULT_CHAT_ID` 或没有告警，则会返回 `ignored` 状态。

---

# API Reference

> This document covers the capabilities of the **Ops Service**. All endpoints are read-only and will not make any modifications to the cluster or business systems.

## 1. Basic Information

- Service Name: `ops-service`
- Tech Stack: FastAPI + LangChain
- Default Port: `8002`
- All endpoints return JSON, except `/api/ops/analyze/stream` which returns `application/x-ndjson`

---

## 2. Health Check

- Method: `GET`
- Path: `/healthz`

### Response Example

```json
{
  "status": "ok",
  "service": "ops-service"
}
```

---

## 3. Synchronous Ops Analysis Endpoint

- Method: `POST`
- Path: `/api/ops/analyze`
- Description: Returns a summary, ranked root cause candidates, and suggested actions in a single response

### Request Body

```json
{
  "description": "Users reported slow page load at 20:15, with some 502 errors.",
  "time_range": {
    "start": "2025-01-15T20:00:00+08:00",
    "end": "2025-01-15T20:30:00+08:00"
  },
  "session_id": "optional-session-id"
}
```

- `description`: Fault description in natural language (Chinese), required.
- `time_range.start`: Start time (ISO8601), recommended to use CST (UTC+8).
- `time_range.end`: End time (ISO8601), must be greater than `start`.
- `session_id`: Session identifier for maintaining context across multiple conversations, optional.

### Response Body

```json
{
  "summary": "The incident primarily manifested as a sudden spike in 5xx errors and latency jitter in todo-service between 20:10~20:20, likely due to temporary unavailability of downstream MySQL.",
  "ranked_root_causes": [
    {
      "rank": 1,
      "service": "todo-service",
      "probability": 0.78,
      "description": "todo-service experienced massive connection timeouts and deadlocks when accessing MySQL, leading to 5xx errors and request queuing.",
      "key_indicators": [
        "todo-service http_requests_total 5xx spiked significantly between 20:12~20:18",
        "Corresponding time period http_request_duration_seconds P95 approached 3s"
      ],
      "key_logs": [
        "2025-01-15T12:13:05Z [app=todo-service] ... connect to mysql timeout ...",
        "2025-01-15T12:13:08Z [app=todo-service] ... Deadlock found when trying to get lock ..."
      ]
    }
  ],
  "next_actions": [
    "Further investigate todo-service database connection metrics and slow queries in Grafana to confirm connection pool exhaustion or lock waits.",
    "Check database slow queries and lock waits, evaluate if index optimization or hot table sharding is needed."
  ],
  "trace": {
    "steps": [
      {
        "index": 0,
        "tool": "prometheus_query_range",
        "tool_input": "{\"query\":\"sum(rate(http_requests_total{service=\\\"todo-service\\\",status=~\\\"5..\\\"}[5m]))\",\"start_iso\":\"2025-01-15T20:10:00+08:00\",\"end_iso\":\"2025-01-15T20:25:00+08:00\",\"step\":\"30s\"}",
        "observation": null,
        "log": null
      }
    ]
  }
}
```

Field descriptions:

- `summary`: Overall summary in natural language, oriented towards SRE/Ops engineers.
- `ranked_root_causes`: List of root cause candidates, sorted by `rank` in ascending order.
  - `rank`: Sort order, 1 indicates the most likely root cause.
  - `service`: Most relevant service name, may be empty (cannot locate to a single service).
  - `probability`: Subjective probability, between 0.0~1.0, may be empty.
  - `description`: Brief description of the root cause.
  - `key_indicators`: List of key metric conclusions supporting the conclusion.
  - `key_logs`: Key log or trace evidence fragments.
- `next_actions`: List of suggested follow-up actions, sorted by priority.
- `trace`: Agent tool invocation trace, useful for auditing and incident post-mortem.

---

## 4. Streaming Ops Analysis Endpoint

- Method: `POST`
- Path: `/api/ops/analyze/stream`
- Return Type: `application/x-ndjson`

This endpoint has the same request body as `/api/ops/analyze`, but returns multiple lines of NDJSON, with each line being a JSON object, facilitating real-time display of the agent's thinking process.

### Response Event Types

- `start`: Analysis start event
- `llm_start` / `llm_token` / `llm_end`: LLM invocation process
- `agent_thought`: Agent thinking process (planning phase)
- `agent_action`: Executing a specific tool
- `tool_start` / `tool_end`: Before and after specific tool invocation
- `agent_observation`: Agent's observation of tool return results
- `error`: Error occurred during the process
- `final`: Final ops analysis result (structure same as `/api/ops/analyze`, with additional event fields)
- `end`: End of the entire streaming session

Clients should read line by line and parse JSON, updating the UI based on the `event` field.

---

## 5. Feishu Long Connection Event Handling

ops-service provides a standalone Feishu event gateway (long connection) using `lark-oapi` to subscribe to `im.message.receive_v1` events:

- When users @mention the bot in a Feishu group and send a text message:
  - The SDK receives the event via long connection;
  - The event gateway forwards the message to ops-service's `/feishu/receive`;
  - ops-service uses the message text as `description`, executes ops analysis using the last 15 minutes as the time window;
  - After analysis completes, sends a structured text result back to the same `chat_id` via the open platform API.

This mode no longer exposes the `/feishu/events` HTTP callback endpoint, nor does it require configuring any public IP or domain.

Errors in sending messages are logged in the service logs.

---

## 6. Alertmanager Webhook Endpoint

- Method: `POST`
- Path: `/alertmanager/webhook`

Alertmanager configuration example (partial):

```yaml
receivers:
  - name: "aegis-ops"
    webhook_configs:
      - url: "http://aegis-ops-service.example.com/alertmanager/webhook"
```

### Request Body Structure (consistent with standard Alertmanager Webhook, example)

```json
{
  "status": "firing",
  "receiver": "aegis-ops",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "KubernetesPodCrashLooping",
        "severity": "critical",
        "instance": "todo-service-7c9f7d44bb-p2x7b"
      },
      "annotations": {
        "summary": "todo-service pod is restarting too frequently"
      },
      "startsAt": "2025-01-15T12:10:00Z",
      "endsAt": "0001-01-01T00:00:00Z"
    }
  ]
}
```

ops-service behavior:

- Aggregates all alerts into a single Feishu text message
- Automatically adds `@all` at the beginning of the message
- Lists each alert's name, severity level, instance and summary in sequence

### Response Example

```json
{
  "status": "ok",
  "sent_to": "oc_xxx",
  "alert_count": 3
}
```

If `FEISHU_DEFAULT_CHAT_ID` is not configured or there are no alerts, it will return an `ignored` status.
