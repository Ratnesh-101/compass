// Newest of the radar sync time and the per-listing verification times, or null.
export function newestRefreshDate(opportunities, stats = null) {
  let newest = null
  if (stats?.last_sync_at) {
    const t = Date.parse(stats.last_sync_at)
    if (!Number.isNaN(t)) newest = t
  }
  for (const opp of opportunities || []) {
    for (const raw of [opp?.last_verified_at, opp?.last_checked_at]) {
      const t = raw ? Date.parse(raw) : NaN
      if (!Number.isNaN(t) && (newest === null || t > newest)) newest = t
    }
  }
  return newest === null ? null : new Date(newest)
}
