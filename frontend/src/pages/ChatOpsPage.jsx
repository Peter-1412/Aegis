import { useEffect, useMemo, useRef, useState } from 'react'
import { chatopsQueryStream } from '../api'

function newSessionId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
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
                <pre className="mono" style={{ whiteSpace: 'pre-wrap' }}>
                  {s.tool_input}
                </pre>
              </>
            ) : null}
            {s.observation ? (
              <>
                <div style={{ height: 6 }} />
                <div className="resultTitle">观察</div>
                <pre className="mono" style={{ whiteSpace: 'pre-wrap' }}>
                  {s.observation}
                </pre>
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
      await chatopsQueryStream({
        question,
        lastMinutes,
        sessionId,
        signal: controller.signal,
        onEvent: (evt) => {
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
          <TracePanel trace={result.trace} />
        </>
      ) : null}
    </div>
  )
}
