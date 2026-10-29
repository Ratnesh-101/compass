/**
 * Compass Router & URL State Synchronizer
 * Reuses browser History API for clean, bookmarkable, and shareable routes:
 * - /timeline or / => Timeline view (all domains)
 * - /domain/:domainKey or /:domainKey => Timeline filtered to specific Context Domain
 * - /compass => Compass Assistant & Planner
 * - /schedule or /calendar => Calendar Schedule view
 */

export const KNOWN_DOMAINS = ['hackathon', 'coursework', 'code', 'general', 'other']

export const RESERVED_ROUTES = [
  'terms',
  'privacy',
  'dashboard',
  'compass',
  'northstar',
  'assistant',
  'planner',
  'schedule',
  'calendar',
  'career',
  'radar',
  'internships',
  'copilot',
  'timeline',
  'domain',
  'share',
  '404',
  'api',
  'health',
  'chat',
  'admin',
  'auth',
]

export function parseLocation(pathname = window.location.pathname, search = window.location.search) {
  const cleanPath = (pathname || '/').replace(/\/+$/, '') || '/'
  const searchParams = new URLSearchParams(search || '')

  // Share route: query param (?share=<token>) or pathname (/share/<token>)
  if (searchParams.has('share')) {
    const token = (searchParams.get('share') || '').trim()
    return { tab: 'share', shareToken: token, domain: 'all' }
  }
  if (cleanPath.startsWith('/share/')) {
    const token = decodeURIComponent(cleanPath.slice('/share/'.length)).trim()
    return { tab: 'share', shareToken: token, domain: 'all' }
  }

  // Explicit query parameters
  const queryTab = searchParams.get('tab')
  const queryDomain = searchParams.get('domain')

  if (queryTab === 'terms') {
    return { tab: 'terms', domain: 'all' }
  }
  if (queryTab === 'privacy') {
    return { tab: 'privacy', domain: 'all' }
  }
  if (queryTab === 'dashboard' || queryTab === 'home') {
    return { tab: 'dashboard', domain: 'all' }
  }
  if (queryTab === 'compass' || queryTab === 'assistant' || queryTab === 'planner') {
    return { tab: 'compass', domain: 'all' }
  }
  if (queryTab === 'schedule' || queryTab === 'calendar') {
    return { tab: 'calendar', domain: 'all' }
  }
  if (queryTab === 'career' || queryTab === 'copilot' || queryTab === 'radar' || queryTab === 'internships') {
    return { tab: 'career', domain: 'all' }
  }
  if (queryTab === 'timeline') {
    return { tab: 'timeline', domain: queryDomain ? queryDomain.toLowerCase().trim() : 'all' }
  }

  // Legal routes: registered BEFORE custom domain fallback
  if (cleanPath === '/terms') {
    return { tab: 'terms', domain: 'all' }
  }
  if (cleanPath === '/privacy') {
    return { tab: 'privacy', domain: 'all' }
  }

  // Pathname routing: Dashboard
  if (cleanPath === '/dashboard') {
    return { tab: 'dashboard', domain: 'all' }
  }

  // Pathname routing: Compass
  if (
    cleanPath === '/compass' ||
    cleanPath === '/northstar' || // legacy redirect — resolve to compass
    cleanPath === '/assistant' ||
    cleanPath === '/planner'
  ) {
    return { tab: 'compass', domain: 'all' }
  }

  // Pathname routing: Schedule
  if (cleanPath === '/schedule' || cleanPath === '/calendar') {
    return { tab: 'calendar', domain: 'all' }
  }

  // Pathname routing: Career Copilot & Internship Radar
  if (cleanPath === '/career' || cleanPath === '/radar' || cleanPath === '/internships') {
    return { tab: 'career', domain: 'all' }
  }

  // Pathname routing: Timeline explicit
  if (cleanPath === '/timeline') {
    if (queryDomain) {
      return { tab: 'timeline', domain: queryDomain.toLowerCase().trim() }
    }
    return { tab: 'timeline', domain: 'all' }
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

  // Root path: / lands on Dashboard by default
  if (cleanPath === '/') {
    return { tab: 'dashboard', domain: 'all' }
  }

  // Any other single segment without slashes could be a custom domain (e.g. /robotics)
  // Guarded against colliding with reserved route names
  if (rootSegment && !rootSegment.includes('/')) {
    if (!RESERVED_ROUTES.includes(rootSegment)) {
      return { tab: 'timeline', domain: rootSegment }
    }
  }

  // Any unrecognized route or multi-segment path resolves to 404
  return { tab: '404', domain: 'all' }
}

export function buildUrl(tab, domain, shareToken = null) {
  if (tab === 'share') {
    return shareToken ? `/?share=${encodeURIComponent(shareToken)}` : '/'
  }
  if (tab === 'terms') {
    return '/terms'
  }
  if (tab === 'privacy') {
    return '/privacy'
  }
  if (tab === '404') {
    return '/404'
  }
  if (tab === 'dashboard') {
    return '/'
  }
  if (tab === 'compass') {
    return '/compass'
  }
  if (tab === 'calendar') {
    return '/schedule'
  }
  if (tab === 'career' || tab === 'radar') {
    return '/career'
  }
  // Timeline tab
  if (domain && domain !== 'all') {
    return `/domain/${encodeURIComponent(domain)}`
  }
  return '/timeline'
}
