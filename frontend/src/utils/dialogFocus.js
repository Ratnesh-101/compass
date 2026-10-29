// Pure helpers behind the shared <Dialog>: focus-trap maths and the open-dialog stack.

export const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
  '[contenteditable="true"]',
].join(',')

export const ROOT_SENTINEL = 'ROOT'

/**
 * Decide where Tab / Shift+Tab should send focus.
 * Returns the element to focus, ROOT_SENTINEL to park focus on the dialog itself,
 * or null when the browser's default movement already stays inside the dialog.
 */
export function nextTabTarget(focusables, active, shiftKey) {
  if (!focusables.length) return ROOT_SENTINEL
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  if (!focusables.includes(active)) return shiftKey ? last : first
  if (shiftKey && active === first) return last
  if (!shiftKey && active === last) return first
  return null
}

// Only the most recently opened dialog reacts to Escape / Tab, so a dialog opened
// from another dialog behaves correctly and closing it hands control back.
const openDialogs = []

export function pushDialog(token) {
  openDialogs.push(token)
}

export function removeDialog(token) {
  const index = openDialogs.indexOf(token)
  if (index !== -1) openDialogs.splice(index, 1)
}

export function isTopDialog(token) {
  return openDialogs[openDialogs.length - 1] === token
}
