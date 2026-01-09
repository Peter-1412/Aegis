# Aegis 作为飞书机器人接入的整体方案

本文档描述如何将 Aegis 封装成一个飞书（Feishu/Lark）机器人，使员工在日常使用飞书办公时可以通过「@aegis + 功能 + 指令」直接驱动 Aegis 的 ChatOps / RCA / Predict 能力，并在飞书会话中收到结果和 Web 控制台链接，点击后跳转到 Aegis 前端查看完整的可视化分析过程。

## 1. 整体架构概览

### 1.1 角色与组件

- **飞书 App / 机器人（Aegis Bot）**
  - 以企业自建应用的形式存在，具备机器人身份。
  - 能接收群聊/单聊中的 @ 消息、Slash 命令或关键词指令。
  - 能向会话中发送文本消息和富文本卡片。
- **Aegis Web 前端**
  - 已有的前端应用（React + Vite）。
  - 暴露入口，例如 `https://aegis.example.com/`。
  - 鉴权策略可后续扩展（SSO、飞书 OAuth 等）。
- **Aegis 后端微服务**
  - `chatops-service`：运维问答。
  - `rca-service`：根因分析。
  - `predict-service`：风险预测。
- **Aegis Feishu Bot 网关服务（新增）**
  - 轻量级 HTTP 服务，负责与飞书平台对接：
    - 处理事件回调（消息/群事件）。
    - 校验签名与事件订阅。
    - 解析指令，调用 Aegis 各微服务 API。
    - 将结果封装成飞书消息/卡片，回复到对应会话。

### 1.2 数据流（以 RCA 为例）

1. 员工在飞书群聊中发送：
   - `@aegis rca 15:00-16:00 用户登录不上去了`
2. 飞书将该消息以事件的形式推送到「事件订阅 URL」，即 Aegis Feishu Bot 网关（例如 `POST https://aegis-gw.example.com/feishu/event`）。
3. 网关服务完成签名校验与 challenge 握手后，从事件中解析：
   - 会话 ID（chat_id）、消息 ID（message_id）、发送者信息。
   - 文本内容（去掉 @aegis 的机器人 mention 部分）。
4. 网关解析命令：
   - `rca` → 选择 `rca-service`。
   - `15:00-16:00` → 解析为具体日期时间范围（CST），例如「今天 15:00~16:00」。
   - `用户登录不上去了` → 作为 RCA 的故障描述。
5. 网关生成一个 `session_id`，调用 Aegis RCA 流式接口：
   - `POST http://rca-service/api/rca/analyze/stream`。
   - 请求体：
     - `description`：用户输入的故障描述。
     - `time_range.start` / `time_range.end`：解析后的 ISO8601 时间。
     - `session_id`：与本次飞书消息线程绑定。
6. Aegis RCA 服务执行 Agent 流程，逐步调用 Prometheus / Loki 工具，产生 RCA 报告与 Trace。
7. 网关消费流式响应：
   - 可以选择：
     - **简化模式**：只在最终结果 ready 后，将 summary + suspected_service + web 链接作为一条飞书消息回复。
     - **流式模式**：在 RCA 执行过程里，以多条消息或一张可更新的互动卡片，逐步展示「正在分析/已获取日志/已得到结论」等。
8. 网关生成 Web 前端链接：
   - 例如：
     - `https://aegis.example.com/#/rca?session_id=...&start=...&end=...`
   - 飞书消息中附带该链接，员工点击后跳转到 Aegis 前端。
   - 前端从 URL 参数中恢复 `session_id` 和时间范围，通过已有的 RCA 页面加载对应 Trace 和可视化过程。

## 2. 飞书侧准备工作

### 2.1 注册企业自建应用

1. 在飞书开发者后台创建一个企业自建应用，例如「Aegis 运维助手」。
2. 开启机器人能力：
   - 配置机器人名称、头像。
   - 允许被拉入单聊/群聊。
3. 为应用开通必要权限（视企业策略而定，典型权限包括）：
   - 接收消息与事件：
     - `im:message` 类权限。
   - 发送消息：
     - 向用户/群聊发送文本消息、富文本消息、卡片消息的权限。
4. 配置重定向 URL / 事件订阅 URL：
   - 事件订阅 URL 指向 Aegis Feishu Bot 网关，例如：
     - `https://aegis-gw.example.com/feishu/event`
   - 记录应用的：
     - `app_id`
     - `app_secret`
     - `verification_token`
     - `encrypt_key`（如果开启消息加密）

### 2.2 配置事件订阅

1. 在飞书应用管理后台中，启用事件订阅。
2. 订阅类型：
   - 机器人接收消息事件，例如：
     - 群聊消息：`im.message.receive_v1`。
   - 可选：加入/退出群聊事件等。
3. 按飞书要求完成 URL 验证：
   - 当飞书发送 `challenge` 请求时，Aegis 网关需要按照协议原样返回 `challenge` 字段以完成校验。

## 3. Aegis Feishu Bot 网关设计

### 3.1 网关服务职责

- 提供一个 HTTP 入口处理飞书事件：
  - `POST /feishu/event`
- 完成以下工作：
  - 校验签名、解密（如启用加密）。
  - 处理 `url_verification` 请求（返回 `challenge`）。
  - 解析消息事件，提取：
    - 文本内容（纯文本 + @机器人部分）。
    - 会话信息（chat_id、message_id）。
    - 发送者身份（user_id / open_id）。
  - 根据命令前缀路由到不同的 Aegis 功能（ChatOps / RCA / Predict）。
  - 将执行结果封装为飞书消息回复。

### 3.2 命令设计（建议）

统一命令格式示例（可按需要调整）：

- **ChatOps 查询**：
  - 群内输入：`@aegis chat 最近30分钟 ai-service 有 5xx 峰值吗？`
  - 解析为：
    - 模式：`chat` → 调用 ChatOps。
    - 时间：`最近30分钟` → 转换为 `last_minutes=30`。
    - 问题：`ai-service 有 5xx 峰值吗？`
- **RCA 分析**：
  - 群内输入：`@aegis rca 15:00-16:00 用户登录不上去了`
  - 解析为：
    - 模式：`rca` → 调用 RCA 服务。
    - 时间范围：`15:00-16:00` → 解析为当天的 15:00~16:00（CST）。
    - 故障描述：`用户登录不上去了`。
- **Predict 风险预测**：
  - 群内输入：`@aegis predict user-service 最近24小时`
  - 解析为：
    - 模式：`predict` → 调用 Predict 服务。
    - 服务名：`user-service`。
    - 回看窗口：`最近24小时` → `lookback_hours=24`。

解析策略建议：

- 先去掉飞书注入的 `@机器人` mention 部分，仅保留纯文本。
- 将剩余文本按空格或特定分隔符拆分：
  - 第一个 token → 模式（chat/rca/predict）。
  - 第二个 token → 时间信息（如 `15:00-16:00` / `最近30分钟`）。
  - 其余部分 → 问题描述或故障描述。
- 时间解析：
  - 若只有 `HH:MM-HH:MM`，可默认使用「当天的 CST」。
  - 也可扩展为支持完整的日期时间，例如：
    - `2025-01-09 15:00-16:00`。

### 3.3 与 Aegis 后端接口的映射

结合 `docs/api.md` 中的接口约定，各模式可映射如下：

#### 3.3.1 ChatOps

- 调用地址：
  - 非流式：`POST http://chatops-service/api/chatops/query`
  - 流式：`POST http://chatops-service/api/chatops/query/stream`
- 请求体结构（简化）：

```json
{
  "question": "最近30分钟 ai-service 有 5xx 峰值吗？",
  "time_range": {
    "last_minutes": 30
  },
  "session_id": "feishu-chat-<chat_id>-<message_id>"
}
```

- 网关根据需要选择：
  - 使用非流式接口，等结果出来后一次性发消息给飞书。
  - 或使用流式接口，将关键步骤转换为飞书多条消息。

#### 3.3.2 RCA

- 调用地址：
  - 非流式：`POST http://rca-service/api/rca/analyze`
  - 流式：`POST http://rca-service/api/rca/analyze/stream`
- 请求体结构：

```json
{
  "description": "用户登录不上去了",
  "time_range": {
    "start": "2025-01-09T15:00:00+08:00",
    "end": "2025-01-09T16:00:00+08:00"
  },
  "session_id": "feishu-chat-<chat_id>-<message_id>"
}
```

- 响应数据（参考 `RCAResponse`）包含：
  - `summary`
  - `suspected_service`
  - `root_cause`
  - `evidence`
  - `suggested_actions`
  - `trace`（用于前端展示完整步骤）

网关可以将 `summary + suspected_service + root_cause` 精简后发回飞书，并在消息中附加 Web 链接查看详情。

#### 3.3.3 Predict

- 调用地址：
  - 非流式：`POST http://predict-service/api/predict/run`
  - 流式：`POST http://predict-service/api/predict/run/stream`
- 请求体结构：

```json
{
  "service_name": "user-service",
  "lookback_hours": 24,
  "session_id": "feishu-chat-<chat_id>-<message_id>"
}
```

- 响应数据包含：
  - `risk_score`
  - `risk_level`
  - `likely_failures`
  - `explanation`
  - `trace`

网关可将 `risk_level + risk_score + explanation` 作为飞书简要回复，并提供 Web 链接查看详细 Trace。

## 4. Web 链接设计与前端适配

### 4.1 链接结构建议

为保证从飞书点击进入前端后能恢复上下文，建议约定如下 URL 形式（示例）：

- ChatOps：
  - `https://aegis.example.com/#/chatops?session_id=<sid>&last_minutes=30`
- RCA：
  - `https://aegis.example.com/#/rca?session_id=<sid>&start=2025-01-09T15:00:00+08:00&end=2025-01-09T16:00:00+08:00`
- Predict：
  - `https://aegis.example.com/#/predict?session_id=<sid>&service_name=user-service&lookback_hours=24`

网关在调用后端时自己生成 `session_id`，同时将这个 `session_id` 写入飞书链接中。

### 4.2 前端如何利用 session_id

当前前端页面已经支持：

- ChatOps 页面从本地 state 中维护 `sessionId`。
- RCA / Predict 页面类似。

为实现“从飞书跳过来即看到对应会话的 Trace”，可以按以下思路扩展（后续迭代中完成）：

1. 前端路由层解析 URL 中的查询参数。
2. 若参数中存在 `session_id`：
   - 覆盖页面内部的 `sessionId` 初始值。
   - 自动触发一次「回放」请求（例如调用非流式接口，或增加一个基于 `session_id` 的 Trace 回放接口）。
3. 将后端返回的 `trace` 填入页面的时间轴与 TracePanel。

这部分需要前后端配合增加「按 session_id 回放会话」的能力，可以作为下一阶段迭代项。

## 5. 飞书消息格式与用户体验建议

### 5.1 文本消息示例（RCA）

当 RCA 分析完成后，可以在群里回复类似消息：

```text
【Aegis RCA 结果】
时间范围：2025-01-09 15:00~16:00
可疑服务：user-service
根因概述：登录接口依赖的 Redis 连接池耗尽导致频繁超时

👉 查看详细分析与日志证据：
https://aegis.example.com/#/rca?session_id=feishu-chat-xxx&start=...&end=...
```

### 5.2 互动卡片（可选）

如需更好的交互体验，可以使用飞书卡片消息（Interactive Card）：

- 标题：`Aegis RCA 结果`
- 字段：
  - 时间范围
  - 可疑服务
  - 根因概述
  - 风险等级（对于 Predict）
- 按钮：
  - 「在 Aegis 中查看详情」 → 跳转到对应 Web 链接。

## 6. 实施步骤清单

### 6.1 基础设施准备

1. 确认 Aegis 三个后端服务在企业网络中可被 Bot 网关访问：
   - `chatops-service`（端口 8001 或通过网关暴露的地址）。
   - `rca-service`（端口 8002 或网关地址）。
   - `predict-service`（端口 8003 或网关地址）。
2. 规划 Aegis Feishu Bot 网关部署方式：
   - 可以是独立微服务（FastAPI / Flask / Node 等）。
   - 或在现有网关中增加一个模块。
3. 准备一个对飞书开放的 HTTPS 域名：
   - 如 `https://aegis-gw.example.com`。

### 6.2 开发 Aegis Feishu Bot 网关

1. 新建服务（以 Python + FastAPI 为例）：
   - 创建 `/feishu/event` 路由。
2. 实现飞书事件处理逻辑：
   - 支持 `url_verification`：
     - 返回 `{ "challenge": body["challenge"] }`。
   - 校验签名（使用 `app_secret` 和请求头中的签名字段）。
   - 如果开启了消息加密，使用 `encrypt_key` 解密消息。
3. 解析消息事件：
   - 仅处理 `im.message.receive_v1` 类型。
   - 从 `event.message.content` 中解析文本（JSON 字符串）。
   - 去除 `@机器人` mention 部分，得到纯指令文本。
4. 解析指令文本：
   - 识别模式（chat/rca/predict）。
   - 解析时间参数（`last_minutes` 或固定时间范围）。
   - 获取问题/描述内容。
5. 构造 `session_id` 与 Aegis 请求体：
   - `session_id` 推荐包含飞书 chat_id/message_id 以便排查，如 `feishu:<chat_id>:<message_id>`。
   - 根据模式调用对应服务的 HTTP 接口。
6. 处理 Aegis 响应：
   - 简化为一个短文本摘要（Answer / summary / explanation）。
   - 生成 Web 链接（携带 session_id 与时间参数）。
7. 调用飞书消息发送 API：
   - 向原始消息所在的 chat_id 发送消息。
   - 内容为文本或互动卡片。

### 6.3 前端与回放能力迭代（可选）

1. 在前端路由层增加对 `session_id` 等参数的识别。
2. 在 RCA / ChatOps / Predict 页面中：
   - 若初始化时检测到 URL 参数带有 `session_id`：
     - 用该值初始化本地 `sessionId`。
     - 自动调用对应服务（或新增的回放接口）获取历史 Trace。
3. 在后端服务中（可选）增加「按 session_id 查询最近一次会话」的接口，用于回放：
   - 简单实现可以直接复用现有接口，通过 `session_id` 和 `time_range` 再跑一遍分析。
   - 进阶实现则需要持久化 Trace 结果。

## 7. 可迭代方向

- **权限与身份映射**：
  - 将飞书用户与 Aegis 内部用户体系或监控权限关联，限制敏感查询。
- **多轮对话支持**：
  - 在同一飞书话题下，使用 `session_id` 维持 ChatOps 多轮上下文。
- **错误可观测性**：
  - 为 Bot 网关自身接入 Prometheus/Loki，便于排查「机器人不回消息」问题。
- **预置命令与帮助**：
  - 支持 `@aegis help` 返回常见命令示例和使用说明。

---

通过以上方案，可以在不大改现有 Aegis 架构的前提下，将其打造成一个飞书中的「运维智能助手」：员工只需要在群里 @aegis 并输入自然语言命令，就能触发 ChatOps / RCA / Predict 能力，并在聊天窗口和 Web 控制台之间无缝切换。该文档可作为后续具体落地实现时的设计蓝本。

