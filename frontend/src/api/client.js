const BASE = '/api'

async function req(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, options)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* ignore */ }
    throw new Error(detail)
  }
  return res.json()
}

export function getHealth() {
  return req('/health')
}

export function listReports() {
  return req('/reports')
}

export function getReport(reportId) {
  return req(`/reports/${reportId}`)
}

export function deleteReport(reportId) {
  return req(`/reports/${reportId}`, { method: 'DELETE' })
}

export function uploadReport(file) {
  const form = new FormData()
  form.append('file', file)
  return req('/reports', { method: 'POST', body: form })
}

export function listFights(reportId) {
  return req(`/reports/${reportId}/fights`)
}

export function getFightStats(reportId, fightId) {
  return req(`/reports/${reportId}/fights/${fightId}/stats`)
}

export function getAnalysisStatus(reportId) {
  return req(`/reports/${reportId}/analysis/status`)
}

export function generateReport(reportId, fightId) {
  return req(`/reports/${reportId}/analysis/report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fight_id: fightId }),
  })
}

export function generatePlayerReport(reportId, fightId, focusPlayer) {
  return req(`/reports/${reportId}/analysis/player-report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fight_id: fightId, focus_player: focusPlayer }),
  })
}

export function chat(reportId, fightId, question, history = [], focusPlayer = null) {
  return req(`/reports/${reportId}/analysis/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fight_id: fightId, question, history, focus_player: focusPlayer }),
  })
}
