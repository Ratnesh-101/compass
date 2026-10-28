// Returns the normalized URL string only when it parses and uses http: or https:.
// Anything else (javascript:, data:, relative, malformed) yields null.
export function getSafeHttpUrl(value) {
  if (typeof value !== 'string' || !value.trim()) return null
  try {
    const parsed = new URL(value.trim())
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null
  } catch {
    return null
  }
}
