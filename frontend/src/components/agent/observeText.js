// Plain-language text for an observe step (tool output). No JSX, importable from node tests.

const HIDDEN_KEYS = new Set(['user_id', 'owner', 'include_demo', 'is_guest'])

function stripHidden(value) {
  if (Array.isArray(value)) return value.map(stripHidden)
  if (value && typeof value === 'object') {
    const out = {}
    for (const [k, v] of Object.entries(value)) {
      if (!HIDDEN_KEYS.has(k)) out[k] = stripHidden(v)
    }
    return out
  }
  return value
}

export function formatObserveContent(content) {
  if (typeof content !== 'string') return content
  const match = content.match(/^Found (\d+) task\(s\)(?: with status '([^']+)')?:/i)
  if (match) {
    const count = match[1]
    const status = match[2] ? ` (status: ${match[2]})` : ''
    return `Found ${count} task${count === '1' ? '' : 's'}${status}. Analyzing your schedule and commitments…`
  }
  const trimmed = content.trim()
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      const data = stripHidden(JSON.parse(trimmed))
      if (data && typeof data === 'object') {
        if (typeof data.response === 'string' && data.response) return data.response
        if (typeof data.message === 'string' && data.message) return data.message
        if (Array.isArray(data)) return `Retrieved ${data.length} result${data.length === 1 ? '' : 's'}.`
      }
    } catch {
      // Python-style or truncated output: fall through to the generic line.
    }
    return 'Retrieved the information. Analyzing it…'
  }
  return content
}
