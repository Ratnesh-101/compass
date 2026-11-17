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

// A profile save bumps a counter. The refresh effect used to list its callbacks as dependencies,
// and those callbacks were new functions on every render of the parent, so the effect re-ran after
// every refresh (about 12 requests a second). This gate answers "has the counter moved since the
// last refresh I ran?", so a re-render alone can never start another refresh.
export function createRefreshGate(initialTrigger = 0) {
  let lastHandled = Number(initialTrigger) || 0
  return {
    /** True once per increase of `trigger`; false for repeats and for the value present at mount. */
    check(trigger) {
      const value = Number(trigger) || 0
      if (value > lastHandled) {
        lastHandled = value
        return true
      }
      return false
    },
    get lastHandled() {
      return lastHandled
    },
  }
}
