// Validates and normalizes URLs to prevent script injection (XSS) and protocol smuggling.

export function getSafeHttpUrl(value) {
  if (typeof value !== 'string' || !value.trim()) return null
  try {
    const parsed = new URL(value.trim())
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null
  } catch {
    return null
  }
}

export function sanitizeUrl(url) {
  if (!url || typeof url !== 'string') return null
  const trimmed = url.trim()
  // eslint-disable-next-line no-control-regex
  const sanitized = trimmed.replace(/[\x00-\x1f\x7f\s]+/g, '')
  if (/^(?:javascript|vbscript|data):/i.test(sanitized)) {
    return null
  }
  const lower = trimmed.toLowerCase()
  if (lower.startsWith('https://') || lower.startsWith('http://') || lower.startsWith('mailto:')) {
    try {
      const parsed = new URL(trimmed)
      if (['https:', 'http:', 'mailto:'].includes(parsed.protocol)) {
        return trimmed
      }
    } catch {
      return null
    }
  }
  return null
}

export function safeHref(url) {
  if (!url || typeof url !== 'string') return '#'
  const trimmed = url.trim()
  // eslint-disable-next-line no-control-regex
  const sanitized = trimmed.replace(/[\x00-\x1f\x7f\s]+/g, '')
  if (/^(?:javascript|vbscript|data):/i.test(sanitized)) {
    return '#'
  }
  if (trimmed.startsWith('/') && !trimmed.startsWith('//') && !trimmed.startsWith('/\\')) {
    return trimmed
  }
  if (trimmed.startsWith('https://') || trimmed.startsWith('http://')) {
    try {
      const parsed = new URL(trimmed)
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        return trimmed
      }
    } catch {
      return '#'
    }
  }
  return '#'
}
