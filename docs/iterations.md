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
   - 从 `ai-log-agent` 统一到 `aegis` 的过程提示我们，项目命名应尽早统一，避免后期大规模重命名。

未来如果继续演进 Aegis，建议在每次版本迭代时同步更新本文件，保持“事件 → 原因 → 修复 → 启示”的闭环记录。

