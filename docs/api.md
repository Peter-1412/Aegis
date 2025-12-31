# Aegis 接口文档

> 面向前端与集成方，描述 Aegis 三个后端微服务的 HTTP 接口。

---

## 1. 通用约定

- 协议：HTTP/HTTPS
- 编码：UTF-8
- 数据格式：JSON
- 认证：当前示例未启用认证，可在网关层或服务层扩展
- 错误码：
  - HTTP 2xx：请求成功
  - HTTP 4xx：参数错误或调用方式错误
  - HTTP 5xx：服务内部错误（包括下游 Loki/Prometheus/LLM 等异常）

时间字段统一使用 ISO8601 字符串，例如：`2025-01-01T08:00:00+08:00`。

---

## 2. ChatOps Service

服务地址示例：

- 本地开发：`http://localhost:8001`
- Kubernetes 集群内：参考 `k8s/chatops-service.yaml`

### 2.1 健康检查

- 方法：`GET`
- 路径：`/healthz`

**请求示例：**

```http
GET /healthz HTTP/1.1
Host: chatops-service
```

**响应示例：**

```json
{
  "status": "ok",
  "service": "chatops-service"
}
```

---

### 2.2 ChatOps 运维问答

- 方法：`POST`
- 路径：`/api/chatops/query`

#### 2.2.1 请求体

```json
{
  "question": "最近 30 分钟 ai-service 有没有 5xx 错误峰值？",
  "time_range": {
    "start": "2025-01-01T08:00:00+08:00",
    "end": "2025-01-01T08:30:00+08:00",
    "last_minutes": null
  },
  "session_id": "optional-session-id"
}
```

字段说明：

- `question`（string，必填）：运维问题（中文或英文均可），长度 1~2000。
- `time_range`（object，可选）：
  - `start` / `end`：时间范围（任一为 null 则视为未指定）。
  - `last_minutes`：最近 N 分钟（1~1440），与 `start/end` 互斥。
- `session_id`（string，可选）：会话 ID，相同 ID 的请求会共享对话历史。

若 `time_range` 为 null 或缺失，则默认使用“当前时间往前 30 分钟”。

#### 2.2.2 响应体

```json
{
  "answer": "最近 30 分钟 ai-service 没有明显的 5xx 峰值，错误率始终低于 1%。",
  "used_logql": "{namespace=\"todo-demo\", app=\"ai-service\"} |~ \"(?i)error|exception|failed\"",
  "start": "2025-01-01T00:00:00+00:00",
  "end": "2025-01-01T00:30:00+00:00",
  "trace": {
    "steps": [
      {
        "index": 0,
        "tool": "trace_note",
        "tool_input": "计划先查看 ai-service 最近 30 分钟的错误率和 5xx 日志。",
        "observation": "计划已记录。",
        "log": null
      },
      {
        "index": 1,
        "tool": "prometheus_query_range",
        "tool_input": "{...}",
        "observation": "{...}",
        "log": null
      }
    ]
  }
}
```

字段说明：

- `answer`（string）：Agent 的最终回答（中文）。
- `used_logql`（string，可空）：本轮分析中实际使用的关键 LogQL（便于前端跳转到日志平台）。
- `start` / `end`（datetime，可空）：本次分析使用的时间范围（统一为 UTC）。
- `trace`（object，可空）：Agent 工具调用轨迹，便于调试和回放。

---

## 3. RCA Service

服务地址示例：

- 本地开发：`http://localhost:8002`

### 3.1 健康检查

- 方法：`GET`
- 路径：`/healthz`

响应格式同 ChatOps。

---

### 3.2 根因分析

- 方法：`POST`
- 路径：`/api/rca/analyze`

#### 3.2.1 请求体

```json
{
  "description": "用户反馈登录失败率在 10:00~10:15 明显升高，主要涉及 user-service。",
  "time_range": {
    "start": "2025-01-01T10:00:00+08:00",
    "end": "2025-01-01T10:15:00+08:00"
  },
  "session_id": "incident-2025-01-01-1"
}
```

字段说明：

- `description`（string，必填）：故障描述，1~4000 字符。
- `time_range`（object，必填）：
  - `start` / `end`：分析时间窗口（CST 或带时区的 ISO8601）。
- `session_id`（string，可选）：会话 ID。

#### 3.2.2 响应体

```json
{
  "summary": "在 10:00~10:15 期间，user-service 的登录接口 401/403 错误率显著升高，根因是近期发布引入的权限校验规则错误。",
  "suspected_service": "user-service",
  "root_cause": "登录流程中对 token 的校验逻辑配置错误，导致合法用户被误判为未授权。",
  "evidence": [
    "Prometheus: user_login_failure_total 在 10:05 左右出现阶跃式上升，错误率从 <1% 升至约 15%。",
    "Loki: {namespace=\"todo-demo\", app=\"user-service\"} 日志中大量出现 \"401 Unauthorized\" 与 \"authentication failed\"。"
  ],
  "suggested_actions": [
    "回滚 user-service 最近一次变更中与权限校验相关的配置或代码。",
    "增加登录失败原因的结构化指标，用于以后更细粒度的监控。"
  ],
  "trace": {
    "steps": [
      {
        "index": 0,
        "tool": "trace_note",
        "tool_input": "计划结合 Prometheus 指标与 user-service 错误日志做 RCA。",
        "observation": "计划已记录。",
        "log": null
      }
    ]
  }
}
```

字段说明：

- `summary`（string）：中文自然语言总结。
- `suspected_service`（string，可空）：最可疑的服务名。
- `root_cause`（string，可空）：简要根因描述。
- `evidence`（string[]）：关键证据点，通常引用指标与日志。
- `suggested_actions`（string[]）：可执行的修复或排查建议。
- `trace`：Agent 工具调用轨迹。

---

## 4. Predict Service

服务地址示例：

- 本地开发：`http://localhost:8003`

### 4.1 健康检查

- 方法：`GET`
- 路径：`/healthz`

响应格式同前。

---

### 4.2 风险预测

- 方法：`POST`
- 路径：`/api/predict/run`

#### 4.2.1 请求体

```json
{
  "service_name": "todo-service",
  "lookback_hours": 24,
  "session_id": "predict-2025-01-01-1"
}
```

字段说明：

- `service_name`（string，必填）：待评估的服务名，例如 `user-service`、`todo-service`、`ai-service`。
- `lookback_hours`（int，可选，默认 24）：回看小时数，范围 1~720。
- `session_id`（string，可选）：会话 ID。

#### 4.2.2 响应体

```json
{
  "service_name": "todo-service",
  "risk_score": 0.63,
  "risk_level": "medium",
  "likely_failures": [
    "todo-service 写数据库时偶发超时，可能导致创建/更新卡顿。",
    "下游 ai-service 调用失败导致部分待办智能推荐功能不可用。"
  ],
  "explanation": "过去 24 小时 todo-service 相关错误日志数量在最近 2 小时有明显上升，且延迟指标尾部有所抬升，但整体错误率仍在可接受范围内，因此评估为中等风险。",
  "trace": {
    "steps": [
      {
        "index": 0,
        "tool": "trace_note",
        "tool_input": "计划查看 todo-service 过去 24 小时错误率与延迟趋势，并拉取错误日志样本。",
        "observation": "计划已记录。",
        "log": null
      }
    ]
  }
}
```

字段说明：

- `service_name`（string）：对应请求参数。
- `risk_score`（float，0.0~1.0）：未来一段时间（约 1~6 小时）发生严重故障的主观风险分。
- `risk_level`（string）：风险等级（如 `low` / `medium` / `high`），与 `risk_score` 对应。
- `likely_failures`（string[]）：未来可能出现的故障类型描述。
- `explanation`（string）：一段面向工程师的中文解释，说明风险判断依据。
- `trace`：Agent 工具调用轨迹。

---

## 5. 错误处理约定

### 5.1 HTTP 状态码

- `400 Bad Request`：请求参数不合法，例如时间范围 `end <= start`。
- `500 Internal Server Error`：内部未捕获异常或下游严重错误。

### 5.2 工具级错误返回

在部分工具（如 `prometheus_query_range`）中，为避免直接抛出异常导致接口 500，会以结构化对象形式返回错误：

```json
{
  "error": "invalid_datetime",
  "message": "Invalid isoformat string: '...'",
  "promql": "...",
  "start_raw": "...",
  "end_raw": "..."
}
```

或：

```json
{
  "error": "prometheus_request_failed",
  "message": "HTTP 500 ...",
  "promql": "...",
  "start": "...",
  "end": "...",
  "step": "60s"
}
```

这些对象会出现在 `trace.steps[*].observation` 中，由大模型决定如何向用户解释。

---

## 6. 接入建议

- 建议通过统一的 API 网关对三个服务进行汇聚与鉴权。
- 若在多集群场景下使用，可在请求头或 Query 参数中增加“集群标识”，由网关路由到不同的 Aegis 实例。
- 对故障工单系统或告警平台，可通过：
  - 调用 RCA 接口为告警事件生成一份根因分析报告；
  - 调用 Predict 接口定期生成服务风险报表。

