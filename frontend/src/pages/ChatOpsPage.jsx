import { useEffect, useMemo, useRef, useState } from 'react'
import { chatopsQueryStream } from '../api'

function newSessionId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

const stageColors = {
  thinking: '#3498db',
  planning: '#9b59b6',
  executing: '#2ecc71',
  observing: '#e67e22'
}

const stageLabels = {
  thinking: '思考',
  planning: '规划',
  executing: '执行',
  observing: '观察'
}

function PrettyJson({ text }) {
  if (text === null || text === undefined) return null
  const raw = String(text)
  const trimmed = raw.trim()
  let parsed = null
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      parsed = JSON.parse(trimmed)
    } catch {
      parsed = null
    }
  }
  if (!parsed) {
    return (
      <pre className="mono" style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>
        {raw}
      </pre>
    )
  }
  const isLogLines = typeof parsed === 'object' && parsed !== null && Array.isArray(parsed.lines)
  if (isLogLines) {
    const total = typeof parsed.line_count === 'number' ? parsed.line_count : parsed.lines.length
    const previewCount = 50
    const shown = parsed.lines.slice(0, previewCount)
    return (
      <div style={{ marginTop: 4 }}>
        {parsed.logql ? (
          <>
            <div className="resultTitle" style={{ fontSize: 13 }}>
              LogQL
            </div>
            <div className="mono" style={{ whiteSpace: 'pre-wrap', marginBottom: 6 }}>
              {parsed.logql}
            </div>
          </>
        ) : null}
        <div className="mono" style={{ fontSize: 12, color: 'var(--text-subtle)', marginBottom: 4 }}>
          时间范围：{parsed.start} → {parsed.end} · 行数：{total}
        </div>
        <div
          style={{
            borderRadius: 4,
            border: '1px solid var(--border-subtle)',
            padding: 8,
            maxHeight: 260,
            overflow: 'auto',
            background: 'var(--bg-deep)'
          }}
        >
          {shown.map((line, idx) => (
            <div key={idx} className="mono" style={{ fontSize: 12, whiteSpace: 'pre' }}>
              {line}
            </div>
          ))}
          {parsed.lines.length > previewCount ? (
            <div className="mono" style={{ fontSize: 12, color: 'var(--text-subtle)', marginTop: 4 }}>
              仅展示前 {previewCount} 行，更多可复制 LogQL 到 Loki 查看。
            </div>
          ) : null}
        </div>
        <details style={{ marginTop: 6 }}>
          <summary className="mono" style={{ fontSize: 12, color: 'var(--text-subtle)' }}>
            查看原始 JSON
          </summary>
          <div style={{ marginTop: 4 }}>
            <pre className="mono" style={{ whiteSpace: 'pre', fontSize: 12 }}>
              {JSON.stringify(parsed, null, 2)}
            </pre>
          </div>
        </details>
      </div>
    )
  }
  return (
    <details style={{ marginTop: 4 }}>
      <summary className="mono" style={{ fontSize: 12, color: 'var(--text-subtle)' }}>
        展开结构化结果
      </summary>
      <div style={{ marginTop: 4 }}>
        <pre className="mono" style={{ whiteSpace: 'pre', fontSize: 12 }}>
          {JSON.stringify(parsed, null, 2)}
        </pre>
      </div>
    </details>
  )
}

function AgentTimeline({ events }) {
  const steps = useMemo(() => {
    const byStep = new Map()
    for (const evt of events || []) {
      const stepId = evt.step_id || evt.stepId
      if (!stepId) continue
      if (!byStep.has(stepId)) {
        byStep.set(stepId, {
          id: stepId,
          workflow_stage: evt.workflow_stage || 'thinking',
          events: []
        })
      }
      byStep.get(stepId).events.push(evt)
    }
    const arr = Array.from(byStep.values())
    arr.sort((a, b) => {
      const na = Number(String(a.id).replace('step-', '')) || 0
      const nb = Number(String(b.id).replace('step-', '')) || 0
      return na - nb
    })
    return arr
  }, [events])
  const [activeStepId, setActiveStepId] = useState(null)
  if (!steps.length) return null
  const activeId = steps.some((s) => s.id === activeStepId) ? activeStepId : steps[0].id
  const activeStep = steps.find((s) => s.id === activeId) || steps[0]

  return (
    <div className="result">
      <div className="resultTitle">Agent 执行流程（思考 / 规划 / 执行 / 观察）</div>
      <div style={{ height: 8 }} />
      <div
        style={{
          display: 'flex',
          gap: 8,
          overflowX: 'auto',
          paddingBottom: 8
        }}
      >
        {steps.map((step) => {
          const stage = step.workflow_stage || 'thinking'
          const color = stageColors[stage] || '#7f8c8d'
          const label = stageLabels[stage] || stage
          return (
            <button
              key={step.id}
              type="button"
              onClick={() => setActiveStepId(step.id)}
              style={{
                minWidth: 120,
                borderRadius: 6,
                border: step.id === activeId ? `2px solid ${color}` : '1px solid var(--border-subtle)',
                padding: '6px 10px',
                background: 'var(--bg-elevated)',
                cursor: 'pointer',
                textAlign: 'left'
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  marginBottom: 4
                }}
              >
                <span
                  style={{
                    display: 'inline-block',
                    width: 8,
                    height: 8,
                    borderRadius: 999,
                    backgroundColor: color
                  }}
                />
                <span style={{ fontSize: 12, color: 'var(--text-subtle)' }}>{label}</span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-normal)' }}>
                {step.events.find((e) => e.event_type === 'agent_action')?.tool ||
                  step.events.find((e) => e.event === 'agent_action')?.tool ||
                  step.events.find((e) => e.event_type === 'trace_note')?.note ||
                  step.events.find((e) => e.event_type === 'agent_thought')?.thought ||
                  step.id}
              </div>
            </button>
          )
        })}
      </div>
      {activeStep ? (
        <>
          <div style={{ height: 8 }} />
          <div
            style={{
              borderRadius: 6,
              border: '1px solid var(--border-subtle)',
              padding: 10,
              background: 'var(--bg-elevated)'
            }}
          >
            {activeStep.events.map((e, idx) => {
              const key = `${activeStep.id}-${idx}-${e.event_type || e.event}`
              const ts = e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : ''
              if (e.event_type === 'llm_start' || e.event === 'llm_start') {
                return (
                  <div key={key} style={{ marginBottom: 8 }}>
                    <div className="resultTitle">LLM 调用开始</div>
                    <div className="mono" style={{ fontSize: 12, color: 'var(--text-subtle)' }}>
                      {ts} · 模型：{e.model || '未知'}
                    </div>
                    {e.prompt ? (
                      <pre className="mono" style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>
                        {e.prompt}
                      </pre>
                    ) : null}
                  </div>
                )
              }
              if (e.event_type === 'llm_end' || e.event === 'llm_end') {
                return (
                  <div key={key} style={{ marginBottom: 8 }}>
                    <div className="resultTitle">LLM 输出</div>
                    <div className="mono" style={{ fontSize: 12, color: 'var(--text-subtle)' }}>
                      {ts}
                    </div>
                    {e.response ? (
                      <pre className="mono" style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>
                        {e.response}
                      </pre>
                    ) : null}
                  </div>
                )
              }
              if (e.event_type === 'agent_thought') {
                return (
                  <div key={key} style={{ marginBottom: 8 }}>
                    <div className="resultTitle">Agent 思考</div>
                    <div className="mono" style={{ fontSize: 12, color: 'var(--text-subtle)' }}>
                      {ts}
                    </div>
                    <pre className="mono" style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>
                      {e.thought}
                    </pre>
                  </div>
                )
              }
              if (e.event_type === 'trace_note') {
                return (
                  <div key={key} style={{ marginBottom: 8 }}>
                    <div className="resultTitle">trace_note</div>
                    <pre className="mono" style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>
                      {e.note}
                    </pre>
                  </div>
                )
              }
              if (e.event_type === 'agent_action' || e.event === 'agent_action') {
                return (
                  <div key={key} style={{ marginBottom: 8 }}>
                    <div className="resultTitle">工具决策：{e.tool}</div>
                    {e.tool_input ? (
                      <PrettyJson text={e.tool_input} />
                    ) : null}
                  </div>
                )
              }
              if (e.event_type === 'tool_start' || e.event === 'tool_start') {
                return (
                  <div key={key} style={{ marginBottom: 8 }}>
                    <div className="resultTitle">工具开始：{e.tool}</div>
                    {e.tool_input ? (
                      <PrettyJson text={e.tool_input} />
                    ) : null}
                  </div>
                )
              }
              if (e.event_type === 'tool_end' || e.event === 'tool_end') {
                return (
                  <div key={key} style={{ marginBottom: 8 }}>
                    <div className="resultTitle">工具结果</div>
                    {e.observation ? (
                      <PrettyJson text={e.observation} />
                    ) : null}
                  </div>
                )
              }
              if (e.event_type === 'agent_observation') {
                return (
                  <div key={key} style={{ marginBottom: 8 }}>
                    <div className="resultTitle">Agent 观察</div>
                    {e.observation ? (
                      <pre className="mono" style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>
                        {e.observation}
                      </pre>
                    ) : null}
                  </div>
                )
              }
              if (e.event_type === 'error' || e.event === 'error') {
                return (
                  <div key={key} style={{ marginBottom: 8 }}>
                    <div className="resultTitle" style={{ color: 'var(--danger)' }}>
                      错误
                    </div>
                    <pre className="mono" style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>
                      {e.error_type || ''} {e.error_message || e.message || ''}
                    </pre>
                  </div>
                )
              }
              return null
            })}
          </div>
        </>
      ) : null}
    </div>
  )
}

function TracePanel({ trace }) {
  const steps = trace?.steps || []
  if (!steps.length) return null
  return (
    <div className="result">
      <details>
        <summary className="resultTitle">Agent 全流程（ReAct：思考摘要/行动/观察）</summary>
        <div style={{ height: 10 }} />
        {steps.map((s) => (
          <div key={`${s.index}-${s.tool}`} style={{ marginBottom: 12 }}>
            <div className="row">
              <span className="pill">
                #{s.index} 工具：<span className="mono">{s.tool}</span>
              </span>
            </div>
            {s.tool_input ? (
              <>
                <div style={{ height: 6 }} />
                <div className="resultTitle">输入</div>
                <PrettyJson text={s.tool_input} />
              </>
            ) : null}
            {s.observation ? (
              <>
                <div style={{ height: 6 }} />
                <div className="resultTitle">观察</div>
                <PrettyJson text={s.observation} />
              </>
            ) : null}
          </div>
        ))}
      </details>
    </div>
  )
}

export default function ChatOpsPage() {
  const presets = useMemo(
    () => [
      { label: '最近 5 分钟', minutes: 5 },
      { label: '最近 10 分钟', minutes: 10 },
      { label: '最近 15 分钟', minutes: 15 },
      { label: '最近 20 分钟', minutes: 20 },
      { label: '最近 25 分钟', minutes: 25 },
      { label: '最近 30 分钟', minutes: 30 },
      { label: '最近 60 分钟', minutes: 60 },
      { label: '最近 6 小时', minutes: 6 * 60 }
    ],
    []
  )

  const [question, setQuestion] = useState('最近30分钟有几个用户登录？')
  const [lastMinutes, setLastMinutes] = useState(30)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [sessionId, setSessionId] = useState(() => newSessionId())
  const [thinking, setThinking] = useState('')
  const [timelineEvents, setTimelineEvents] = useState([])
  const controllerRef = useRef(null)

  useEffect(() => {
    if (typeof window === 'undefined') return
    const raw = window.localStorage.getItem('aegis-chatops-state')
    if (!raw) return
    try {
      const data = JSON.parse(raw)
      if (typeof data.question === 'string') {
        setQuestion(data.question)
      }
      if (typeof data.lastMinutes === 'number') {
        setLastMinutes(data.lastMinutes)
      }
    } catch {
      void 0
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const data = {
      question,
      lastMinutes
    }
    window.localStorage.setItem('aegis-chatops-state', JSON.stringify(data))
  }, [question, lastMinutes])

  async function onSubmit() {
    if (controllerRef.current) {
      controllerRef.current.abort()
      controllerRef.current = null
    }
    const controller = new AbortController()
    controllerRef.current = controller
    setLoading(true)
    setError('')
    setResult(null)
    setThinking('')
    try {
      setTimelineEvents([])
      await chatopsQueryStream({
        question,
        lastMinutes,
        sessionId,
        signal: controller.signal,
        onEvent: (evt) => {
          setTimelineEvents((prev) => {
            if (!evt) return prev
            if (evt.event === 'start') return []
            if (evt.event === 'final' || evt.event === 'end') return prev
            return [...prev, evt]
          })
          if (evt.event === 'start') {
            setResult({
              answer: '',
              used_logql: null,
              start: evt.start ? new Date(evt.start) : null,
              end: evt.end ? new Date(evt.end) : null,
              trace: { steps: [] }
            })
          } else if (evt.event === 'llm_token') {
            setThinking((prev) => `${prev}${evt.token || ''}`)
          } else if (evt.event === 'agent_action') {
            setResult((prev) => {
              const base = prev || { answer: '', used_logql: null, start: null, end: null, trace: { steps: [] } }
              const steps = base.trace?.steps || []
              const index = steps.length
              const step = {
                index,
                tool: evt.tool || '',
                tool_input: evt.tool_input || null,
                observation: evt.log || null,
                log: evt.log || null
              }
              return {
                ...base,
                trace: { steps: [...steps, step] }
              }
            })
          } else if (evt.event === 'tool_start') {
            setResult((prev) => {
              const base = prev || { answer: '', used_logql: null, start: null, end: null, trace: { steps: [] } }
              const steps = base.trace?.steps || []
              const index = steps.length
              const step = {
                index,
                tool: evt.tool || '',
                tool_input: evt.tool_input || null,
                observation: null,
                log: null
              }
              return {
                ...base,
                trace: { steps: [...steps, step] }
              }
            })
          } else if (evt.event === 'tool_end') {
            setResult((prev) => {
              const base = prev || { answer: '', used_logql: null, start: null, end: null, trace: { steps: [] } }
              const steps = base.trace?.steps || []
              if (!steps.length) return base
              const last = steps[steps.length - 1]
              const updated = {
                ...last,
                observation: evt.observation || last.observation
              }
              return {
                ...base,
                trace: { steps: [...steps.slice(0, -1), updated] }
              }
            })
          } else if (evt.event === 'final') {
            setResult((prev) => {
              const base = prev || {}
              return {
                ...base,
                answer: evt.answer || '',
                used_logql: evt.used_logql || null,
                start: evt.start ? new Date(evt.start) : base.start || null,
                end: evt.end ? new Date(evt.end) : base.end || null,
                trace: evt.trace || base.trace || null
              }
            })
          }
        }
      })
    } catch (e) {
      if (e?.name === 'AbortError') return
      setError(e?.message || '请求失败')
    } finally {
      setLoading(false)
      controllerRef.current = null
    }
  }

  return (
    <div className="panel">
      <div className="panelHeader">
        <div>
          <div className="panelTitle">自然语言查询日志</div>
          <div className="panelSub">Agent 生成 LogQL → 查询 Loki → 用中文总结答案</div>
        </div>
        <div className="pill">适用于统计类/定位类问题</div>
      </div>

      <div className="field">
        <div className="label">问题</div>
        <textarea
          className="textarea"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="例如：最近30分钟有几个用户登录？"
        />
      </div>

      <div style={{ height: 12 }} />

      <div className="row">
        <div className="pill">时间范围</div>
        <select
          className="select"
          value={lastMinutes}
          onChange={(e) => setLastMinutes(Number(e.target.value))}
        >
          {presets.map((p) => (
            <option key={p.minutes} value={p.minutes}>
              {p.label}
            </option>
          ))}
        </select>

        <button className="btn" type="button" onClick={onSubmit} disabled={loading || !question.trim()}>
          {loading ? '查询中…' : '开始查询'}
        </button>

        <button className="btn" type="button" onClick={() => setSessionId(newSessionId())} disabled={loading}>
          重置会话
        </button>

        {error ? <span style={{ color: 'var(--danger)' }}>{error}</span> : null}
      </div>

      {result ? (
        <>
          <div className="result">
            <div className="resultTitle">回答</div>
            <div style={{ whiteSpace: 'pre-wrap' }}>{result.answer}</div>
            {thinking ? (
              <>
                <div style={{ height: 10 }} />
                <div className="resultTitle">内心独白（LLM 原始推理流）</div>
                <div className="mono" style={{ whiteSpace: 'pre-wrap' }}>
                  {thinking}
                </div>
              </>
            ) : null}
            {result.used_logql ? (
              <>
                <div style={{ height: 10 }} />
                <div className="resultTitle">使用的 LogQL</div>
                <div className="mono">{result.used_logql}</div>
              </>
            ) : null}
          </div>
          <AgentTimeline events={timelineEvents} />
          <TracePanel trace={result.trace} />
        </>
      ) : null}
    </div>
  )
}
