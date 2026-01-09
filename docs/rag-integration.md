# Aegis 接入 RAG 的整体方案

本文档讨论在现有 Aegis 架构（ChatOps / RCA / Predict 三个 Agent 微服务）之上，如何合理接入基于向量检索的 RAG（Retrieval-Augmented Generation）能力，用于：

- 为 ChatOps 提供监控体系、告警规则、运维手册的「知识库问答」能力；
- 为 RCA/Predict 提供「参考 runbook / 历史事故案例 / 最佳实践」的支撑；
- 为未来扩展（如飞书 Bot、变更评审助手）提供统一的知识底座。

本方案只讨论架构与步骤，不涉及具体代码实现。

## 1. 总体设计思路

### 1.1 是否单独做一个 RAG 微服务？

推荐采用「**独立知识服务 + Agent 工具**」的形式：

- 新增一个轻量级微服务，例如 `knowledge-service`：
  - 暴露 HTTP API：`/api/knowledge/query`、`/api/knowledge/upsert` 等。
  - 内部封装：
    - 文档分片与向量化。
    - 向量数据库查询（向量检索 + 关键字/标签过滤）。
    - 简单的结果重排与去重。
- 在 ChatOps / RCA / Predict 的 Agent 工具集中新增一个工具：
  - 例如 `knowledge_search`：
    - 入参：`question`、`top_k`、可选 `scope`（chatops/rca/predict）。
    - 出参：若干条「文档片段 + 元信息」，供 Agent 参考。

这样有几个好处：

- 知识库构建和 Agent 逻辑解耦，可以独立迭代、扩容。
- 不破坏三套现有服务的结构，仅在工具层增加一个新的 HTTP 工具。
- 未来接入飞书 Bot 或其它前端时，也可以直接对接 `knowledge-service` 做纯问答。

### 1.2 数据从哪里来？

初期可以充分利用现有仓库中已经存在的「高价值文本」：

- 当前仓库中的文档：
  - `docs/` 目录下的各类文档：
    - `architecture.md`：架构说明。
    - `api.md`：接口文档。
    - `monitoring_queries_agent.md`：监控指标与 LogQL/PromQL 约定。
    - `iterations.md`：版本迭代与经验教训。
    - `user-manual.md`：用户使用说明。
    - `enterprise-agent-gap-analysis.md`：与大厂生产级 Agent 的差距分析。
    - 以及新增加的集成方案文档（飞书 Bot、RAG 等）。
- Todo_List 业务系统本身的文档（如果有）：
  - 服务 README、运维手册、发布手册。
- 监控与告警规则：
  - PrometheusRule / Alertmanager 配置。
  - Grafana dashboard 描述（可以先以 JSON/导出的 markdown 形式纳入）。
- 历史事故/变更记录（后续迭代）：
  - SRE 在 Wiki / 工单系统 / 飞书文档里记录的故障复盘与变更评审。

后续可逐步扩展到：

- 业务代码注释与接口说明（如服务内的 README / swagger 文档）。
- 生产环境运维 SOP、Playbook。

### 1.3 需要安装/引入哪些东西？

基础设施建议如下：

- **向量数据库**（二选一或多选一）：
  - 使用已有关系型数据库扩展：
    - 例如 PostgreSQL + `pgvector` 插件。
    - 优点：运维成本低，可与现有应用共用数据库集群。
  - 或采用独立向量存储：
    - 如 Milvus、Qdrant、Weaviate 等。
    - 优点：专用向量检索能力更强，适合规模很大时扩展。
- **Embedding 模型**：
  - 优先考虑与现有 LLM 供应商（如火山方舟 Ark）配套的 Embedding 接口：
    - 例如 `text-embedding` 模型，通过 HTTP API 调用。
  - 或使用开源本地模型（如 BGE / Jina / GTE 系列）：
    - 需要额外部署一个推理服务（例如使用 vLLM / FastAPI 包一层）。
- **文档解析依赖**：
  - Markdown / HTML / PDF 的解析库（LangChain 已有相应 Loader，可直接选型）。
- **定时/离线任务框架**（可选）：
  - 用于定期增量同步 Git 仓库 / Wiki / 配置文件。

整体上，RAG 的基础设施可以与现有 Aegis 微服务并行部署，不需要侵入当前 Loki/Prometheus 体系。

## 2. RAG 能力在 Aegis 中的定位

### 2.1 面向 ChatOps

典型问题：

- 「这个告警规则是什么意思？触发条件是什么？」
- 「`http_request_duration_seconds_bucket` 这个指标怎么理解？」
- 「当 user-service 报 5xx 峰值时，有哪些常见处理步骤？」

RAG 的作用：

- 把 `docs/` 里与指标/告警相关的文档作为知识库；
- ChatOps Agent 在回答问题前，可以调用 `knowledge_search` 工具：
  - 用用户问题构造查询；
  - 检索相关的文档片段；
  - 将片段摘要融合到回答中，给出更准确的解释和建议。

### 2.2 面向 RCA

典型问题：

- 「10:00~10:15 间登录失败，可能原因是什么？」
- 「类似场景以前出现过吗？用了哪些排查手段？」

RAG 的作用：

- 把历史 RCA 报告、故障复盘文档、`iterations.md` 中的经验教训纳入知识库；
- RCA Agent 在拿到当前 Prometheus/Loki 证据后：
  - 调用 `knowledge_search`，带上「故障描述 + 怀疑的服务名」；
  - 检索历史上类似事故的处理经验；
  - 在建议动作中补充「参考以往案例」的经验。

### 2.3 面向 Predict

典型问题：

- 「未来 2 小时 ai-service 风险高吗？如果高，该提前做什么准备？」

RAG 的作用：

- 提供与容量规划、降级策略、熔断配置等相关的文档；
- Predict Agent 在判断高风险时：
  - 调用 `knowledge_search`，检索「ai-service 高风险时建议动作」；
  - 在 explanation 或 suggested_actions 中引用对应建议。

## 3. 知识服务（knowledge-service）设计

### 3.1 API 设计（示意）

建议新增一个 `knowledge-service` 微服务，提供最少两个接口：

- 检索接口：

```http
POST /api/knowledge/query
Content-Type: application/json

{
  "question": "最近 30 分钟 user-service 登录失败率高怎么办？",
  "scope": "rca",        // 可选：chatops / rca / predict / all
  "top_k": 5,            // 返回片段数量
  "filters": {           // 可选
    "service": "user-service"
  }
}
```

返回：

```json
{
  "hits": [
    {
      "id": "doc-123#chunk-5",
      "score": 0.87,
      "source": "docs/monitoring_queries_agent.md",
      "title": "user-service 登录相关指标与日志",
      "snippet": "在 user-service 中，登录失败通常与 user_login_errors_total ...",
      "url": "https://aegis.example.com/docs/monitoring_queries_agent.html#user-login",
      "metadata": {
        "service": "user-service",
        "category": "runbook",
        "scope": "rca"
      }
    }
  ]
}
```

- 文档入库接口（可选）：

```http
POST /api/knowledge/upsert
Content-Type: application/json

{
  "doc_id": "docs/monitoring_queries_agent.md",
  "content": "文件完整内容或增量内容 ...",
  "metadata": {
    "path": "docs/monitoring_queries_agent.md",
    "category": "monitoring",
    "scope": ["chatops", "rca"],
    "service": ["user-service", "todo-service", "ai-service"]
  }
}
```

也可以不对外暴露 upsert 接口，而是在内部通过定时任务直接从 Git 拉取文档进行解析与写入。

### 3.2 内部组件

`knowledge-service` 内部可以拆为三层：

1. **存储层**：
   - 向量表结构（以 PostgreSQL + pgvector 为例）：

     ```sql
     CREATE TABLE knowledge_chunks (
       id TEXT PRIMARY KEY,
       doc_id TEXT NOT NULL,
       chunk_index INT NOT NULL,
       content TEXT NOT NULL,
       embedding VECTOR(1536),  -- 取决于具体 embedding 维度
       metadata JSONB
     );
     CREATE INDEX ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops);
     ```

2. **嵌入层**：
   - 一个封装了 embedding 模型调用的模块：
     - 输入：文本片段（例如 500~800 字符）。
     - 输出：向量数组（float list）。
3. **查询层**：
   - 将用户问题向量化；
   - 执行向量相似度查询 + 关键词过滤；
   - 对结果进行简单重排（可以按得分和 metadata 综合排序）；
   - 返回前端或 Agent 可直接消费的 JSON。

## 4. 与现有 Agent 的集成方式

### 4.1 新增 LangChain Tool：knowledge_search

在 ChatOps / RCA / Predict 各自的 `app/tools/` 中新增一个工具（逻辑相同，只是注册位置不同），示意：

- 工具入参：
  - `question: str`
  - `scope: str | None`
  - `service: str | None`
  - `top_k: int = 5`
- 工具行为：
  - 调用 `knowledge-service /api/knowledge/query`。
  - 返回 `hits` 列表。

在系统 Prompt 中告诉 Agent：

- 什么时候应该调用 `knowledge_search`：
  - 当用户的问题与「指标解释 / 告警含义 / SOP / 历史经验」相关时；
  - 当从 Prometheus/Loki 得到的证据不足以直接得出结论时，可以使用知识库补充背景。
- 如何使用返回结果：
  - 优先引用得分最高的 1~3 条片段；
  - 用自己的话总结，不要大段复制；
  - 在回答中可以注明「参考内部文档：xxx」。

### 4.2 集成位置建议

- ChatOps：
  - 在 `build_tools` 中将 `knowledge_search` 加入工具列表；
  - 在系统 Prompt 中增加一段「知识库使用说明」。
- RCA：
  - 作为辅助工具，仅在 `rca_collect_evidence` 得不到足够证据时调用。
- Predict：
  - 在高风险情况下，调用 `knowledge_search` 获得「风险处置建议」，补充到 `suggested_actions` 中。

这样 RAG 是作为「辅助知识输入」，不会改变现有三个服务的核心职责。

## 5. 文档与数据的初始构建流程

### 5.1 一次性构建

1. 确定初始纳入的文档范围：
   - `docs/` 下所有 `.md` 文件；
   - 业务项目的运维手册；
   - Prometheus/Grafana/Alertmanager 配置（可选）。
2. 编写一个离线脚本（单次执行）：
   - 遍历所有文档文件；
   - 使用 Markdown 解析器将文档按层级分段（按标题或固定长度分块）；
   - 生成 `chunk` 对象：

     ```json
     {
       "id": "docs/api.md#L80-120",
       "doc_id": "docs/api.md",
       "chunk_index": 3,
       "content": "这部分讲的是 ChatOps Service 的 API ...",
       "metadata": {
         "path": "docs/api.md",
         "category": "api",
         "scope": ["chatops"],
         "service": null
       }
     }
     ```

   - 对每个 `content` 调用 embedding 模型，写入向量表。

### 5.2 增量更新

后续可以根据需要增加：

- 定时任务：
  - 每天或每小时扫描 Git 变更（或从 CI 推送变更列表）。
  - 对变更的文档重新切片/向量化。
- 手动触发：
  - 为 SRE/开发提供一个简单 CLI 或 Web 界面，当新写完一篇故障复盘时，手动触发「同步到知识库」。

## 6. 实施步骤总览

1. **确定目标和范围**：
   - 明确 RAG 初期只解决「文档类知识问答」，不尝试直接从日志/指标中做检索。
2. **选型与部署向量存储**：
   - 在现有基础设施中选择 PostgreSQL + pgvector 或 Milvus/Qdrant。
3. **选型 Embedding 模型**：
   - 优先使用现有 LLM 供应商提供的 embedding 接口。
4. **实现 knowledge-service 原型**：
   - 提供 `/api/knowledge/query` 接口；
   - 内部包含分片、向量检索和简单排序逻辑。
5. **编写离线构建脚本**：
   - 基于 `docs/` 目录构建初始知识库。
6. **在 ChatOps / RCA / Predict 中设计 `knowledge_search` 工具**：
   - 先在 Prompt 设计层面规划好调用策略和使用方式；
   - 后续再在代码中增加工具实现与注册。
7. **逐步扩展数据源与使用场景**：
   - 纳入历史 RCA 报告、SOP、变更评审等内容；
   - 在飞书 Bot 场景下直接复用 `knowledge-service`，实现「纯知识问答」。

---

通过上述方案，Aegis 可以在现有「指标 + 日志」基础之上，补上一条「知识维度」的能力：  
让 Agent 不仅能查到“发生了什么”（Logs/Metrics），还能回答“这代表什么含义、以前遇到过类似情况、应该如何处理”（Docs/Runbook/经验）。这一层 RAG 能力可以独立演进，对现有三个 Agent 微服务的侵入度很低。***
