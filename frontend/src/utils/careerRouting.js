// Pure URL helpers for the main tab and the Career Copilot sub-tab (?tab=copilot&sub=resume).

export const MAIN_TABS = ['dashboard', 'compass', 'calendar', 'timeline', 'career']
export const DEFAULT_TAB = 'dashboard'
export const CAREER_SUB_TABS = ['radar', 'resume', 'applications']
export const DEFAULT_CAREER_SUB = 'radar'

const TAB_ALIASES = { copilot: 'career', radar: 'career', internships: 'career', home: 'dashboard', schedule: 'calendar' }

/** Reads ?tab= and ?sub= from a query string. Unknown values fall back to the defaults. */
export function parseCareerLocation(search = '') {
  const params = new URLSearchParams(search || '')
  const rawTab = (params.get('tab') || '').toLowerCase().trim()
  const mapped = TAB_ALIASES[rawTab] || rawTab
  const tab = MAIN_TABS.includes(mapped) ? mapped : DEFAULT_TAB
  const rawSub = (params.get('sub') || '').toLowerCase().trim()
  const sub = tab === 'career' && CAREER_SUB_TABS.includes(rawSub) ? rawSub : DEFAULT_CAREER_SUB
  return { tab, sub }
}

/** Builds the query-string URL for a main tab and, for Career Copilot, its sub-tab. */
export function buildCareerUrl(tab, sub = DEFAULT_CAREER_SUB) {
  const mapped = TAB_ALIASES[tab] || tab
  if (mapped === 'career') {
    const safeSub = CAREER_SUB_TABS.includes(sub) ? sub : DEFAULT_CAREER_SUB
    return safeSub === DEFAULT_CAREER_SUB ? '/?tab=copilot' : `/?tab=copilot&sub=${safeSub}`
  }
  return MAIN_TABS.includes(mapped) ? `/?tab=${mapped}` : '/'
}

/** The Google test-user setup note is for developers only: never shown on a production host. */
export function showDevSetupNote(isDev, hostname = '') {
  return Boolean(isDev) || hostname === 'localhost' || hostname === '127.0.0.1'
}
