// Pure display helpers for the Internship Radar detail modal.
// Keeps internal labels (tier_1, jobspy_glassdoor, "HTTP 200 via tavily_extract", raw errors)
// out of the UI and turns job-description markdown into plain blocks that React can render safely.

const DAY_MS = 24 * 60 * 60 * 1000

// Strings that mean "internal bookkeeping" rather than something a student should read.
const INTERNAL_EVIDENCE_RE =
  /(tier_\d|jobspy|tavily|ats_(greenhouse|lever|ashby)|http\s*\d{3}|via\s+\w+_\w+|verification (failed|stopped|connection)|timed out|traceback|exception|error:|sni_hostname|\bnan\b|retaining current status|status retained)/i

export function isInternalEvidence(text) {
  return Boolean(text) && INTERNAL_EVIDENCE_RE.test(String(text))
}

/** Evidence text that is safe to show, or null when it is an internal label or raw error. */
export function safeVerificationBasis(text) {
  if (!text || isInternalEvidence(text)) return null
  return String(text).trim() || null
}

const SOURCE_TYPE_LABELS = [
  [/^jobspy_linkedin/i, 'LinkedIn'],
  [/^jobspy_indeed/i, 'Indeed'],
  [/^jobspy_glassdoor/i, 'Glassdoor'],
  [/^jobspy_zip/i, 'ZipRecruiter'],
  [/^ats_greenhouse/i, 'Employer careers page (Greenhouse)'],
  [/^ats_lever/i, 'Employer careers page (Lever)'],
  [/^ats_ashby/i, 'Employer careers page (Ashby)'],
  [/^github/i, 'Community list on GitHub'],
  [/^tavily/i, 'Web search'],
  [/official/i, 'Official site'],
]

export function friendlySourceType(type) {
  const t = String(type || '')
  for (const [re, label] of SOURCE_TYPE_LABELS) if (re.test(t)) return label
  return null
}

export function friendlySourceAuthority(authority) {
  const a = String(authority || '').toLowerCase()
  if (a === 'tier_1') return 'Employer source'
  if (a === 'tier_2') return 'Job board'
  if (a === 'tier_3') return 'Web search'
  return null
}

/**
 * "Last checked 3 days ago" when there is a real check date, "Could not re-check today" when the
 * latest attempt failed, otherwise "Not checked yet".
 */
export function lastCheckedLabel(lastVerifiedAt, { checkFailed = false, now = Date.now() } = {}) {
  if (checkFailed) return 'Could not re-check today'
  const t = lastVerifiedAt ? new Date(lastVerifiedAt).getTime() : NaN
  if (Number.isNaN(t)) return 'Not checked yet'
  const days = Math.floor((now - t) / DAY_MS)
  if (days <= 0) return 'Last checked today'
  if (days === 1) return 'Last checked 1 day ago'
  if (days < 60) return `Last checked ${days} days ago`
  return 'Last checked over 2 months ago'
}

/** Auto-generated placeholder text ("X at Y. Discovered on Glassdoor.") is not a job description. */
export function isStubDescription(text) {
  const s = String(text || '').trim()
  if (!s) return true
  return s.length < 220 && /\b(Discovered (on|via)|Verified live opening on official|Published location:)/i.test(s)
}

/** Inline **bold** to segments. Anything else stays literal text. */
export function parseInline(text) {
  const out = []
  const re = /\*\*([^*]+)\*\*/g
  let last = 0
  let m
  const s = String(text || '')
  while ((m = re.exec(s)) !== null) {
    if (m.index > last) out.push({ text: s.slice(last, m.index), bold: false })
    out.push({ text: m[1], bold: true })
    last = m.index + m[0].length
  }
  if (last < s.length) out.push({ text: s.slice(last), bold: false })
  return out.map((seg) => ({ ...seg, text: seg.text.replace(/[*_`]+/g, '') })).filter((seg) => seg.text !== '')
}

const RULE_RE = /^\s*([-_=*]\s*){3,}$/

/**
 * Markdown-ish job description to blocks: {type: 'heading' | 'bullet' | 'paragraph', segments}.
 * Drops horizontal rules ("----"), and headings that have no content under them.
 */
export function descriptionBlocks(text) {
  const lines = String(text || '').replace(/\r\n/g, '\n').split('\n')
  const raw = []
  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed || RULE_RE.test(trimmed)) continue
    const h = trimmed.match(/^#{1,6}\s+(.*)$/)
    const boldOnly = trimmed.match(/^\*\*([^*]+)\*\*:?$/)
    const b = trimmed.match(/^[-*•]\s+(.*)$/)
    if (h) raw.push({ type: 'heading', segments: parseInline(h[1]) })
    else if (boldOnly) raw.push({ type: 'heading', segments: parseInline(boldOnly[1]) })
    else if (b) raw.push({ type: 'bullet', segments: parseInline(b[1]) })
    else raw.push({ type: 'paragraph', segments: parseInline(trimmed) })
  }
  return raw.filter((blk, i) => {
    if (blk.segments.length === 0) return false
    if (blk.type !== 'heading') return true
    const next = raw[i + 1]
    return Boolean(next) && next.type !== 'heading'
  })
}

// ---- Remote roles open worldwide (second tier, never labelled as India) ----

export const WORLDWIDE_CHIP_LABEL = 'Remote · open worldwide'
export const WORLDWIDE_DETAIL_LINE = 'The listing says anyone can apply. Check the company site for location rules.'

const INDIA_TEXT_RE =
  /\b(india|bengaluru|bangalore|mumbai|delhi|new delhi|hyderabad|chennai|pune|kolkata|gurgaon|gurugram|noida|ahmedabad|jaipur|kochi|chandigarh|indore|thiruvananthapuram|coimbatore)\b/i
const WORLDWIDE_TEXT_RE =
  /\b(worldwide|world-wide|anywhere|global remote|remote\s*[(\-–,]?\s*global\b|work from anywhere)\b/i

/**
 * True for a listing that is not located in India but that the server marked India-eligible
 * because the listing itself says anyone can apply. Missing fields never throw.
 */
export function isOpenWorldwide(opportunity) {
  const o = opportunity || {}
  if (o.is_india_eligible !== true) return false
  const country = String(o.country || '').trim()
  const location = String(o.location || o.location_text || '')
  if (/^india$/i.test(country) || INDIA_TEXT_RE.test(location)) return false
  return /^(global|worldwide|anywhere)$/i.test(country) || WORLDWIDE_TEXT_RE.test(location)
}

/** Subheading under "Internship Radar", from the India filter and the loaded list. */
export function radarHeadingText(indiaOnly, opportunities) {
  if (!indiaOnly) {
    return 'Internships worldwide, checked against your degree and year. Some may need a work permit.'
  }
  const list = Array.isArray(opportunities) ? opportunities : []
  if (list.some(isOpenWorldwide)) return 'Internships in India, then remote roles open worldwide'
  return 'Internships in India, or open to applicants in India, checked against your degree and year.'
}
