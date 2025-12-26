const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

function toInt(value, fallback) {
  const n = Number.parseInt(String(value || ''), 10)
  return Number.isFinite(n) ? n : fallback
}

function originWithPort(port) {
  const proto = globalThis.location?.protocol || 'http:'
  const host = globalThis.location?.hostname || 'localhost'
  return `${proto}//${host}:${port}`
}

function resolveBase(path) {
  if (API_BASE) return API_BASE
  if (path.startsWith('/api/chatops')) return originWithPort(toInt(import.meta.env.VITE_CHATOPS_NODEPORT, 30091))
  if (path.startsWith('/api/rca')) return originWithPort(toInt(import.meta.env.VITE_RCA_NODEPORT, 30092))
  if (path.startsWith('/api/predict')) return originWithPort(toInt(import.meta.env.VITE_PREDICT_NODEPORT, 30093))
  return ''
}

async function httpJson(path, options = {}) {
  const res = await fetch(`${resolveBase(path)}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    },
    ...options
  })
  const text = await res.text()
  let data
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  if (!res.ok) {
    const msg =
      typeof data === 'string'
        ? data
        : data?.detail
          ? JSON.stringify(data.detail)
          : JSON.stringify(data)
    throw new Error(msg || `HTTP ${res.status}`)
  }
  return data
}

export function chatopsQuery({ question, lastMinutes, sessionId }) {
  return httpJson('/api/chatops/query', {
    method: 'POST',
    body: JSON.stringify({
      question,
      time_range: lastMinutes ? { last_minutes: lastMinutes } : null,
      session_id: sessionId || null
    })
  })
}

export function rcaAnalyze({ description, startIso, endIso, sessionId }) {
  return httpJson('/api/rca/analyze', {
    method: 'POST',
    body: JSON.stringify({
      description,
      time_range: { start: startIso, end: endIso },
      session_id: sessionId || null
    })
  })
}

export function predictRun({ serviceName, lookbackHours, sessionId }) {
  return httpJson('/api/predict/run', {
    method: 'POST',
    body: JSON.stringify({
      service_name: serviceName,
      lookback_hours: lookbackHours,
      session_id: sessionId || null
    })
  })
}
