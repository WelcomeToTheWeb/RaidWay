import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import {
  getHealth, listReports, getReport, deleteReport, uploadReport,
  listFights, getFightStats, generateReport, generatePlayerReport, chat,
} from './api/client.js'
import { fmtNum, fmtPct, roleColor, outcomeColor } from './format.js'
import './styles.css'

function App() {
  const [health, setHealth] = useState(null)
  const [reports, setReports] = useState([])
  const [reportId, setReportId] = useState(null)
  const [fights, setFights] = useState([])
  const [fightId, setFightId] = useState(null)
  const [stats, setStats] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [coach, setCoach] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [selectedPlayer, setSelectedPlayer] = useState(null)

  useEffect(() => { getHealth().then(setHealth).catch(() => {}) }, [])
  useEffect(() => { listReports().then(setReports).catch(() => {}) }, [busy])

  async function onUpload(file) {
    setBusy(true); setError(null); setCoach(null); setMessages([]); setSelectedPlayer(null)
    try {
      const meta = await uploadReport(file)
      setReportId(meta.report_id)
      setFights(meta.fights)
      setFightId(meta.fights[0]?.fight_id ?? null)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function loadSample() {
    setBusy(true); setError(null)
    try {
      const res = await fetch('/samples/sample_raid_log.json')
      const blob = await res.blob()
      await onUpload(new File([blob], 'sample_raid_log.json', { type: 'application/json' }))
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  useEffect(() => {
    if (!reportId || fightId === null) return
    setStats(null); setCoach(null)
    getFightStats(reportId, fightId).then(setStats).catch(e => setError(e.message))
  }, [reportId, fightId])

  async function askCoach(mode, playerName) {
    if (!reportId || fightId === null) return
    setBusy(true); setError(null)
    try {
      const rep = mode === 'player'
        ? await generatePlayerReport(reportId, fightId, playerName)
        : await generateReport(reportId, fightId)
      setCoach(rep)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function sendChat() {
    if (!input.trim() || !reportId) return
    const q = input.trim()
    setInput('')
    const history = messages.map(m => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.content }))
    setMessages(m => [...m, { role: 'user', content: q }])
    setBusy(true)
    try {
      const ans = await chat(reportId, fightId, q, history, selectedPlayer)
      setMessages(m => [...m, { role: 'assistant', content: ans.answer }])
    } catch (e) {
      setMessages(m => [...m, { role: 'assistant', content: `Error: ${e.message}` }])
    } finally { setBusy(false) }
  }

  return (
    <div className="app">
      <header>
        <h1>⚔️ Raid Analyst</h1>
        {health && (
          <div className="health">
            LLM: {health.llm.provider}{health.llm.ready ? '' : ' (offline/mock)'}
          </div>
        )}
      </header>

      <section className="upload-row">
        <label className="btn">
          Upload log (JSON)
          <input type="file" accept=".json,.txt,.csv" onChange={e => e.target.files[0] && onUpload(e.target.files[0])} hidden disabled={busy} />
        </label>
        <button className="btn" onClick={loadSample} disabled={busy}>Load sample raid</button>
        {reports.length > 0 && (
          <select value={reportId ?? ''} onChange={async e => {
            const rid = e.target.value
            setReportId(rid); setCoach(null); setMessages([]); setSelectedPlayer(null)
            const meta = await getReport(rid).catch(() => null)
            if (meta) { setFights(meta.fights); setFightId(meta.fights[0]?.fight_id ?? null) }
          }}>
            {reports.map(r => <option key={r.report_id} value={r.report_id}>{r.source_name}</option>)}
          </select>
        )}
        {reportId && (
          <button className="btn danger" onClick={async () => {
            await deleteReport(reportId).catch(() => {})
            setReportId(null); setFights([]); setFightId(null); setStats(null); setCoach(null); setMessages([]); setBusy(b => !b)
          }}>Remove report</button>
        )}
      </section>

      {error && <div className="error">{error}</div>}

      {fights.length > 0 && (
        <section className="fights">
          <h2>Fights</h2>
          <div className="fight-list">
            {fights.map(f => (
              <button
                key={f.fight_id}
                className={`fight-card${f.fight_id === fightId ? ' active' : ''}`}
                onClick={() => setFightId(f.fight_id)}
              >
                <div className="fight-name">{f.name}</div>
                <div className="fight-meta">
                  <span style={{ color: outcomeColor(f.outcome) }}>{f.outcome}</span>
                  <span>{f.duration_seconds}s</span>
                  {f.difficulty && <span>{f.difficulty}</span>}
                </div>
              </button>
            ))}
          </div>
        </section>
      )}

      {stats && (
        <>
          <section className="summary">
            <div className="stat"><label>Total Damage</label><span>{fmtNum(stats.total_damage)}</span></div>
            <div className="stat"><label>Raid DPS</label><span>{fmtNum(stats.raid_dps)}</span></div>
            <div className="stat"><label>Total Healing</label><span>{fmtNum(stats.total_healing)}</span></div>
            <div className="stat"><label>Raid HPS</label><span>{fmtNum(stats.raid_hps)}</span></div>
            <div className="stat"><label>Deaths</label><span>{stats.total_deaths}</span></div>
            <div className="stat"><label>Duration</label><span>{stats.duration_seconds}s</span></div>
          </section>

          <section className="actions">
            <button className="btn primary" disabled={busy} onClick={() => askCoach('raid')}>
              🧠 Coach the raid
            </button>
            {selectedPlayer && (
              <button className="btn primary" disabled={busy} onClick={() => askCoach('player', selectedPlayer)}>
                🎯 Coach {selectedPlayer}
              </button>
            )}
          </section>

          {coach && (
            <section className="coach card">
              <h3>Coaching Report — {coach.encounter_name}</h3>
              <div className="markdown">{coach.llm_raw}</div>
            </section>
          )}

          <section className="players card">
            <h3>Players</h3>
            <table>
              <thead>
                <tr>
                  <th>Name</th><th>Spec</th><th>Role</th>
                  <th>Damage</th><th>DPS</th>
                  <th>Healing</th><th>HPS</th>
                  <th>Dmg Taken</th><th>Deaths</th><th>Activity</th><th>Crit%</th>
                </tr>
              </thead>
              <tbody>
                {stats.players.map(p => (
                  <tr
                    key={p.name}
                    className={selectedPlayer === p.name ? 'selected' : ''}
                    onClick={() => setSelectedPlayer(selectedPlayer === p.name ? null : p.name)}
                  >
                    <td>{p.name}</td>
                    <td>{p.spec || '—'}</td>
                    <td style={{ color: roleColor(p.role) }}>{p.role}</td>
                    <td>{fmtNum(p.damage)}</td>
                    <td>{fmtNum(p.dps)}</td>
                    <td>{fmtNum(p.healing)}</td>
                    <td>{fmtNum(p.hps)}</td>
                    <td>{fmtNum(p.damage_taken)}</td>
                    <td>{p.deaths}</td>
                    <td>{fmtPct(p.activity_pct)}</td>
                    <td>{p.crit_rate ? Math.round(p.crit_rate * 100) : 0}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="hint">Click a player to focus coaching and chat on them.</p>
          </section>

          <section className="chat card">
            <h3>Ask the Analyst {selectedPlayer && <span className="focus">(focus: {selectedPlayer})</span>}</h3>
            <div className="messages">
              {messages.length === 0 && (
                <p className="hint">Ask things like "Why did we wipe?", "Which healers are underperforming?", or "What should {selectedPlayer || 'a player'} change?"</p>
              )}
              {messages.map((m, i) => (
                <div key={i} className={`msg ${m.role}`}>
                  <div className="who">{m.role === 'user' ? 'You' : 'Analyst'}</div>
                  <div className="content">{m.content}</div>
                </div>
              ))}
            </div>
            <div className="input-row">
              <input
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !busy && sendChat()}
                placeholder="Ask about the fight..."
                disabled={busy || !reportId}
              />
              <button className="btn primary" onClick={sendChat} disabled={busy || !input.trim()}>Send</button>
            </div>
          </section>
        </>
      )}

      {busy && <div className="loading">Working…</div>}
    </div>
  )
}

createRoot(document.getElementById('root')).render(<App />)
