import { useMemo, useState } from 'react'
import { chatopsQuery } from '../api'

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
      { label: '最近 15 分钟', minutes: 15 },
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

  async function onSubmit() {
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const data = await chatopsQuery({ question, lastMinutes, sessionId })
      setResult(data)
    } catch (e) {
      setError(e?.message || '请求失败')
    } finally {
      setLoading(false)
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
