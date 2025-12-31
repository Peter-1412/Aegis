<div align="center">

# Aegis —— Todo_List 项目的智能运维助手

面向 SRE / 运维工程师的 AI 运维平台，基于 Prometheus + Loki + 大模型，实现
即时运维问答（ChatOps）、故障根因分析（RCA）与故障风险预测（Predict）。

</div>

---

## 1. 项目简介

Aegis 是一个为 Kubernetes 上的 Todo_List 应用量身打造的智能运维助手，核心目标：

- 只依赖 **Prometheus 指标** 与 **Loki 日志**，不侵入业务代码逻辑
- 通过大模型代理（Agent）自动调用监控数据源，完成排查与分析
- 为运维工程师提供统一的 Web 界面，一站式使用 ChatOps / RCA / 预测能力

当前支持的三大核心能力：

1. **ChatOps**：自然语言提问（如“最近 30 分钟 ai-service 是否有 5xx 峰值？”），
   Agent 自动生成 PromQL / LogQL 查询并综合给出结论与操作建议。
2. **RCA（Root Cause Analysis）**：针对一次已发生的故障，收集多服务错误日志和指标，
   输出结构化的根因分析报告及可执行的修复建议。
3. **Predict**：结合历史错误日志与关键指标，评估某服务未来一段时间内的故障风险及可能故障类型。

监控目标系统为：

- `d:\Code\Python_Study\Todo_List` 项目（后文简称 Todo_List），该项目已接入 Prometheus 与 Loki。

---

## 2. 主要特性

- 🔍 **多源观测数据融合**
  - 指标：Prometheus（HTTP、业务、资源、MySQL、节点等）
  - 日志：Loki（来自 Promtail 收集的 Kubernetes 日志）

- 🧠 **LLM 驱动的智能 Agent**
  - 基于 LangChain Agent + 工具（Tools）系统
  - 自动规划 PromQL / LogQL 查询、执行调用、解释结果
  - 保留每一步工具调用轨迹，方便回溯与审计

- 🧭 **主题化三大服务**
  - ChatOps Service：日常运维问答
  - RCA Service：面向事故的根因分析
  - Predict Service：面向未来的风险研判

- 💻 **统一前端控制台**
  - 基于 React + Vite 实现
  - 提供 ChatOps / RCA / Predict 三个页面
  - 可查看 Agent 生成的 LogQL / 工具调用轨迹

- ☁️ **Kubernetes 原生部署**
  - 提供完整的 `k8s/` 部署清单（Namespace、ConfigMap、Secret、三套后端服务和前端）
  - 默认对接集群内的 Loki 与 Prometheus。

---

## 3. 目录结构

```text
Aegis/
├── frontend/                 # 前端 Web 控制台（React + Vite）
├── services/
│   ├── chatops-service/      # ChatOps 微服务（FastAPI + LangChain Agent）
│   ├── rca-service/          # RCA 微服务
│   └── predict-service/      # Predict 微服务
├── k8s/                      # Kubernetes 部署清单
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   ├── chatops-service.yaml
│   ├── rca-service.yaml
│   ├── predict-service.yaml
│   └── frontend.yaml
└── docs/                     # 文档（接口、PRD、架构、迭代、使用手册等）
```

各服务内部结构高度一致：

- `app/main.py`：FastAPI 入口与 HTTP 接口定义
- `app/agent/executor.py`：构造 LangChain AgentExecutor 与系统 Prompt
- `app/tools/`：各个工具（Loki / Prometheus / 业务工具）
- `app/models.py`：请求 / 响应 / 中间结构模型
- `app/memory/`：会话记忆（基于 ConversationBufferMemory）
- `app/settings.py`：配置（Loki / Prometheus / LLM / 业务参数）

---

## 4. 组件说明

### 4.1 前端（frontend）

- 技术栈：React + Vite
- 主要页面：
  - `ChatOpsPage.jsx`：ChatOps 交互页面
  - `RCAPage.jsx`：根因分析界面
  - `PredictPage.jsx`：风险预测界面
- 通过 `frontend/src/api.js` 与后端三个服务进行交互。

### 4.2 ChatOps Service

- 技术栈：FastAPI + LangChain Agent
- 核心文件：`services/chatops-service/app/`
- 主要接口：
  - `GET /healthz`：健康检查
  - `POST /api/chatops/query`：运维问答入口
- Agent 工具：
  - `trace_note`：记录本轮计划与原因
  - `loki_query_range_lines`：按时间范围查询 Loki 日志行
  - `prometheus_query_range`：查询 Prometheus 指标时间序列

### 4.3 RCA Service

- 技术栈：FastAPI + LangChain Agent
- 核心文件：`services/rca-service/app/`
- 主要接口：
  - `GET /healthz`
  - `POST /api/rca/analyze`：根因分析入口
- Agent 工具：
  - `trace_note`
  - `rca_collect_evidence`：批量收集错误/异常日志证据
  - `prometheus_query_range`

### 4.4 Predict Service

- 技术栈：FastAPI + LangChain Agent
- 核心文件：`services/predict-service/app/`
- 主要接口：
  - `GET /healthz`
  - `POST /api/predict/run`：风险预测入口
- Agent 工具：
  - `trace_note`
  - `predict_collect_features`：为预测聚合错误日志计数序列与日志样本
  - `prometheus_query_range`

---

## 5. 快速开始

### 5.1 先决条件

- 已部署的 Kubernetes 集群，并且：
  - 已安装 Loki（及 Promtail）并采集 Todo_List 项目的日志
  - 已安装 Prometheus，并采集 Todo_List 服务、节点、MySQL 等指标
- 部署 Todo_List 项目，并确保：
  - 指标按 `docs/monitoring_queries_agent.md` 中约定暴露
  - 日志包含必要的业务字段（如 `service=...`）
- 可用的 LLM 接入（当前示例为火山方舟 Ark 模型）

### 5.2 本地构建与运行（示意）

1. 安装后端服务依赖（以 ChatOps 为例）：

   ```bash
   cd services/chatops-service
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8001
   ```

2. 启动其它服务：

   ```bash
   cd services/rca-service
   uvicorn app.main:app --reload --port 8002

   cd services/predict-service
   uvicorn app.main:app --reload --port 8003
   ```

3. 启动前端：

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

> 具体端口、环境变量、Loki/Prometheus 地址可通过 `settings.py` 与 `k8s/configmap.yaml` 调整。

### 5.3 Kubernetes 部署

1. 创建命名空间与配置：

   ```bash
   kubectl apply -f k8s/namespace.yaml
   kubectl apply -f k8s/configmap.yaml
   kubectl apply -f k8s/secret.yaml
   ```

2. 部署三个后端服务与前端：

   ```bash
   kubectl apply -f k8s/chatops-service.yaml
   kubectl apply -f k8s/rca-service.yaml
   kubectl apply -f k8s/predict-service.yaml
   kubectl apply -f k8s/frontend.yaml
   ```

3. 通过 Ingress / NodePort 等方式访问前端，开始使用 Aegis。

---

## 6. 接口概览

详细接口定义见 [`docs/api.md`](docs/api.md)，这里只给出一览表：

| 服务              | 方法 | 路径                  | 说明           |
|-------------------|------|-----------------------|----------------|
| ChatOps Service   | GET  | `/healthz`            | 健康检查       |
| ChatOps Service   | POST | `/api/chatops/query`  | ChatOps 问答   |
| RCA Service       | GET  | `/healthz`            | 健康检查       |
| RCA Service       | POST | `/api/rca/analyze`    | 根因分析       |
| Predict Service   | GET  | `/healthz`            | 健康检查       |
| Predict Service   | POST | `/api/predict/run`    | 风险预测       |

---

## 7. 更多文档

- 接口文档：[`docs/api.md`](docs/api.md)
- PRD 文档：[`docs/prd.md`](docs/prd.md)
- 系统技术架构：[`docs/architecture.md`](docs/architecture.md)
- 迭代与缺陷总结：[`docs/iterations.md`](docs/iterations.md)
- 产品使用手册（面向运维）：[`docs/user-manual.md`](docs/user-manual.md)

---

## 8. 贡献与规划

未来可考虑的方向：

- 支持更多监控后端（如 Tempo / Jaeger / OpenSearch）
- 支持多租户与权限控制
- 支持更多业务项目的多集群接入与隔离

目前仓库尚未开放公共贡献流程，如需协作或定制化开发，可在内部沟通渠道中联系项目负责人。

