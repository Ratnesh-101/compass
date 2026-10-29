// User timezone helpers: the browser's IANA zone is sent to the scheduler; timestamps stay UTC on the wire.

export function getUserTimeZone() {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
    return typeof tz === 'string' && tz ? tz : 'UTC'
  } catch {
    return 'UTC'
  }
}

function zonedParts(iso, timeZone) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return null
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)
  const out = {}
  for (const p of parts) out[p.type] = p.value
  return out
}

// 'YYYY-MM-DD' of the instant in the given zone (falls back to the UTC date part on bad input).
export function zonedDateKey(iso, timeZone) {
  try {
    const p = zonedParts(iso, timeZone)
    if (p) return `${p.year}-${p.month}-${p.day}`
  } catch { /* fall through */ }
  return String(iso).split('T')[0]
}

// Minutes since local midnight of the instant in the given zone.
export function zonedMinutes(iso, timeZone) {
  try {
    const p = zonedParts(iso, timeZone)
    if (p) return Number(p.hour) * 60 + Number(p.minute)
  } catch { /* fall through */ }
  const d = new Date(iso)
  return d.getUTCHours() * 60 + d.getUTCMinutes()
}

export function workingWindowLabel(timeZone) {
  return `09:00 - 18:00 ${timeZone || 'UTC'}`
}
