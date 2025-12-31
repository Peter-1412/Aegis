import { useEffect, useRef, useState } from 'react'
import { predictRunStream } from '../api'

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

function riskColor(level) {
  if (level === 'high') return 'var(--danger)'
  if (level === 'medium') return 'var(--warn)'
  return 'var(--ok)'
}

export default function PredictPage() {
  const [serviceName, setServiceName] = useState('todo-service')
  const [lookbackHours, setLookbackHours] = useState(6)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [sessionId, setSessionId] = useState(() => newSessionId())
  const [flash, setFlash] = useState(false)
  const [thinking, setThinking] = useState('')
  const controllerRef = useRef(null)

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
      await predictRunStream({
        serviceName,
        lookbackHours,
        sessionId,
        signal: controller.signal,
        onEvent: (evt) => {
          if (evt.event === 'start') {
            setResult({
              service_name: serviceName,
              risk_score: 0,
              risk_level: 'low',
              likely_failures: [],
              explanation: '',
              trace: { steps: [] }
            })
          } else if (evt.event === 'llm_token') {
            setThinking((prev) => `${prev}${evt.token || ''}`)
          } else if (evt.event === 'agent_action') {
            setResult((prev) => {
              const base =
                prev || {
                  service_name: serviceName,
                  risk_score: 0,
                  risk_level: 'low',
                  likely_failures: [],
                  explanation: '',
                  trace: { steps: [] }
                }
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
              const base =
                prev || {
                  service_name: serviceName,
                  risk_score: 0,
                  risk_level: 'low',
                  likely_failures: [],
                  explanation: '',
                  trace: { steps: [] }
                }
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
              const base =
                prev || {
                  service_name: serviceName,
                  risk_score: 0,
                  risk_level: 'low',
                  likely_failures: [],
                  explanation: '',
                  trace: { steps: [] }
                }
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
              const base =
                prev || {
                  service_name: serviceName,
                  risk_score: 0,
                  risk_level: 'low',
                  likely_failures: [],
                  explanation: '',
                  trace: { steps: [] }
                }
              return {
                ...base,
                service_name: evt.service_name || base.service_name || serviceName,
                risk_score: evt.risk_score ?? base.risk_score ?? 0,
                risk_level: evt.risk_level || base.risk_level || 'low',
                likely_failures: evt.likely_failures ?? base.likely_failures ?? [],
                explanation: evt.explanation || base.explanation || '',
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

  useEffect(() => {
    if (!result) return
    if (result.risk_level !== 'high') return
    setFlash(true)
    const timer = setTimeout(() => setFlash(false), 2000)
    return () => clearTimeout(timer)
  }, [result])

  return (
    <div
      className="panel"
      style={{
        position: 'relative',
        overflow: 'hidden',
        transition: 'background-color 0.4s ease',
        background:
          result?.risk_level === 'high'
            ? 'radial-gradient(circle at top, rgba(255,0,0,0.18), transparent 60%), rgba(20,0,0,0.96)'
            : undefined
      }}
    >
      {result?.risk_level === 'high' && (
        <div
          style={{
            pointerEvents: 'none',
            position: 'absolute',
            inset: 0,
            background: flash
              ? 'radial-gradient(circle, rgba(255,255,255,0.22), rgba(255,0,0,0.2), transparent 70%)'
              : 'radial-gradient(circle, rgba(255,0,0,0.12), transparent 70%)',
            mixBlendMode: 'screen',
            transition: 'opacity 0.3s ease',
            opacity: flash ? 1 : 0.6,
            zIndex: 0
          }}
        />
      )}
      <div className="panelHeader">
        <div>
          <div className="panelTitle">未来风险预测</div>
          <div className="panelSub">基于历史错误密度/趋势做风险打分，并给出可能故障</div>
        </div>
        <div className="pill">输出风险概率（0~1）</div>
      </div>

      <div className="grid2">
        <div className="field">
          <div className="label">微服务名称</div>
          <input
            className="input"
            value={serviceName}
            onChange={(e) => setServiceName(e.target.value)}
            placeholder="例如：auth-service"
          />
        </div>
        <div className="field">
          <div className="label">回看窗口</div>
          <select className="select" value={lookbackHours} onChange={(e) => setLookbackHours(Number(e.target.value))}>
            <option value={1}>最近 1 小时</option>
            <option value={2}>最近 2 小时</option>
            <option value={4}>最近 4 小时</option>
            <option value={6}>最近 6 小时</option>
            <option value={24}>最近 24 小时</option>
            <option value={72}>最近 3 天</option>
            <option value={168}>最近 7 天</option>
          </select>
        </div>
      </div>

      <div style={{ height: 12 }} />

      <div className="row">
        <button className="btn" type="button" onClick={onSubmit} disabled={loading || !serviceName.trim()}>
          {loading ? '预测中…' : '开始预测'}
        </button>
        <button className="btn" type="button" onClick={() => setSessionId(newSessionId())} disabled={loading}>
          重置会话
        </button>
        {error ? <span style={{ color: 'var(--danger)' }}>{error}</span> : null}
      </div>

      {result ? (
        <>
          <div className="result">
            <div className="resultTitle">预测结果</div>
            <div className="row">
              <span className="pill">服务：{result.service_name}</span>
              <span className="pill">
                风险分：
                <span style={{ marginLeft: 6, color: riskColor(result.risk_level) }}>{result.risk_score}</span>
              </span>
              <span className="pill">
                风险等级：
                <span style={{ marginLeft: 6, color: riskColor(result.risk_level) }}>{result.risk_level}</span>
              </span>
            </div>

            <div style={{ height: 10 }} />
            <div style={{ whiteSpace: 'pre-wrap' }}>{result.explanation}</div>

            {thinking ? (
              <>
                <div style={{ height: 10 }} />
                <div className="resultTitle">内心独白（LLM 原始推理流）</div>
                <div className="mono" style={{ whiteSpace: 'pre-wrap' }}>
                  {thinking}
                </div>
              </>
            ) : null}

            {(result.likely_failures?.length || 0) > 0 ? (
              <>
                <div style={{ height: 10 }} />
                <div className="resultTitle">可能故障</div>
                <div className="mono">{result.likely_failures.map((x) => `- ${x}`).join('\n')}</div>
              </>
            ) : null}
          </div>
          <TracePanel trace={result.trace} />
        </>
      ) : null}
    </div>
  )
}
