import { useMemo, useState } from 'react'
import { rcaAnalyze } from '../api'

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

function toInputValue(d) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function RCAPage() {
  const now = useMemo(() => new Date(), [])
  const [description, setDescription] = useState('某段时间内用户无法登录，接口返回 500。请定位根因。')
  const [start, setStart] = useState(toInputValue(new Date(now.getTime() - 30 * 60 * 1000)))
  const [end, setEnd] = useState(toInputValue(now))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [sessionId, setSessionId] = useState(() => newSessionId())

  async function onSubmit() {
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const data = await rcaAnalyze({
        description,
        startIso: new Date(start).toISOString(),
        endIso: new Date(end).toISOString(),
        sessionId
      })
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
          <div className="panelTitle">根因故障定位（RCA）</div>
          <div className="panelSub">自动拉取错误日志样本 → LLM 生成 RCA 报告</div>
        </div>
        <div className="pill">需要明确时间范围</div>
      </div>

      <div className="field">
        <div className="label">故障描述</div>
        <textarea
          className="textarea"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="例如：登录接口 5xx，出现大量超时…"
        />
      </div>

      <div style={{ height: 12 }} />

      <div className="grid2">
        <div className="field">
          <div className="label">开始时间（本地时间）</div>
          <input className="input" type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />
        </div>
        <div className="field">
          <div className="label">结束时间（本地时间）</div>
          <input className="input" type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} />
        </div>
      </div>

      <div style={{ height: 12 }} />

      <div className="row">
        <button
          className="btn"
          type="button"
          onClick={onSubmit}
          disabled={loading || !description.trim() || !start || !end}
        >
          {loading ? '分析中…' : '开始分析'}
        </button>
        <button className="btn" type="button" onClick={() => setSessionId(newSessionId())} disabled={loading}>
          重置会话
        </button>
        {error ? <span style={{ color: 'var(--danger)' }}>{error}</span> : null}
      </div>

      {result ? (
        <>
          <div className="result">
            <div className="resultTitle">RCA 报告</div>
            <div style={{ whiteSpace: 'pre-wrap' }}>{result.summary}</div>

            <div style={{ height: 10 }} />
            <div className="row">
              {result.suspected_service ? <span className="pill">可疑服务：{result.suspected_service}</span> : null}
              {result.root_cause ? <span className="pill">根因：{result.root_cause}</span> : null}
            </div>

            {(result.evidence?.length || 0) > 0 ? (
              <>
                <div style={{ height: 10 }} />
                <div className="resultTitle">证据要点</div>
                <div className="mono">{result.evidence.join('\n')}</div>
              </>
            ) : null}

            {(result.suggested_actions?.length || 0) > 0 ? (
              <>
                <div style={{ height: 10 }} />
                <div className="resultTitle">建议动作</div>
                <div className="mono">{result.suggested_actions.join('\n')}</div>
              </>
            ) : null}
          </div>
          <TracePanel trace={result.trace} />
        </>
      ) : null}
    </div>
  )
}
