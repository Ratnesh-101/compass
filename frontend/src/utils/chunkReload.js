/**
 * Detects whether an error is caused by a missing/stale hashed JavaScript chunk
 * (typically after a new frontend deployment when an open tab requests old chunks).
 *
 * @param {unknown} err
 * @returns {boolean}
 */
export function isStaleChunkError(err) {
  if (!err || typeof err !== 'object' || typeof err.message !== 'string') {
    return false
  }
  const pattern =
    /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|MIME type of "text\/html"/i
  return pattern.test(err.message)
}

/**
 * Checks if a reload should be performed for a stale chunk error.
 * Ensures only a single reload occurs within a 60-second cooldown window to prevent
 * infinite reload loops.
 *
 * @param {unknown} err
 * @param {Storage} [storage=globalThis.sessionStorage]
 * @param {number} [now=Date.now()]
 * @returns {boolean}
 */
export function shouldReloadForStaleChunk(
  err,
  storage = globalThis.sessionStorage,
  now = Date.now()
) {
  if (!isStaleChunkError(err)) {
    return false
  }

  const key = 'compass.chunkReload'
  const cooldownMs = 60000

  try {
    const raw = storage.getItem(key)
    if (raw) {
      const last = Number(raw)
      if (!Number.isNaN(last) && now - last < cooldownMs) {
        return false
      }
    }
  } catch {
    return false
  }

  try {
    storage.setItem(key, String(now))
  } catch {
    /* if setItem throws still return true */
  }

  return true
}
