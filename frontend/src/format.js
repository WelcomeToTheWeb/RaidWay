export function fmtNum(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '0'
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return `${Math.round(n)}`
}

export function fmtPct(n) {
  return `${(n ?? 0).toFixed(1)}%`
}

export function roleColor(role) {
  switch (role) {
    case 'tank': return '#4aa8ff'
    case 'healer': return '#3ddc84'
    case 'dps': return '#ff6b6b'
    default: return '#999'
  }
}

export function outcomeColor(outcome) {
  if (outcome === 'Kill') return '#3ddc84'
  if (outcome === 'Wipe') return '#ff6b6b'
  return '#999'
}
