# Agent 执行流程实时可视化方案

## 1. 方案概述

本方案旨在实现类似 TRAE IDE 的 Agent 执行流程实时可视化功能，无需修改 Aegis 现有代码。通过增强当前的回调机制和前端展示能力，实现对 Agent 思考过程、工具调用和执行结果的实时可视化展示。

## 2. 核心需求分析

### 2.1 现有功能评估

Aegis 项目已经具备以下相关功能：
- 基于 LangChain 的 Agent 执行框架
- 流式输出接口 (`/api/chatops/query/stream`)
- 基本的回调机制 (`ChatOpsStreamHandler`)
- 中间步骤记录和跟踪功能
- `trace_note` 工具用于记录思考过程

### 2.2 缺失功能

与 TRAE IDE 相比，缺少的核心功能包括：
- 实时可视化的操作流界面
- 时间轴式的执行步骤展示
- 工具调用详情的展开/折叠
- 思考过程与执行结果的关联展示
- 执行状态的实时更新

## 3. 架构设计（参考TRAE IDE架构）

### 3.1 TRAE IDE架构核心特点

根据TRAE IDE的架构图，我们可以提炼出以下核心特点：

1. **核心模块结构**：
   - 任务管理模块
   - 工具管理模块
   - 用户交互层
   - 核心功能层（规划/工具调用/上下文管理/执行）

2. **Workflow流程（1.0版本）**：
   - 思考 → 规划 → 执行 → 观察

3. **Agentic模式（2.0版本）**：
   - 增强LLM的自主性
   - 主动理解需求、感知环境
   - 驱动工具执行获取反馈
   - 从大模型调用输出LLM的能力

### 3.2 Aegis适配TRAE IDE的架构设计

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Aegis 前端应用                               │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │
│  │   聊天界面      │  │   操作流面板    │  │   工具调用详情面板   │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                         时间轴展示层                           │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐         │  │
│  │  │  思考    │ │  规划    │ │  执行    │ │  观察    │         │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘         │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                               │  WebSocket
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Aegis 后端服务                               │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │
│  │   现有 API      │  │   流处理器      │  │   回调增强层        │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                     Agent Trace 模块                          │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐         │  │
│  │  │  思考记录  │ │  规划记录  │ │  执行记录  │ │  观察记录  │         │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘         │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        LangChain Agent                              │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │
│  │   任务管理      │  │   工具管理      │  │   上下文管理        │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.3 关键组件

#### 3.3.1 回调增强层（TRAE IDE核心功能适配）

- **功能**：拦截和增强现有回调事件，适配TRAE IDE的Workflow流程
- **实现方式**：创建独立的回调处理器，与现有 `ChatOpsStreamHandler` 并行工作
- **事件类型**（对应TRAE IDE的Workflow阶段）：
  - **思考阶段**：
    - `llm_start`/`llm_end`：LLM 调用开始/结束
    - `llm_token`：LLM 生成的令牌
  - **规划阶段**：
    - `agent_thought`：Agent 的思考过程（对应TRAE IDE的"规划"模块）
    - `trace_note`：思考过程记录
  - **执行阶段**：
    - `agent_action`：Agent 动作决策
    - `tool_start`/`tool_end`：工具调用开始/结束
  - **观察阶段**：
    - `agent_observation`：Agent 对工具执行结果的观察
    - `llm_result`：LLM 最终结果

#### 3.3.2 实时通信层

- **协议选择**：WebSocket（双向通信，支持TRAE IDE的实时交互模式）
- **消息格式**：JSON 格式，包含事件类型、时间戳、数据内容、Workflow阶段
- **消息类型**：
  ```json
  {
    "event_id": "uuid",
    "event_type": "llm_token",
    "workflow_stage": "thinking",  // thinking/planning/executing/observing
    "timestamp": "2023-10-01T10:00:00Z",
    "data": {
      "token": "你",
      "step_id": "step-1",
      "agent_id": "chatops-agent"
    }
  }
  ```

#### 3.3.3 前端可视化层（TRAE IDE界面风格）

- **组件结构**：
  - 时间轴组件：按TRAE IDE的Workflow阶段展示执行步骤
  - 操作流面板：显示Agent的思考→规划→执行→观察完整流程
  - 详情面板：展示选中步骤的详细信息（参考TRAE IDE的详情展示）
  - 阶段指示器：清晰标记当前所处的Workflow阶段

- **可视化效果**（参考TRAE IDE）：
  - 不同Workflow阶段使用不同颜色标识：
    - 思考阶段：蓝色
    - 规划阶段：紫色
    - 执行阶段：绿色
    - 观察阶段：橙色
  - 支持步骤的展开/折叠
  - 实时更新执行状态和进度
  - 显示执行耗时和Agent状态
  - 工具调用卡片式展示（类似TRAE IDE的工具调用界面）

## 4. 实现方案

### 4.1 后端实现（无需修改现有代码）

#### 4.1.1 回调处理器扩展（适配TRAE IDE的Workflow）

创建一个新的回调处理器类 `AgentTraceVisualizationHandler`，继承自 `AsyncCallbackHandler`，实现对TRAE IDE Workflow所有关键事件的捕获和增强。

```python
class AgentTraceVisualizationHandler(AsyncCallbackHandler):
    def __init__(self, websocket):
        self.websocket = websocket
        self.session_id = str(uuid.uuid4())
        self.step_id_counter = 0
        self.current_workflow_stage = "thinking"
        self.current_step_id = None
        self.agent_actions = []
    
    def _next_step_id(self):
        """生成下一个步骤ID"""
        self.step_id_counter += 1
        return f"step-{self.step_id_counter}"
    
    async def _send_event(self, event_type, data, workflow_stage=None):
        """发送事件到前端"""
        await self.websocket.send_json({
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "workflow_stage": workflow_stage or self.current_workflow_stage,
            "timestamp": datetime.now().isoformat(),
            "session_id": self.session_id,
            "data": data
        })
    
    # ===== 思考阶段事件处理 =====
    async def on_llm_start(self, serialized, prompts, **kwargs):
        """LLM调用开始（思考阶段）"""
        self.current_workflow_stage = "thinking"
        self.current_step_id = self._next_step_id()
        await self._send_event("llm_start", {
            "prompt": prompts[0],
            "step_id": self.current_step_id,
            "model": serialized.get("kwargs", {}).get("model_name", "unknown")
        })
    
    async def on_llm_new_token(self, token, **kwargs):
        """LLM生成令牌（思考阶段）"""
        await self._send_event("llm_token", {
            "token": token,
            "step_id": self.current_step_id
        })
    
    # ===== 规划阶段事件处理 =====
    async def on_agent_thought(self, thought, **kwargs):
        """Agent思考过程（规划阶段）"""
        self.current_workflow_stage = "planning"
        self.current_step_id = self._next_step_id()
        await self._send_event("agent_thought", {
            "thought": thought,
            "step_id": self.current_step_id
        })
    
    # ===== 执行阶段事件处理 =====
    async def on_agent_action(self, action, **kwargs):
        """Agent动作决策（执行阶段）"""
        self.current_workflow_stage = "executing"
        self.current_step_id = self._next_step_id()
        
        # 记录Agent动作
        agent_action = {
            "tool": getattr(action, "tool", "unknown"),
            "tool_input": _stringify(getattr(action, "tool_input", None)),
            "log": str(getattr(action, "log", None)) if getattr(action, "log", None) else None,
            "step_id": self.current_step_id
        }
        self.agent_actions.append(agent_action)
        
        await self._send_event("agent_action", agent_action)
    
    async def on_tool_start(self, serialized, input_str, **kwargs):
        """工具调用开始（执行阶段）"""
        await self._send_event("tool_start", {
            "tool_name": serialized.get("name", "unknown"),
            "input": input_str,
            "step_id": self.current_step_id
        })
    
    # ===== 观察阶段事件处理 =====
    async def on_tool_end(self, output, **kwargs):
        """工具调用结束（观察阶段）"""
        self.current_workflow_stage = "observing"
        await self._send_event("tool_end", {
            "output": output,
            "step_id": self.current_step_id
        })
    
    async def on_agent_observation(self, observation, **kwargs):
        """Agent观察结果（观察阶段）"""
        await self._send_event("agent_observation", {
            "observation": observation,
            "step_id": self.current_step_id
        })
    
    async def on_llm_end(self, response, **kwargs):
        """LLM调用结束（观察/完成阶段）"""
        await self._send_event("llm_end", {
            "response": response.generations[0][0].text if response.generations else "",
            "step_id": self.current_step_id
        })
    
    # ===== 处理 trace_note 工具调用（规划阶段） =====
    async def on_tool_call(self, tool_call, **kwargs):
        """工具调用事件"""
        if getattr(tool_call, "name", "") == "trace_note":
            # trace_note 工具调用属于规划阶段
            self.current_workflow_stage = "planning"
            await self._send_event("trace_note", {
                "note": tool_call.args[0] if tool_call.args else "",
                "step_id": self.current_step_id
            })
    
    # ===== 错误处理 =====
    async def on_error(self, error, **kwargs):
        """错误事件"""
        await self._send_event("error", {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "step_id": self.current_step_id
        })
```

#### 4.1.2 WebSocket 服务（TRAE IDE风格的实时通信）

创建一个新的 WebSocket 端点，用于实时推送执行事件，支持TRAE IDE的实时交互模式：

```python
@app.websocket("/ws/agent-trace/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket端点，用于Agent执行流程的实时可视化"""
    await websocket.accept()
    handler = AgentTraceVisualizationHandler(websocket)
    
    try:
        # 发送初始化事件
        await handler._send_event("session_start", {
            "session_id": session_id,
            "agent_type": "chatops-agent",
            "workflow_stages": ["thinking", "planning", "executing", "observing"]
        })
        
        while True:
            # 接收前端消息（支持双向通信，用于控制可视化）
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # 处理前端控制指令
            if message["type"] == "control":
                if message["action"] == "pause":
                    # 暂停可视化（仅前端暂停，不影响后端执行）
                    pass
                elif message["action"] == "resume":
                    # 恢复可视化
                    pass
                elif message["action"] == "clear":
                    # 清空可视化内容
                    pass
    except WebSocketDisconnect:
        # 清理资源
        await handler._send_event("session_end", {
            "session_id": session_id,
            "reason": "client_disconnected"
        })
    except Exception as e:
        # 记录错误
        logger.error(f"WebSocket error: {e}")
```

#### 4.1.3 流处理器整合（与现有系统无缝集成）

修改 `_run_chatops` 函数的调用方式，添加新的回调处理器，无需修改现有代码：

```python
# 在流处理函数中添加新的回调处理器
async def runner():
    try:
        # 现有流处理器
        stream_handler = ChatOpsStreamHandler(queue)
        
        # 新的可视化回调处理器（连接到WebSocket）
        ws = await websocket_connect(f"ws://localhost:8000/ws/agent-trace/{session_id}")
        ws_handler = AgentTraceVisualizationHandler(ws)
        
        # 将两个处理器都传递给 _run_chatops
        res = await _run_chatops(req, callbacks=[stream_handler, ws_handler])
        
        # 发送最终结果
        await ws_handler._send_event("execution_complete", {
            "result": res,
            "step_id": ws_handler.current_step_id
        })
        
        await ws.close()
    except Exception as exc:
        # 错误处理
        if 'ws_handler' in locals():
            await ws_handler.on_error(exc)
    finally:
        # 清理资源
        await queue.put({"event": "end"})
```

### 4.2 前端实现（TRAE IDE风格）

#### 4.2.1 WebSocket 客户端（支持TRAE IDE的实时交互）

```javascript
class AgentTraceClient {
    constructor(sessionId) {
        this.sessionId = sessionId;
        this.ws = null;
        this.events = [];
        this.stageColors = {
            thinking: '#3498db',      // 蓝色
            planning: '#9b59b6',      // 紫色
            executing: '#2ecc71',     // 绿色
            observing: '#e67e22'      // 橙色
        };
        this.stageLabels = {
            thinking: '思考',
            planning: '规划',
            executing: '执行',
            observing: '观察'
        };
        this.isPaused = false;
        
        this.connect();
    }
    
    connect() {
        // 建立 WebSocket 连接
        this.ws = new WebSocket(`ws://localhost:8000/ws/agent-trace/${this.sessionId}`);
        
        // 监听消息
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleAgentEvent(data);
        };
        
        // 连接打开
        this.ws.onopen = () => {
            console.log('WebSocket connection established');
            this.updateConnectionStatus('connected');
        };
        
        // 连接关闭
        this.ws.onclose = () => {
            console.log('WebSocket connection closed');
            this.updateConnectionStatus('disconnected');
        };
        
        // 连接错误
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.updateConnectionStatus('error');
        };
    }
    
    // 处理不同类型的事件
    handleAgentEvent(event) {
        if (this.isPaused) return;
        
        this.events.push(event);
        
        // 更新当前Workflow阶段指示器
        this.updateStageIndicator(event.workflow_stage);
        
        switch(event.event_type) {
            // ===== 思考阶段 =====
            case 'llm_start':
                this.addLlmStartStep(event);
                break;
            case 'llm_token':
                this.updateLlmOutput(event);
                break;
            
            // ===== 规划阶段 =====
            case 'agent_thought':
                this.addAgentThoughtStep(event);
                break;
            case 'trace_note':
                this.addTraceNoteStep(event);
                break;
            
            // ===== 执行阶段 =====
            case 'agent_action':
                this.addAgentActionStep(event);
                break;
            case 'tool_start':
                this.addToolStartStep(event);
                break;
            
            // ===== 观察阶段 =====
            case 'tool_end':
                this.updateToolResult(event);
                break;
            case 'agent_observation':
                this.addAgentObservationStep(event);
                break;
            case 'llm_end':
                this.addLlmEndStep(event);
                break;
            
            // ===== 会话管理 =====
            case 'session_start':
                this.initializeSession(event);
                break;
            case 'session_end':
                this.endSession(event);
                break;
            
            // ===== 错误处理 =====
            case 'error':
                this.addErrorStep(event);
                break;
        }
    }
    
    // 更新Workflow阶段指示器
    updateStageIndicator(stage) {
        // 移除所有活动状态
        document.querySelectorAll('.stage-indicator').forEach(indicator => {
            indicator.classList.remove('active');
        });
        
        // 添加当前阶段活动状态
        const currentIndicator = document.querySelector(`[data-stage="${stage}"]`);
        if (currentIndicator) {
            currentIndicator.classList.add('active');
        }
    }
    
    // 更新连接状态
    updateConnectionStatus(status) {
        const statusElement = document.getElementById('connection-status');
        statusElement.className = `connection-status ${status}`;
        statusElement.textContent = {
            connected: '已连接',
            disconnected: '已断开',
            error: '连接错误'
        }[status] || '未知状态';
    }
    
    // 控制方法
    pause() {
        this.isPaused = true;
    }
    
    resume() {
        this.isPaused = false;
    }
    
    clear() {
        this.events = [];
        document.getElementById('timeline').innerHTML = '';
    }
    
    // 具体事件处理方法（省略实现细节）
    addLlmStartStep(event) { /* ... */ }
    updateLlmOutput(event) { /* ... */ }
    addAgentThoughtStep(event) { /* ... */ }
    addTraceNoteStep(event) { /* ... */ }
    addAgentActionStep(event) { /* ... */ }
    addToolStartStep(event) { /* ... */ }
    updateToolResult(event) { /* ... */ }
    addAgentObservationStep(event) { /* ... */ }
    addLlmEndStep(event) { /* ... */ }
    initializeSession(event) { /* ... */ }
    endSession(event) { /* ... */ }
    addErrorStep(event) { /* ... */ }
}

// 初始化客户端
const sessionId = 'session-' + Date.now();
const agentTraceClient = new AgentTraceClient(sessionId);
```

#### 4.2.2 可视化组件（TRAE IDE风格）

**Workflow阶段指示器**：
```html
<div class="workflow-stages">
    <div class="stage-indicator" data-stage="thinking">
        <div class="stage-icon">🤔</div>
        <div class="stage-label">思考</div>
    </div>
    <div class="stage-indicator" data-stage="planning">
        <div class="stage-icon">📋</div>
        <div class="stage-label">规划</div>
    </div>
    <div class="stage-indicator" data-stage="executing">
        <div class="stage-icon">⚡</div>
        <div class="stage-label">执行</div>
    </div>
    <div class="stage-indicator" data-stage="observing">
        <div class="stage-icon">👀</div>
        <div class="stage-label">观察</div>
    </div>
</div>
```

**时间轴组件**：
```html
<div class="timeline-container">
    <div class="timeline-header">
        <h3>Agent执行流程</h3>
        <div class="timeline-controls">
            <button id="pause-btn" onclick="agentTraceClient.pause()">暂停</button>
            <button id="resume-btn" onclick="agentTraceClient.resume()">恢复</button>
            <button id="clear-btn" onclick="agentTraceClient.clear()">清空</button>
        </div>
        <div id="connection-status" class="connection-status">连接中...</div>
    </div>
    <div id="timeline" class="timeline"></div>
</div>
```

**时间轴项模板**：
```html
<!-- LLM思考步骤 -->
<div class="timeline-item" data-step-id="{{step_id}}" data-stage="thinking">
    <div class="timeline-marker" style="background-color: {{stage_color}}">
        <span class="marker-icon">🧠</span>
        <span class="marker-label">LLM</span>
    </div>
    <div class="timeline-content">
        <div class="timeline-header">
            <span class="timeline-title">思考：{{title}}</span>
            <span class="timeline-time">{{time}}</span>
        </div>
        <div class="timeline-body">
            <div class="llm-prompt">{{prompt}}</div>
            <div class="llm-output">{{output}}</div>
        </div>
    </div>
</div>

<!-- 工具调用步骤 -->
<div class="timeline-item" data-step-id="{{step_id}}" data-stage="executing">
    <div class="timeline-marker" style="background-color: {{stage_color}}">
        <span class="marker-icon">🔧</span>
        <span class="marker-label">工具</span>
    </div>
    <div class="timeline-content">
        <div class="timeline-header">
            <span class="timeline-title">执行：{{tool_name}}</span>
            <span class="timeline-time">{{time}}</span>
        </div>
        <div class="timeline-body">
            <div class="tool-input">
                <h4>输入参数</h4>
                <pre>{{input}}</pre>
            </div>
            <div class="tool-output">
                <h4>输出结果</h4>
                <pre>{{output}}</pre>
            </div>
        </div>
    </div>
</div>
```

**工具调用详情面板**：
```html
<div class="tool-detail-panel" id="tool-detail-panel">
    <div class="tool-header">
        <h3>工具调用详情</h3>
        <button class="close-btn" onclick="closeToolDetail()">&times;</button>
    </div>
    <div class="tool-content">
        <div class="tool-info">
            <div class="info-item">
                <span class="label">工具名称：</span>
                <span class="value" id="detail-tool-name"></span>
            </div>
            <div class="info-item">
                <span class="label">调用时间：</span>
                <span class="value" id="detail-call-time"></span>
            </div>
            <div class="info-item">
                <span class="label">执行耗时：</span>
                <span class="value" id="detail-execution-time"></span>
            </div>
            <div class="info-item">
                <span class="label">Workflow阶段：</span>
                <span class="value" id="detail-stage"></span>
            </div>
        </div>
        <div class="tool-input">
            <h4>输入参数</h4>
            <pre id="detail-input"></pre>
        </div>
        <div class="tool-output">
            <h4>输出结果</h4>
            <pre id="detail-output"></pre>
        </div>
    </div>
</div>
```

### 4.3 集成方案（TRAE IDE风格）

1. **启动方式**：
   - 前端应用启动时，建立 WebSocket 连接并初始化 TRACE IDE 风格的界面
   - 后端服务启动时，自动加载新的回调处理器和 WebSocket 端点
   - Agent 执行时，自动触发工作流阶段转换和事件推送

2. **配置选项**：
   ```python
   # TRAE IDE 风格可视化功能配置
   TRAE_STYLE_VISUALIZATION_ENABLED = True
   WEBSOCKET_PORT = 8000
   WORKFLOW_STAGES = ["thinking", "planning", "executing", "observing"]
   TRACE_RETENTION_MINUTES = 60
   AGENTIC_MODE_ENABLED = False  # 后续可升级为 True，支持 TRAE IDE 2.0 的 Agentic 模式
   ```

3. **数据存储**：
   - 临时存储执行轨迹数据（内存或 Redis）
   - 可选：持久化存储关键执行轨迹（数据库），支持轨迹回放
   - 按会话 ID 组织轨迹数据，支持多会话并发

## 5. 功能特性（TRAE IDE风格）

### 5.1 实时可视化（Workflow驱动）

- **思考阶段可视化**：逐字显示 LLM 生成的文本，蓝色标识
- **规划阶段可视化**：显示 Agent 的思考过程和决策逻辑，紫色标识
- **执行阶段可视化**：显示工具调用的开始、执行和结果，绿色标识
- **观察阶段可视化**：显示 Agent 对工具执行结果的观察和总结，橙色标识

### 5.2 交互功能（TRAE IDE体验）

- **Workflow 阶段导航**：清晰标记当前所处阶段，支持阶段间快速跳转
- **步骤展开/折叠**：支持展开查看详细信息，折叠节省空间
- **步骤过滤**：按事件类型和 Workflow 阶段过滤
- **时间轴缩放**：支持缩放时间轴，查看不同时间粒度的执行过程
- **详情查看**：点击步骤查看完整的输入输出信息，类似 TRAE IDE 的详情面板
- **实时控制**：支持暂停、恢复、清空可视化内容

### 5.3 性能优化（企业级标准）

- **事件压缩**：合并相似事件，减少网络传输量
- **延迟加载**：仅加载可视区域内的步骤详情
- **内存管理**：定期清理过期的执行轨迹数据
- **连接优化**：WebSocket 心跳机制，自动重连
- **批量处理**：大流量下的事件批量处理

## 6. 部署与集成

### 6.1 部署架构（TRAE IDE分布式风格）

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Kubernetes 集群                             │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │
│  │   ChatOps 服务  │  │   WebSocket 服务│  │   Redis（可选）     │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────────────────────────────┐  │
│  │   任务管理服务  │  │   Agent 核心功能层（规划/工具调用/执行）│  │
│  └─────────────────┘  └─────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        前端应用（Browser）                          │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │
│  │   聊天界面      │  │   操作流面板    │  │   工具调用详情面板   │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                         Workflow 阶段指示器                   │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 环境变量（TRAE IDE兼容）

| 环境变量 | 描述 | 默认值 |
|---------|------|-------|
| `TRAE_STYLE_VISUALIZATION_ENABLED` | 是否启用 TRAE IDE 风格可视化 | `true` |
| `WEBSOCKET_HOST` | WebSocket 服务主机 | `0.0.0.0` |
| `WEBSOCKET_PORT` | WebSocket 服务端口 | `8000` |
| `REDIS_URL` | Redis 连接 URL（可选） | - |
| `TRACE_RETENTION_MINUTES` | 轨迹数据保留时间 | `60` |
| `WORKFLOW_STAGES` | Workflow 阶段配置 | `["thinking", "planning", "executing", "observing"]` |
| `AGENTIC_MODE_ENABLED` | 是否启用 Agentic 模式 | `false` |

## 7. 监控与维护

### 7.1 监控指标（TRAE IDE标准）

- WebSocket 连接数和状态
- 事件处理延迟和吞吐量
- 数据传输量（入/出）
- 错误率和错误类型分布
- Workflow 阶段转换统计
- Agent 执行性能指标

### 7.2 日志记录

- 记录关键事件处理日志（JSON 格式，便于分析）
- 记录连接建立/断开日志
- 记录错误信息和异常堆栈
- 记录 Workflow 阶段转换日志
- 记录 Agent 执行性能日志

### 7.3 常见问题

| 问题 | 可能原因 | 解决方案 |
|-----|---------|--------|
| 实时更新延迟 | 网络延迟或事件过多 | 检查网络连接，优化事件压缩和批量处理 |
| 界面卡顿 | 大量事件同时渲染 | 增加事件过滤、延迟加载和虚拟滚动 |
| 连接断开 | WebSocket 超时或网络不稳定 | 增加心跳机制，优化重连逻辑 |
| 阶段指示器错误 | 事件顺序异常 | 优化事件处理顺序，增加事件校验 |

## 8. 后续扩展（TRAE IDE演进路线）

### 8.1 高级功能（TRAE IDE 2.0特性）

- **Agentic 模式支持**：升级到 TRAE IDE 2.0 的 Agentic 模式，增强 LLM 自主性
- **多 Agent 协同可视化**：支持多个 Agent 之间的交互可视化
- **执行轨迹回放**：支持回放历史执行轨迹，重现执行过程
- **性能分析**：分析执行瓶颈，优化 Agent 性能
- **智能建议**：基于执行轨迹提供优化建议，类似 TRAE IDE 的智能提示

### 8.2 集成扩展（企业级生态）

- 与 Prometheus 集成，显示性能指标和监控数据
- 与 Grafana 集成，展示可视化图表和仪表板
- 与告警系统集成，显示相关告警信息
- 与配置中心集成，支持动态配置更新
- 与服务网格集成，支持服务调用可视化

### 8.3 技术扩展（TRAE IDE技术栈）

- 支持 WebRTC 实时通信，降低延迟
- 支持移动端适配，实现多端一致体验
- 支持高性能渲染引擎，优化大量事件的渲染性能
- 支持 AI 辅助分析，自动识别执行异常和优化点
- 支持插件扩展机制，便于功能扩展

## 9. 总结

本方案通过参考 TRAE IDE 的架构和功能特点，实现了 Aegis 项目的 Agent 执行流程实时可视化功能，无需修改现有代码。方案采用了 TRAE IDE 的 Workflow 流程（思考→规划→执行→观察）和 Agentic 模式理念，提供了丰富的可视化和交互功能，同时考虑了性能优化和部署集成。

方案的核心优势在于：

1. **无侵入性**：无需修改现有代码，通过回调扩展和 WebSocket 服务实现功能增强
2. **TRAE IDE 风格**：完全按照 TRAE IDE 的界面风格和交互体验设计
3. **Workflow 驱动**：基于明确的工作流阶段组织可视化内容
4. **可扩展性**：支持后续升级到 TRAE IDE 2.0 的 Agentic 模式
5. **企业级标准**：考虑了性能、监控、维护等企业级应用需求

通过本方案的实施，Aegis 项目将获得与 TRAE IDE 类似的 Agent 执行流程实时可视化能力，提升用户体验和调试效率，为后续的功能演进奠定基础。

