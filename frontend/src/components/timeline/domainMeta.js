export const KNOWN_FIELDS = new Set([
  'id', 'domain', 'project', 'timestamp', 'title', 'tags',
  'countdown', 'vector_dim', 'description'
])

export const DOMAIN_META = {
  hackathon: { label: 'Hackathon', icon: '🚀', color: '#fbbf24', border: 'rgba(245, 158, 11, 0.4)' },
  coursework: { label: 'Coursework', icon: '📚', color: '#60a5fa', border: 'rgba(59, 130, 246, 0.4)' },
  code: { label: 'Code', icon: '💻', color: '#34d399', border: 'rgba(16, 185, 129, 0.4)' },
  general: { label: 'General', icon: '🌐', color: '#94a3b8', border: 'rgba(100, 116, 139, 0.4)' },
  other: { label: 'Other', icon: '🏷️', color: '#a78bfa', border: 'rgba(167, 139, 250, 0.4)' },
}

export function normalizeDomainKey(name) {
  if (!name) return ''
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}

export function getCustomDomains() {
  try {
    const raw = localStorage.getItem('compass.custom_domains')
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) return parsed
    }
  } catch {
    /* ignore storage read error */
  }
  return []
}

export function saveCustomDomain(domain) {
  try {
    const existing = getCustomDomains()
    const filtered = existing.filter(d => d.key !== domain.key)
    filtered.push(domain)
    localStorage.setItem('compass.custom_domains', JSON.stringify(filtered))
    return filtered
  } catch (err) {
    console.warn('Failed to save custom domain to localStorage:', err)
    return []
  }
}

export function removeCustomDomain(domainKey) {
  try {
    const existing = getCustomDomains()
    const filtered = existing.filter(d => d.key !== domainKey)
    localStorage.setItem('compass.custom_domains', JSON.stringify(filtered))
    return filtered
  } catch (err) {
    console.warn('Failed to remove custom domain from localStorage:', err)
    return []
  }
}

export function getDomainMeta(dom) {
  if (!dom) return DOMAIN_META.general
  const key = String(dom).toLowerCase().trim()
  if (DOMAIN_META[key]) return DOMAIN_META[key]

  const custom = getCustomDomains().find(d => d.key === key)
  if (custom) {
    return {
      label: custom.label || (key.charAt(0).toUpperCase() + key.slice(1)),
      icon: custom.icon || '🎯',
      color: custom.color || '#c084fc',
      border: custom.border || 'rgba(192, 132, 252, 0.4)',
    }
  }

  return {
    label: key.charAt(0).toUpperCase() + key.slice(1),
    icon: '🏷️',
    color: '#c084fc',
    border: 'rgba(192, 132, 252, 0.4)',
  }
}

export function formatFieldLabel(key) {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
}

export function formatFieldValue(value) {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}
