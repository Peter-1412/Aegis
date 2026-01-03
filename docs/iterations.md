# Aegis 迭代与缺陷总结文档

版本：v1.0  
目的：系统性记录 Aegis 在开发过程中的关键版本、缺陷、修复方式与经验教训，便于后续团队复盘与知识传承。

---

## 1. 迭代时间线概览

> 时间为相对顺序，未绑定具体日期。

| 版本 | 主要变更                                                         |
|------|------------------------------------------------------------------|
| v0.1 | 搭建三套 FastAPI 服务与前端原型，打通基础 LLM 调用链。           |
| v0.2 | 引入 Prometheus 查询工具，支持按时间范围执行 PromQL。           |
| v0.3 | 将工具按“一个工具一个文件”拆分，提升可维护性。                   |
| v0.4 | 将所有 `ai-log-agent` 命名统一调整为 `aegis`，包含 K8s 部署等。 |
| v0.5 | 结合 Todo_List 监控手册重写系统 Prompt，升级 Predict 为 LLM 主导。 |
| v0.6 | 修复 Prompt 花括号与 Prometheus 时间解析导致的 500 等鲁棒性问题。 |
| v0.7 | 引入三服务流式输出与前端短时间窗口预设，并强化 Prompt 与监控手册一致性。 |
| v0.8 | 重构 Agent 可视化与操作流时间轴，并修复 Predict 卡死问题。       |

以下按版本详细记录关键变更与缺陷。

---

## 2. v0.1：基础能力打通

### 2.1 功能

- 为 ChatOps / RCA / Predict 三个场景分别创建 FastAPI 服务。
- 为每个服务构建 LangChain Agent，接入 LLM（火山方舟 Ark）。
- 前端提供三个简单页面与三个后端接口对接。

### 2.2 问题与教训

- 早期 Agent 的 Prompt 较为粗糙，对 PromQL/LogQL 的约束不明确。
- 工具全部集中在单文件中，可读性和扩展性较差。

**教训：**

- Prompt 设计应尽早结合目标监控环境（Prometheus + Loki 的具体约束）。
- 工具设计应考虑后续扩展，一开始就宜按单责任原则拆分。

---

## 3. v0.2：接入 Prometheus 指标查询

### 3.1 功能

- 在三个服务中新增 `prometheus_query_range` 工具：
  - 统一封装 `/api/v1/query_range` 请求。
  - 返回结构化的时间序列数据（metric + values）。

### 3.2 缺陷 1：时间解析失败导致 500

**现象：**

- Predict 服务在调用 `prometheus_query_range` 时，偶发 `ValueError: Invalid isoformat string`。
- 由于异常未捕获，FastAPI 返回 HTTP 500，前端只看到“内部服务器错误”。

**根因：**

- 工具内部直接调用 `datetime.fromisoformat()` 强制解析 Agent 提供的时间字符串。
- 当 LLM 生成的时间格式不符合严格 ISO8601 要求（例如缺少时区、带多余字符）时会抛异常。

**修复方案：**

- 在 `prometheus_query_range` 中增加两层保护：
  1. 时间解析 `try/except`：
     - 若解析失败，返回 `{"error": "invalid_datetime", "message": "...", "start_raw": "...", "end_raw": "..."}`。
  2. HTTP 请求 `try/except`：
     - 若调用 Prometheus 失败或返回错误状态码，返回 `{"error": "prometheus_request_failed", ...}`。

**启示与成长：**

- 在“LLM 参与输入构造”的场景中，必须假设输入是不可信的，工具实现要具备强健的错误防护。
- 工具向 Agent 返回结构化错误信息比直接抛异常更利于 LLM 自行调整策略并向用户给出合理解释。

---

## 4. v0.3：工具拆分与结构化

### 4.1 功能

- 将原先“多个工具堆在同一个文件”的实现拆分为“一个工具一个文件”，例如：
  - `trace_note.py`
  - `loki_query_range_lines.py`
  - `prometheus_query_range.py`
  - `rca_collect_evidence.py`
  - `predict_collect_features.py`
- 在 `tools/__init__.py` 中集中构建工具列表：
  - 使用工厂函数注入 `LokiClient` 等依赖。

### 4.2 教训

- 单文件多工具在初期开发阶段看似方便，但很快会变成“长文件难以维护”的负担。
- 提前引入“工具工厂 + 聚合构建”的模式，可以在不破坏业务逻辑的前提下灵活扩展。

---

## 5. v0.4：命名统一（ai-log-agent → aegis）

### 5.1 变更内容

- 将 K8s 中所有 `ai-log-agent` 命名统一替换为 `aegis`，包括：
  - Namespace
  - ConfigMap / Secret 名称
  - Service / Deployment 名称
- 保证引用链一致（如环境变量引用的 ConfigMap/Secret 名称）。

### 5.2 教训

- 项目命名应尽早确定并保持一致，后期统一命名需要格外仔细检查引用关系。
- 使用搜索工具全局扫描关键字是必要手段，但仍需要人工复核关键资源（如 k8s 清单）。

---

## 6. v0.5：针对 Todo_List 的 Prompt 与 Predict 升级

### 6.1 Prompt 优化

**改动点：**

- ChatOps / RCA / Predict 三个服务的系统 Prompt 全面升级：
  - 增加 Todo_List 环境信息（user-service、todo-service、ai-service）。
  - 显式列出可用指标族（http_requests_total、user_login_*、mysql_up 等）。
  - 强调 Loki 标签使用约束：只能在选择器中使用 `namespace、app、pod、container、job、node_name、filename、stream` 等。
  - 强化“先看 Prometheus，再看 Loki”的分析流程。
  - 规定所有工具调用前必须先调用 `trace_note` 记录计划。

**收益：**

- Agent 的行为更贴合真实监控环境，大幅减少“臆造指标名/标签”的情况。
- Trace 中的工具调用序列更清晰，便于回溯和 UI 展示。

### 6.2 Predict 从脚本式到 LLM 主导

**问题：**

- 早期 Predict 的风险分完全由 `_risk_from_counts`（基于错误计数序列的规则函数）计算，
  大模型只负责输出文本说明，整体更像一个脚本工具而非智能 Agent。

**改动：**

1. 扩展 `LikelyFailures` 模型，增加：
   - `risk_score: float | None`
   - `risk_level: str | None`
2. Prompt 要求 LLM 直接输出包含 `risk_score` 与 `risk_level` 的 JSON。
3. 后端逻辑：
   - 优先采用 LLM 给出的 `risk_score` / `risk_level`；
   - 如为空或解析失败，再用 `_risk_from_counts` 和 `_risk_level` 兜底。

**启示：**

- 在“判断型”任务上应充分让大模型发挥主观推理能力，传统规则更多作为安全网而非核心逻辑。
- 将 LLM 输出约束为结构化 JSON，有利于前端展示与后续自动化处理。

---

## 7. v0.6：Prompt 花括号与时间解析缺陷修复

### 7.1 缺陷 2：Prompt 花括号导致 KeyError（ChatOps / RCA）

**现象：**

- ChatOps 和 RCA 服务在调用 Agent 时抛出：

  ```text
  KeyError: Input to ChatPromptTemplate is missing variables {'service="xxx"'}
  ```

**根因：**

- 在系统 Prompt 中写了：

  ```text
  禁止写成 {service="xxx"}。
  ```

- 由于 LangChain 的 `ChatPromptTemplate` 使用 `{...}` 表示变量，
  这段文字被误解析为一个名为 `service="xxx"` 的变量占位符，而调用时未提供该变量。

**修复：**

- 将相关字符串改为使用双大括号转义：

  ```text
  禁止写成 {{service="xxx"}}。
  ```

**启示：**

- 使用模版引擎（如 Jinja、LangChain PromptTemplate）时，要避免在文案中直接使用单大括号。
- 对包含 `{`、`}` 的例子，统一使用 `{{`、`}}` 转义。

### 7.2 缺陷 3：Prometheus 时间解析异常未捕获（Predict / ChatOps / RCA）

**现象：**

- Predict 服务出现 `ValueError: Invalid isoformat string`，导致 HTTP 500。
- 原因同 v0.2 所述，但此时已确认该问题在三服务中均可能出现。

**修复：**

- 为所有服务的 `prometheus_query_range` 工具统一增加时间解析与 HTTP 调用的 `try/except` 包装，
  返回结构化错误对象而不是直接抛异常。

**启示：**

- 公共工具应在多个服务中保持一致的鲁棒性策略。
- 统一改造公共工具时，要检查所有调用点，而不仅是当前暴露问题的服务。

---

## 8. 总体经验总结

1. **Prompt 与模板引擎的交互要小心**
   - 系统 Prompt 中的示例语句需要考虑到模板引擎的占位符规则。
   - 在需求阶段就应该约定“如需展示 `{}` 示例，一律使用 `{{}}`”。

2. **LLM 输入输出不可信，工具要足够防御**
   - 时间字符串、PromQL/LogQL 片段都可能由 LLM 生成，应视作“不可信输入”处理。
   - 工具函数要使用结构化错误返回，避免抛异常导致整个接口失败。

3. **结构化输出优于纯文本**
   - 无论是 RCA 还是 Predict，统一让大模型输出 JSON 对象极大简化了后端与前端逻辑。
   - 结构化字段便于做二次加工（可视化、报表、导出）。

4. **日志与 Trace 设计要在一开始考虑**
   - `trace_note` 与 `TraceStep` 的存在，使得调试 Agent 行为、解释模型决策变得可行。
   - 这对后续迭代 Prompt、分析问题非常关键。

5. **命名与资源管理要统一**
233→   - 从 `ai-log-agent` 统一到 `aegis` 的过程提示我们，项目命名应尽早统一，避免后期大规模重命名。
234→
235→未来如果继续演进 Aegis，建议在每次版本迭代时同步更新本文件，保持“事件 → 原因 → 修复 → 启示”的闭环记录。

---

## 9. v0.7：流式输出改造与短时间窗口优化

### 9.1 功能：三服务流式输出与前端内心独白

- ChatOps / RCA / Predict 三个服务的 LLM 封装统一改为支持 `streaming` 参数：
  - 使用 LangChain 的 `ChatOpenAI(streaming=True)` 以及 `AsyncCallbackHandler`。
  - 通过 `extra_body={"reasoning_effort": "high"}` 打开模型的推理模式。
- 为 ChatOps / RCA / Predict 分别新增流式接口：
  - ChatOps：`POST /api/chatops/query/stream`（原有，作为统一规范的参考）。
  - RCA：`POST /api/rca/analyze/stream`。
  - Predict：`POST /api/predict/run/stream`。
- 统一采用 NDJSON 协议进行前后端流式通信：
  - 事件类型包括：`start`、`llm_token`、`agent_action`、`tool_start`、`tool_end`、`final`、`end`。
  - `final` 事件返回完整业务结构（ChatOps 的 answer / used_logql，RCA 的 summary / evidence 等，Predict 的 risk_score / risk_level 等）。
- 前端三个页面中：
  - ChatOps：展示“内心独白（LLM 原始推理流）”与 ReAct 工具调用步骤（Trace 面板）。
  - RCA：新增流式展示 RCA 报告生成过程与内心独白，实时渲染工具调用轨迹。
  - Predict：在“未来风险预测”场景中展示流式推理过程，保留高风险场景的红色视觉提示。

### 9.2 功能：健康检查与时间窗口优化

- K8s 健康检查：
  - 将 ChatOps / RCA / Predict 三个服务的 `readinessProbe` 周期从 10 秒统一调整为 60 秒。
  - 目的：减少 `/healthz` 请求在 Loki 中造成的大量日志噪音，同时保持 Pod 就绪探针的行为不变。
- 三个服务的访问日志优化：
  - 在 ChatOps / RCA / Predict 三个服务中，为 `uvicorn.access` 日志增加 `_HealthzAccessFilter` 过滤器。
  - 过滤规则：凡是访问路径包含 `/healthz` 的请求一律不写入访问日志，从源头降低健康检查对 Loki 的干扰。
- 前端时间窗口预设优化：
  - ChatOps：
    - 将时间范围选择从“15/30/60 分钟、6 小时”扩展为：
      - 5 / 10 / 15 / 20 / 25 / 30 / 60 分钟，以及 6 小时。
    - 方便在日志保留时间较短的测试集群中进行更精细的短时查询。
  - Predict：
    - 在遵守后端 `lookback_hours >= 1` 约束的前提下，增加更短的整点窗口：
      - 1 / 2 / 4 / 6 / 24 小时，以及 3 / 7 天。
    - 默认回看窗口从 24 小时调整为 6 小时，更偏向近期风险分析。

### 9.3 功能：Prompt 与监控查询手册对齐

- 对照 `docs/monitoring_queries_agent.md`，检查 ChatOps / RCA / Predict 三个服务的系统 Prompt：
  - 确保统一强调：
  - PromQL 只能基于真实存在的指标名，不允许臆造。
  - Loki 选择器仅使用 Kubernetes 原生标签（`namespace、app、pod、container、job、node_name、filename、stream`），业务字段如 `service=`、`level=` 必须用 `|=` 或 `|~` 文本过滤。
  - 分析流程遵循“先 Prometheus 做宏观判断，再 Loki 看错误日志细节”的原则。
  - 查询不到数据或指标不存在时，必须如实说明环境限制，禁止编造结果。
- 在 RCA 服务的 Prompt 中新增明确说明：
  - `使用 Prometheus 时…不能凭空臆造不存在的指标。`
  - `使用 Prometheus 或 Loki 查询不到数据时，必须如实说明当前环境未暴露对应指标或缺少相关日志，禁止编造查询结果。`

- Predict 时间窗口与 Prometheus 查询约束修复：
  - 为 Predict 服务的 `prometheus_query_range` 新增相对时间语法支持：当 `start_iso` 为 `LOOKBACK_{N}_HOURS_START` 时，后端自动将时间窗口解析为“当前时间往前 N 小时”，避免 Agent 使用示例日期（如 2024-05-20）导致回看范围与实际时间不符。
  - 在 Predict 的系统 Prompt 中明确约定：调用 `prometheus_query_range` 时禁止自行填写具体日期时间，必须使用 `LOOKBACK_{lookback_hours}_HOURS_START` 占位符，让后端根据用户选择的回看小时数计算真实时间范围。
  - 调整 `predict_collect_features` 的返回结构，将 `logql` 字段改为直接返回标准 LogQL 字符串，方便在前端 Trace 中直观展示并复制到 Loki 控制台执行。

### 9.5 功能：前端临时存储与交互体验优化

- ChatOps 页面：
  - 通过浏览器 `localStorage` 持久化“问题文本”和“时间范围选择（lastMinutes）”。
  - 切换到 RCA / Predict 再切回时，自动恢复上一次输入内容和时间范围。
- RCA 页面：
  - 持久化“故障描述”“开始时间”“结束时间”，避免在多次尝试不同分析策略时频繁重复输入。
- Predict 页面：
  - 持久化“服务名”和“回看小时数”，便于对同一服务进行多轮风险预测与对比。
- 统一约定：
  - 所有临时存储均使用当前浏览器的 `localStorage`，仅在本地生效，不涉及服务端状态或隐私上传。

### 9.4 启示与后续约定

- 流式输出对调试与用户体验的价值：
  - 开发阶段可以通过“内心独白 + Trace”快速理解 Agent 的工具调用路径和推理过程，有助于迭代 Prompt 与工具设计。
  - 用户侧可以感知到实时思考过程，明显优于一次性返回的大段文本。
- 健康检查与日志噪音的平衡：
  - 就绪探针频率过高会在 Loki 中产生大量无意义日志，应根据场景调整探针周期。
  - 业务日志与运维日志需要在“稳定性监控”和“可观测性噪音”之间找到平衡点。
- 版本演进过程中的文档同步：
  - 从 v0.7 开始，每次对三服务、前端或公共工具做出非 trivial 变更时，都应同步更新本迭代表，说明：
    - 变更点（功能/缺陷修复）。
    - 根因与修复方式（如果是缺陷）。
    - 对后续设计的启示。

---

## 10. v0.8：Agent 可视化重构与 Predict 稳定性修复

### 10.1 缺陷 4：Predict 流式接口在部分请求下卡住

**现象：**

- `POST /api/predict/run/stream` 在部分复杂问题下会长时间无响应，浏览器端看起来“卡死”。
- 后端无明显报错日志，只能看到流式连接一直占用，无法快速定位哪里卡住。

**根因：**

- Predict 所用豆包大模型开启了 `reasoning_effort="high"` 的推理模式，单次推理成本和延迟显著上升。
- Agent 执行缺乏硬性边界：
  - `AgentExecutor` 未设置 `max_iterations`，在极端情况下可能在 ReAct 循环里“兜圈子”。
  - 流式接口外层没有统一的超时控制，一旦某次调用卡住，请求就会一直挂起。
- 日志中缺乏对单次 Predict 调用内部步骤的结构化记录，难以通过日志还原 Agent 的具体行为。

**修复方案：**

1. 降低 Predict LLM 的推理强度：
   - 在 `services/predict-service/app/llm.py` 中，将豆包大模型的 `extra_body` 参数从高推理模式调整为：
     - `extra_body={"reasoning_effort": "low"}`。
   - 保证在 Predict 场景下优先满足“响应稳定、时延可控”，再在 Prompt 上约束其推理质量。
2. 为 Agent 执行增加硬边界：
   - 在 `services/predict-service/app/agent/executor.py` 中创建 `AgentExecutor` 时显式传入：
     - `max_iterations=8`。
   - 避免 LLM 在工具调用环中反复试探导致无上限迭代。
3. 为流式接口增加统一超时与日志：
   - 在 `services/predict-service/app/main.py` 中：
     - 使用 `asyncio.wait_for(...)` 为流式推理增加统一超时（如 120 秒），超时后主动结束本次会话并返回错误事件。
     - 在 `_run_predict` 等内部协程中补充结构化日志，记录：
       - 预测请求的关键参数（服务名、时间窗口等）。
       - 每一步 Agent 调用的工具名与简要结果（或失败原因）。

**启示：**

- 面向生产 SRE 场景时，LLM 的“推理能力”不能无限拔高，必须在模型层、Agent 层与接口层分别设置边界（tokens、迭代次数、超时时间）。
- 对于“看起来只是卡住”的问题，统一的超时策略 + 结构化日志是排障的第一层安全网。

### 10.2 功能：Agent 可视化重构与操作流时间轴

**改动点：**

- 后端统一重构三套服务的 Agent 流式回调，实现类似 TRAE IDE 的工作流可视化：
  - 在 ChatOps / RCA / Predict 服务中，引入带会话上下文的流式回调处理器：
    - 每个请求生成独立的 `session_id`。
    - 内部维护自增的 `step_id` 与 `workflow_stage`（如 `thinking` / `planning` / `executing` / `observing`）。
  - 通过 NDJSON 流或 WebSocket，将结构化事件实时推送给前端，事件统一包含：
    - `event` / `event_type`：事件类型（如 `llm_token`、`agent_action`、`tool_start`、`tool_end`、`final` 等）。
    - `workflow_stage`：当前步骤所属阶段，便于 UI 做分段展示。
    - `step_id`：将同一次“思考 → 计划 → 执行 → 观察”的若干事件归为同一个步骤。
    - `session_id` / `timestamp`：用于跨服务、跨组件追踪同一次分析会话。
- 前端为三大页面补齐统一的“操作流时间轴”组件：
  - ChatOps 页面：
    - 新增 `AgentTimeline` 组件，将流式事件按 `step_id` 归组并按时间排序。
    - 通过颜色区分不同 `workflow_stage`，直观展示 Agent 从“思考”到“执行工具”的完整路径。
  - RCA 页面：
    - 在 RCA 报告与 Trace 面板之间插入时间轴，展示每一步“收集证据 → 形成假设 → 验证”的过程。
    - 与后端 `RCAStreamHandler` 输出的阶段信息对齐。
  - Predict 页面：
    - 为风险预测过程增加时间轴，展示模型如何逐步收集指标、组合信号并给出最终风险等级。
    - 便于在高风险结论出现时，快速回溯其依据的指标与查询路径。

**启示：**

- Agent 系统的“可观测性”不只是日志与 Trace，还包括对 LLM 推理过程的结构化可视化：
  - 统一事件 schema（`session_id` / `step_id` / `workflow_stage`）有利于前端构建通用的可视化组件。
  - 从一开始就设计好“可视化友好”的回调协议，可以大幅降低后续排障和用户心智成本。
- 将 ChatOps / RCA / Predict 三个场景的可视化能力统一之后：
  - Prompt / 工具 / 流程差异被清晰暴露在时间轴与 Trace 中，便于后续针对性优化。
  - 文档、演示与团队培训时，可以直接拿时间轴作为“Agent 行为说明书”，降低理解门槛。
