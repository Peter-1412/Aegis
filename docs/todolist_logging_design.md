# Todo_List 项目：日志设计规范

版本：v1.0（仅设计规范，不直接修改现有代码）

---

## 1. 设计目标

Todo_List 项目目前已经接入 Prometheus + Loki，并在 user-service、todo-service、ai-service 中使用 Python `logging` 输出文本日志。  
本规范的目标是：

- 统一三大服务的日志格式与字段命名
- 明确“当前已有的日志行为”和“推荐补充的字段”，方便后续迭代落地
- 让 Aegis 这类 AI 运维 Agent 能够更稳定地基于日志做：
  - 故障排查（错误、慢请求）
  - 用户行为分析（登录、待办操作、AI 对话）
  - 跨服务关联分析（同一用户在多个服务上的行为）

> 重要说明：  
> 本文档只描述“目标日志设计”，不会改动任何现有代码。  
> 实际日志输出仍以当前代码为准，落地本规范需要后续在各服务中逐步调整日志语句。

---

## 2. 日志总体格式约定

### 2.1 基本格式

三大服务都已通过 `logging.basicConfig` 使用类似的格式：

```text
%(asctime)s %(levelname)s service=<service-name> %(message)s
```

本规范在此基础上做约定：

- `asctime`：统一为本地时间或 UTC，保持 Loki 中时间线可读
- `levelname`：使用 `INFO`、`WARNING`、`ERROR`、`CRITICAL` 等标准等级
- `service`：固定为下列之一：
  - `user-service`
  - `todo-service`
  - `ai-service`
- `message`：统一采用 `key=value` 风格的业务字段，避免自由文本难以检索

### 2.2 通用字段约定

推荐在业务日志中尽量使用以下通用字段（根据场景选择）：

- `service`：服务名（通过 format 模板已经包含）
- `event`：事件类型，如 `login`、`register`、`todo_create`、`todo_update`、`ai_chat`
- `user`：用户名（如 `peter`）
- `user_id`：内部用户 ID（如 `22`）
- `todo_id`：待办 ID（如 `101`）
- `status`：结果状态，如 `success`、`failure`
- `reason`：失败原因的机器可读标识，如 `invalid_credentials`、`username_exists`
- `method`：HTTP 方法，如 `GET`、`POST`
- `path`：请求路径，如 `/api/auth/login`
- `duration_ms`：请求耗时，单位毫秒

> 只要日志中出现 `key=value` 形式的字段，就可以在 Loki 中通过 `|= "key=value"` 或正则 `|~ "key=..."` 进行过滤。

---

## 3. 当前日志实现概览

本节基于 Todo_List 现有代码，描述“已经在生产中的日志行为”，作为后续改造的基线。

### 3.1 user-service

配置（来自 `d:\Code\Python_Study\Todo_List\user-service\main.py`）：

```python
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)s service=user-service %(message)s",
)
```

#### 3.1.1 HTTP 请求日志

在中间件 `_req_logger` 中记录：

- 过滤掉 `/metrics`、`/health`、`/healthz`、`/livez`、`/readyz`
- 记录方法、路径、状态码、耗时：

```text
request method=POST path=/api/auth/login status=200 duration_ms=12.34
```

特点：

- 有 `method`、`path`、`status`、`duration_ms` 字段
- 没有用户信息（username / user_id）

#### 3.1.2 用户注册日志

- 注册失败（用户名已存在）：

```text
event=register user=peter result=failure reason=username_exists
```

- 注册成功：

```text
event=register user=peter result=success
```

当前情况：

- 有 `event`、`user`、`result`、`reason`
- 没有 `user_id`

#### 3.1.3 用户登录日志

- 登录失败（密码错误等）：

```text
event=login user=peter result=failure reason=invalid_credentials
```

- 登录成功：

```text
event=login user=peter result=success
```

当前情况：

- 有 `event`、`user`、`result`、`reason`
- 没有 `user_id`

> 影响：  
> 目前仅通过日志无法从用户名 `user=peter` 直接推导出 `user_id=22`，因此在 Loki 中很难“跨服务按用户聚合”。

### 3.2 todo-service

配置（来自 `d:\Code\Python_Study\Todo_List\todo-service\main.py`）：

```python
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)s service=todo-service %(message)s",
)
```

#### 3.2.1 HTTP 请求日志

与 user-service 类似的请求日志：

```text
request method=POST path=/api/todos status=200 duration_ms=5.12
```

#### 3.2.2 业务事件日志

- 创建待办：

```text
todo created id=101 user_id=22
```

- 更新待办：

```text
todo updated id=101 completed=True user_id=22
```

- 删除待办：

```text
todo deleted id=101 user_id=22
```

当前情况：

- 已经包含 `user_id` 和 `id`（可视为 `todo_id`）
- 未显式使用 `event` 字段，而是把事件放在自然语言中（如 `todo created`）

### 3.3 ai-service

配置（来自 `d:\Code\Python_Study\Todo_List\ai-service\main.py`）：

```python
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)s service=ai-service %(message)s",
)
```

#### 3.3.1 HTTP 请求日志

中间件与其他服务一致：

```text
request method=POST path=/api/ai/chat status=200 duration_ms=80.50
```

#### 3.3.2 AI 对话日志

在 `/api/ai/chat` 成功返回时记录：

```text
ai chat user_id=22
```

当前情况：

- 已有 `user_id`
- 没有 `event` 字段，事件类型靠自然语言 `ai chat` 表达

---

## 4. 推荐统一日志规范

本节给出“目标状态”的日志规范，后续可以按需在 Todo_List 各服务中逐步改造日志语句。

### 4.1 通用规范

1. 所有业务事件日志都应显式包含：
   - `service`
   - `event`
   - 与用户相关的：`user` 和/或 `user_id`
2. 涉及待办任务的日志应包含：
   - `todo_id`
3. 涉及结果的操作应包含：
   - `status`（success / failure）
   - 如失败，再增加 `reason`
4. HTTP 请求日志中尽量统一：
   - `event=http_request`
   - `method`、`path`、`status`、`duration_ms`

### 4.2 HTTP 请求日志（所有服务通用）

推荐统一改为如下格式：

```text
service=user-service event=http_request method=POST path=/api/auth/login status=200 duration_ms=12.34
service=todo-service event=http_request method=POST path=/api/todos status=200 duration_ms=5.12
service=ai-service event=http_request method=POST path=/api/ai/chat status=200 duration_ms=80.50
```

改造要点：

- 在现有 `logging.info("request method=%s path=%s status=%s duration_ms=%.2f", ...)` 的基础上：
  - 固定在 message 开头增加 `event=http_request`

收益：

- 使用 Loki 可以统一按 `event=http_request` 过滤所有服务的请求日志，再根据 `service`、`path`、`status` 做细分。

### 4.3 user-service 业务事件日志

目标是让“用户名”和“内部 user_id”都出现在关键业务事件中，方便跨服务关联。

#### 4.3.1 注册事件

推荐目标格式：

- 注册失败：

```text
service=user-service event=register user=peter status=failure reason=username_exists
```

- 注册成功：

```text
service=user-service event=register user=peter user_id=22 status=success
```

> 注：当前代码尚未在日志中输出 `user_id`，可以在完成用户插入数据库后，从 `u.id` 中取出并加入日志。

#### 4.3.2 登录事件

推荐目标格式：

- 登录失败：

```text
service=user-service event=login user=peter status=failure reason=invalid_credentials
```

- 登录成功：

```text
service=user-service event=login user=peter user_id=22 status=success
```

说明：

- 一旦在登录成功日志中补充了 `user_id`，Aegis 中的 Agent 就可以：
  1. 先根据 `user=peter` 找到 `user_id=22`
  2. 再在 todo-service、ai-service 中用 `user_id=22` 过滤业务日志，实现跨服务用户行为分析

### 4.4 todo-service 业务事件日志

当前已经有 `user_id` 和 `id`，推荐进一步统一为带 `event` 的形式。

#### 4.4.1 创建待办

目标格式：

```text
service=todo-service event=todo_create todo_id=101 user_id=22 title="xxx"
```

#### 4.4.2 更新待办

目标格式：

```text
service=todo-service event=todo_update todo_id=101 user_id=22 completed=True
```

#### 4.4.3 删除待办

目标格式：

```text
service=todo-service event=todo_delete todo_id=101 user_id=22
```

说明：

- 可以在现有 `logging.info("todo created id=%s user_id=%s", ...)` 基础上，将 `id` 改名为更语义化的 `todo_id`，并添加 `event=...` 前缀。

### 4.5 ai-service 业务事件日志

目标是让 AI 对话事件也具备 `event` 和 `user_id`，必要时可扩展会话 ID。

#### 4.5.1 AI 对话成功

目标格式：

```text
service=ai-service event=ai_chat user_id=22 status=success
```

如需进一步追踪，可以增加：

```text
service=ai-service event=ai_chat user_id=22 status=success chat_id=abc123
```

#### 4.5.2 AI 对话失败

在捕获异常、增加 `AI_CHAT_ERRORS_TOTAL` 的同时，建议增加错误日志：

```text
service=ai-service event=ai_chat user_id=22 status=failure reason=ai_service_error
```

---

## 5. 面向 Loki 的典型查询示例（基于本规范）

本小节给出的是“当 Todo_List 日志已经按照本规范改造后”可以使用的 LogQL 模板，供 Aegis 等 Agent 参考。

### 5.1 按用户查看跨服务行为

#### 5.1.1 从 user-service 中找到 user_id

```logql
{namespace="todo-demo"}
  |= "service=user-service"
  |= "event=login"
  |= "user=peter"
  |= "status=success"
```

从日志行中解析出 `user_id=22`。

#### 5.1.2 使用 user_id 关联 todo-service 和 ai-service

```logql
{namespace="todo-demo"}
  |= "user_id=22"
  |~ "service=todo-service|service=ai-service"
```

或分别查询：

```logql
{namespace="todo-demo"}
  |= "service=todo-service"
  |= "user_id=22"
```

```logql
{namespace="todo-demo"}
  |= "service=ai-service"
  |= "user_id=22"
```

### 5.2 按事件类型聚合

#### 5.2.1 所有服务的业务事件日志

```logql
{namespace="todo-demo"} |= "event="
```

#### 5.2.2 登录失败日志

```logql
{namespace="todo-demo"}
  |= "service=user-service"
  |= "event=login"
  |= "status=failure"
```

#### 5.2.3 待办完成操作

```logql
{namespace="todo-demo"}
  |= "service=todo-service"
  |= "event=todo_update"
  |= "completed=True"
```

### 5.3 慢请求分析

基于统一的 `event=http_request`：

```logql
{namespace="todo-demo"}
  |= "event=http_request"
  |= "service=user-service"
  |~ "duration_ms=(1[0-9]{3}|[2-9][0-9]{3,})"
```

> 说明：上面的正则仅为示例，用于匹配 `duration_ms` 超过一定阈值的请求，实际阈值可以调整。

---

## 6. 与 Aegis / AI 运维 Agent 的对接建议

1. Aegis 中的 `docs/monitoring_queries_agent.md` 可以明确引用本规范：
   - 当 Todo_List 日志已经按本规范改造时，可以使用“按 `event`、`user_id`、`todo_id` 的高级查询模板”
   - 当日志尚未完全改造时，应退化为更保守的查询，并在回答中说明限制
2. 对于“某个用户在最近一段时间做了什么”的问题：
   - 理想流程：
     1. 在 user-service 日志中通过 `user=<用户名>` 和 `event=login` 查出对应的 `user_id`
     2. 再用 `user_id` 去 todo-service / ai-service 中过滤日志
   - 现状（未补充 `user_id` 之前）：
     - 日志中缺少 `user_id`，Agent 无法仅凭日志完成跨服务用户行为归并
     - 需要在回答中明确说明这一限制，避免编造关联关系

---

## 7. 落地本规范的推荐顺序

1. 在三大服务的 HTTP 请求中间件中，统一将请求日志改为带 `event=http_request` 的形式
2. 在 user-service 的注册 / 登录成功日志中补充 `user_id`
3. 在 todo-service / ai-service 的业务日志中统一增加 `event` 字段，并将 `id` 改为语义化字段名（如 `todo_id`
4. 在 Aegis 的 Agent Prompt / 查询文档中，分别描述：
   - “当前已落地的日志字段可以如何使用”
   - “尚未落地的字段对应的能力暂不可用，需要在回答中说明限制”

完成以上步骤后，Todo_List 的日志体系将更适合被 Aegis 等智能运维系统消费和分析。

