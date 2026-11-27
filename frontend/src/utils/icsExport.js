/**
 * Summarize tasks exportable to an .ics calendar feed vs undated open tasks left out.
 *
 * Uses the same filtering rules as backend export_calendar_ics_endpoint:
 * - Excludes tasks with status in {'done', 'completed', 'cancelled'} (missing status = 'open').
 * - Matches domain filter ('all' or empty string/falsy = every domain).
 * - exportable: open tasks with scheduled_start, due_date, or due_at.
 * - undated: open tasks matching the domain with none of those time/date fields.
 *
 * @param {Array<Object>} tasks
 * @param {string} [domain]
 * @returns {{ exportable: number, undated: number }}
 */
const EXCLUDED_STATUSES = new Set(['done', 'completed', 'cancelled'])

export function summarizeIcsExport(tasks, domain) {
  let exportable = 0
  let undated = 0

  const items = Array.isArray(tasks) ? tasks : []
  const matchAll = !domain || domain === 'all'

  for (const t of items) {
    if (!t) continue
    const status = String(t.status || 'open').toLowerCase().trim()
    if (EXCLUDED_STATUSES.has(status)) continue
    if (!matchAll && t.domain !== domain) continue

    if (t.scheduled_start || t.due_date || t.due_at) {
      exportable++
    } else {
      undated++
    }
  }

  return { exportable, undated }
}
