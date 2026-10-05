/**
 * Compass Router & URL State Synchronizer
 * Reuses browser History API for clean, bookmarkable, and shareable routes:
 * - /timeline or / => Timeline view (all domains)
 * - /domain/:domainKey or /:domainKey => Timeline filtered to specific Context Domain
 * - /compass or /northstar => Compass Assistant & Planner
 * - /schedule or /calendar => Calendar Schedule view
 */

export const KNOWN_DOMAINS = ['hackathon', 'coursework', 'code', 'general', 'other']

export function parseLocation(pathname = window.location.pathname, search = window.location.search) {
  const cleanPath = (pathname || '/').replace(/\/+$/, '') || '/'
  const searchParams = new URLSearchParams(search || '')

  // Explicit query parameters
  const queryTab = searchParams.get('tab')
  const queryDomain = searchParams.get('domain')

  if (queryTab === 'compass' || queryTab === 'northstar' || queryTab === 'assistant' || queryTab === 'planner') {
    return { tab: 'compass', domain: 'all' }
  }
  if (queryTab === 'schedule' || queryTab === 'calendar') {
    return { tab: 'calendar', domain: 'all' }
  }

  // Pathname routing: Compass
  if (
    cleanPath === '/compass' ||
    cleanPath === '/northstar' ||
    cleanPath === '/assistant' ||
    cleanPath === '/planner'
  ) {
    return { tab: 'compass', domain: 'all' }
  }

  // Pathname routing: Schedule
  if (cleanPath === '/schedule' || cleanPath === '/calendar') {
    return { tab: 'calendar', domain: 'all' }
  }

  // Domain prefix route: /domain/hackathon, /domain/code, etc.
  if (cleanPath.startsWith('/domain/')) {
    const domainKey = decodeURIComponent(cleanPath.slice('/domain/'.length)).toLowerCase().trim()
    return { tab: 'timeline', domain: domainKey || 'all' }
  }

  // Direct domain route: /hackathon, /coursework, /code, /general, /other
  const rootSegment = cleanPath.slice(1).toLowerCase().trim()
  if (KNOWN_DOMAINS.includes(rootSegment)) {
    return { tab: 'timeline', domain: rootSegment }
  }

  // Timeline with query param or default
  if (cleanPath === '/timeline' || cleanPath === '/') {
    if (queryDomain) {
      return { tab: 'timeline', domain: queryDomain.toLowerCase().trim() }
    }
    return { tab: 'timeline', domain: 'all' }
  }

  // Any other single segment without slashes could be a custom domain (e.g. /robotics)
  if (rootSegment && !rootSegment.includes('/')) {
    return { tab: 'timeline', domain: rootSegment }
  }

  return { tab: 'timeline', domain: 'all' }
}

export function buildUrl(tab, domain) {
  if (tab === 'compass') {
    return '/compass'
  }
  if (tab === 'calendar') {
    return '/schedule'
  }
  // Timeline tab
  if (domain && domain !== 'all') {
    return `/domain/${encodeURIComponent(domain)}`
  }
  return '/timeline'
}
