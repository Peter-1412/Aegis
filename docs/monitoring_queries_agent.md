# TodoList 项目：AI 运维 Agent 查询手册

> 面向“智能运维 Agent”的说明文档，用于指导如何通过  
> Prometheus（指标）和 Loki（日志）分析 TodoList 项目的运行状态、业务行为和故障。

---

## 1. 环境与通用约定

- 指标来源：Prometheus
  - 业务服务（user-service、todo-service、ai-service）
  - Kubernetes 节点和集群
  - MySQL Exporter（当前只确认 `mysql_up`、`mysqld_exporter_build_info`）
- 日志来源：Loki
  - 由 Promtail 从 Kubernetes 集群采集
  - 只把 Kubernetes 自带字段作为标签：
    - `namespace`、`app`、`pod`、`container`、`job`、`node_name`、`filename`、`stream`
  - 日志中形如 `service=user-service`、`event=login`、`user=peter`、`user_id=22`、`todo_id=101`、`level=INFO` 等都只是普通文本字段

当你（Agent）需要生成查询时，应遵守以下规则：

- Prometheus 查询只能基于真实存在的指标名，不要凭空假设。
- Loki 查询的选择器只使用已存在的标签，其他维度用文本过滤完成。
- 查询不到数据时，要告诉用户“当前环境没有暴露对应指标/日志”，而不是编造结果。

---

## 2. Prometheus 查询手册（PromQL 模板）

以下模板用于生成 PromQL 查询。请根据用户描述选择合适的模板并替换服务名等变量。

### 2.1 HTTP 请求与错误率

**按服务统计请求速率：**

```promql
sum(rate(http_requests_total[5m])) by (service)
```

**按服务和方法统计请求速率：**

```promql
sum(rate(http_requests_total[5m])) by (service, method)
```

**按服务统计 4xx/5xx 错误率：**

```promql
sum(rate(http_requests_total{status=~"4..|5.."}[5m])) by (service)
/
sum(rate(http_requests_total[5m])) by (service)
```

**按服务统计 P95 / P99 延迟：**

```promql
histogram_quantile(
  0.95,
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service)
)

histogram_quantile(
  0.99,
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service)
)
```

当用户说“某个接口很慢 / 错误很多”时，应优先使用以上查询。

### 2.2 业务指标（用户 / 待办 / AI）

#### 用户服务（user-service）

**注册成功率：**

```promql
rate(user_registration_success_total[5m])
/
(
  rate(user_registration_success_total[5m])
  +
  rate(user_registration_failure_total[5m])
)
```

**登录成功率：**

```promql
rate(user_login_success_total[5m])
/
(
  rate(user_login_success_total[5m])
  +
  rate(user_login_failure_total[5m])
)
```

#### 待办服务（todo-service）

**待办操作速率：**

```promql
rate(todo_created_total[5m])
rate(todo_updated_total[5m])
rate(todo_deleted_total[5m])
rate(todo_completed_total[5m])
```

可用于回答“最近一段时间创建/完成了多少待办”等问题。

#### AI 服务（ai-service）

**AI 对话调用情况：**

```promql
rate(ai_chat_requests_total[5m])
rate(ai_chat_responses_total[5m])
rate(ai_chat_errors_total[5m])
```

**AI 错误率：**

```promql
rate(ai_chat_errors_total[5m])
/
rate(ai_chat_requests_total[5m])
```

### 2.3 服务健康与系统资源

**服务是否存活：**

```promql
up{service=~"user-service|todo-service|ai-service"}
```

**各服务进程内存占用：**

```promql
process_resident_memory_bytes{service=~"user-service|todo-service|ai-service"}
```

**进程 CPU 使用率：**

```promql
rate(process_cpu_seconds_total[5m]) * 100
```

**节点资源情况：**

```promql
node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes * 100

(1 - rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100
```

### 2.4 MySQL 相关指标（当前环境）

当前环境的 mysqld-exporter 已确认可以使用的主要指标：

**MySQL 存活状态：**

```promql
mysql_up
```

- `mysql_up == 1`：数据库对 exporter 可达，认为“存活”。
- `mysql_up == 0`：数据库不可达，应视为故障。

**Exporter 自身信息：**

```promql
mysqld_exporter_build_info
```

如果用户询问 QPS、连接数等更细节的 MySQL 指标，请按如下流程：

1. 在查询框输入 `mysql_`，利用自动补全列出所有可用指标。
2. 如没有找到合适的指标，应明确回答：
   - “当前 mysqld-exporter 只暴露了 `mysql_up` 等少量指标，无法给出更细粒度的数据库性能数据。”

### 2.5 告警逻辑参考（可用于解释问题）

**HTTP 错误率过高：**

```promql
100 * sum(rate(http_requests_total{status=~"5.."}[5m])) by (service)
/
sum(rate(http_requests_total[5m])) by (service) > 5
```

**响应时间过长（P95 > 1 秒）：**

```promql
histogram_quantile(
  0.95,
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service)
) > 1
```

**服务不可用：**

```promql
up{service=~"user-service|todo-service|ai-service"} == 0
```

在解释某次告警时，可以引用这些表达式帮助用户理解触发条件。

---

## 3. Loki 查询手册（LogQL 模板）

### 3.1 选择器与标签规则

- 选择器左侧只允许使用以下标签：
  - `namespace`、`app`、`pod`、`container`、`job`、`node_name`、`filename`、`stream`
- 日志中的业务字段（如 `service=user-service`、`level=INFO`）只能通过文本过滤：
  - 严禁写 `{service="user-service"}` 或 `{service=~"..."}`
  - 必须写成 `{namespace="todo-demo"} |= "service=user-service"`
  - 其他字段如 `event=...`、`user=...`、`user_id=...`、`todo_id=...` 等，也必须用 `|=` 或 `|~` 进行文本过滤

错误示例（不要使用）：

```logql
{service="user-service"}
{service=~"user-service|todo-service|ai-service"}
```

正确示例：

```logql
{namespace="todo-demo"} |= "service=user-service"
{namespace="todo-demo"} |= "service=todo-service"
{namespace="todo-demo"} |= "service=ai-service"
```

### 3.2 基础查询模板

**按服务查看最近日志：**

```logql
{namespace="todo-demo", app="user-service"}
{namespace="todo-demo", app="todo-service"}
{namespace="todo-demo", app="ai-service"}
```

**按服务 + 文本过滤：**

```logql
{namespace="todo-demo"} |= "service=user-service"
{namespace="todo-demo"} |= "service=todo-service"
{namespace="todo-demo"} |= "service=ai-service"
```

**按时间窗口统计错误日志数量：**

```logql
sum by (app) (
  count_over_time(
    {namespace="todo-demo"} |~ "(?i)error|exception|failed" [5m]
  )
)
```

### 3.3 常见场景查询

#### 某个服务最近 15 分钟的错误日志

```logql
{namespace="todo-demo", app="user-service"}
  |~ "(?i)error|exception|failed"
```

或使用日志中的 `service` 字段：

```logql
{namespace="todo-demo"}
  |= "service=user-service"
  |~ "(?i)error|exception|failed"
```

#### 用户登录相关日志

```logql
{namespace="todo-demo"}
  |= "service=user-service"
  |~ "(?i)event=login|login|signin"
```

#### 待办操作相关日志

```logql
{namespace="todo-demo"}
  |= "service=todo-service"
  |~ "(?i)event=todo_create|event=todo_update|event=todo_delete|create|update|delete|complete"
```

#### AI 对话相关日志

```logql
{namespace="todo-demo"}
  |= "service=ai-service"
  |~ "(?i)event=ai_chat|chat|request|response"
```

#### 某个用户最近 N 分钟的操作行为（跨服务）

在 Todo_List 的日志设计规范中（详见 `docs/todolist_logging_design.md`），推荐在关键业务日志中统一使用如下字段：

- `service`：服务名，例如 `user-service`、`todo-service`、`ai-service`
- `event`：事件类型，例如 `login`、`register`、`todo_create`、`todo_update`、`todo_delete`、`ai_chat`、`http_request` 等
- `user`：用户名，例如 `user=peter`
- `user_id`：内部用户 ID，例如 `user_id=22`
- `todo_id`：待办 ID，例如 `todo_id=101`
- `status`：结果状态，例如 `status=success` 或 `status=failure`

按照该规范落地后，各服务日志的典型形态为：

- user-service 登录成功日志：一定包含 `user=peter`，并推荐同时包含 `user_id=22`：
  - `service=user-service event=login user=peter user_id=22 status=success`
- todo-service 业务日志：只包含 `user_id=22` 和 `todo_id=...`，不再重复用户名：
  - `service=todo-service event=todo_create todo_id=101 user_id=22 ...`
- ai-service 业务日志：只包含 `user_id=22`：
  - `service=ai-service event=ai_chat user_id=22 status=success`

在实际环境中，如果某些字段（例如 `user_id`）尚未完全按规范落地，你在查询时要注意区分：

- 如果在 user-service 登录成功日志中能看到 `user_id=...`，可以用它做跨服务关联
- 如果看不到 `user_id`，只能基于用户名 `user=peter` 给出更保守的结论，并在回答中说明“日志中缺少 user_id 字段，无法完全对齐 todo/ai-service 的行为”

当需要回答“某个用户在最近一段时间做了什么”时，建议按照下面的顺序构造查询：

1. 先在 user-service 日志中根据用户名定位登录行为，并在可能的情况下顺便获取用户 ID：

   ```logql
   {namespace="todo-demo"}
     |= "service=user-service"
     |~ "(?i)event=login|login|signin"
     |= "user=peter"
   ```

   - 理想情况（日志已按规范改造）：同一行中还会包含 `user_id=22`，可以把该值记为当前用户的 `user_id`
   - 兼容情况（日志尚未完全改造）：如果没有 `user_id` 字段，也要把这些登录日志视为有效证据，而不能因为缺少 `user_id` 就认为没有该用户相关日志

2. 再使用该 `user_id` 去 todo-service / ai-service 中查找业务操作日志：

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

3. 将上述查询结果按时间排序，归纳该用户在最近 N 分钟内在各个服务上的主要行为，例如：

   - 在 user-service 的登录 / 鉴权记录；
   - 在 todo-service 的待办创建、更新、完成操作；
   - 在 ai-service 中与 AI 助手的对话请求。

如果在 user-service 中能找到该用户的登录记录，但在 todo-service / ai-service 中没有匹配到对应的 `user_id`，应在回答中明确说明“仅在 user-service 找到登录相关日志，暂未看到该用户在其他服务上的业务操作日志”。

如果在当前环境中确实还没有按照规范输出 `user_id` 或 `event` 字段，也要在回答中解释清楚这一限制，而不要假设这些字段一定存在。

### 3.4 聚合与统计

**按服务统计最近 1 小时日志总量：**

```logql
sum by (app) (
  count_over_time({namespace="todo-demo"} [1h])
)
```

**按服务统计最近 5 分钟错误日志量：**

```logql
sum by (app) (
  count_over_time(
    {namespace="todo-demo"} |~ "(?i)error|exception|failed" [5m]
  )
)
```

---

## 4. Prometheus + Loki 联合分析流程

当用户让你“排查某个服务的问题”或“解释一次故障”时，建议按照下面的顺序行动：

1. **用 Prometheus 做健康检查**
   - 查询 `up{service="<服务名>"}` 看服务是否存活。
   - 查询 HTTP 请求速率、错误率、P95 延迟。
   - 查询对应的业务指标（例如注册/登录成功率、待办创建速率、AI 错误率）。
2. **用 Loki 拉取细节日志**
   - 用 `{namespace="todo-demo", app="<服务名>"}` 或 `|= "service=<服务名>"` 锁定服务。
   - 用 `|~ "(?i)error|exception|failed"` 等关键字过滤错误日志。
3. **整理并输出结论**
   - 指出哪个时间段、哪个服务的哪些指标异常。
   - 引用一两条典型错误日志来解释可能原因。
   - 如果指标或日志不存在，要明确说明“当前环境没有这类数据”。

---

## 5. 给 AI 运维 Agent 的提示词示例

下面是一段可以直接放进 Agent 系统 Prompt 的指令文本：

- 你接入了两个数据源：
  - `Prometheus`：通过 PromQL 查询指标。
  - `Loki`：通过 LogQL 查询日志。
- 在分析 TodoList 项目时：
  - 优先使用本手册中的 PromQL / LogQL 模板生成查询。
  - 所有结论必须有查询结果作为依据，不要编造不存在的指标或标签。
- 当用户问“某个服务的状态”时：
  1. 先在 Prometheus 中查询该服务的存活状态、错误率和延迟。
  2. 再在 Loki 中查询该服务最近一段时间的错误日志。
  3. 综合指标和日志给出解释。
- 使用 Loki 时：
  - 只在选择器中使用 Kubernetes 原生标签（如 `namespace`、`app`）。
  - 把 `service=`、`level=` 等视为普通文本，用 `|=` 或 `|~` 过滤。
- 用户询问 MySQL 健康状况时：
  - 查询 `mysql_up`，解释 0 和 1 的含义。
  - 如用户要求 QPS、连接数等指标，而当前环境未暴露，请如实说明限制。

> 总体原则：  
> - 用指标做“宏观判断”，用日志做“细节解释”。  
> - 优先选择简单、鲁棒的查询模板，避免复杂且易报错的表达式。  
> - 查询为空时，先检查指标/标签是否存在，再向用户解释原因。
