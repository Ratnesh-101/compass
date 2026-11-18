export const MAX_TEXTAREA_HEIGHT = 160

// Sizes a textarea to its content, capped at maxHeight. Returns the height set (px).
// With no content, the height is cleared so the CSS minHeight applies again.
export function autoGrowTextarea(el, maxHeight = MAX_TEXTAREA_HEIGHT) {
  if (!el) return 0
  if (!el.value) {
    el.style.height = ''
    el.style.overflowY = 'hidden'
    return 0
  }
  el.style.height = 'auto'
  const next = Math.min(el.scrollHeight, maxHeight)
  el.style.height = `${next}px`
  el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden'
  return next
}
