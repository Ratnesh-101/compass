// Converts scraped markdown job-description text into readable plain text.

const DEFAULT_MAX = 1200

function truncateAtSentence(text, max) {
  if (text.length <= max) return text
  const slice = text.slice(0, max)
  // Last sentence end (. ! ? followed by space/newline) or a paragraph break.
  let cut = -1
  const re = /[.!?](?=\s)|\n\n/g
  let m
  while ((m = re.exec(slice)) !== null) {
    cut = m[0] === '\n\n' ? m.index : m.index + 1
  }
  if (cut < max * 0.5) {
    // No usable sentence boundary: fall back to the last word boundary.
    const sp = slice.lastIndexOf(' ')
    cut = sp > max * 0.5 ? sp : max
  }
  return slice.slice(0, cut).trimEnd().replace(/[,;:\-–]$/, '') + '…'
}

export function plainJobDescription(text, maxLength = DEFAULT_MAX) {
  if (text == null) return ''
  let s = String(text).replace(/\r\n?/g, '\n')

  // Images: ![alt](url) -> dropped.
  s = s.replace(/!\[[^\]]*\]\([^)]*\)/g, '')
  // Links: [text](url "title") -> text.
  s = s.replace(/\[([^\]]*)\]\((?:[^()\s]|\([^)]*\))*(?:\s+(?:"[^"]*"|'[^']*'))?\s*\)/g, '$1')
  // Bare URLs.
  s = s.replace(/<?https?:\/\/[^\s<>)\]]+>?/gi, '')
  s = s.replace(/\bwww\.[^\s<>)\]]+/gi, '')
  // Code fences / inline code markers.
  s = s.replace(/```[a-z]*\n?/gi, '').replace(/`([^`]*)`/g, '$1')
  // Heading hashes (including stray trailing ones).
  s = s.replace(/^[ \t]*#{1,6}[ \t]*/gm, '').replace(/[ \t]+#{2,}[ \t]*$/gm, '')
  // Bold / italic markers.
  s = s.replace(/(\*\*|__)(.+?)\1/g, '$2')
  s = s.replace(/(^|[\s(])\*(?!\s)([^*\n]+?)\*(?=[\s).,;:!?]|$)/g, '$1$2')
  // Flattened scrapes keep markdown markers mid-line: turn ' ##### ' into a paragraph break and ' * ' into a bullet line.
  s = s.replace(/[ \t]+#{1,6}[ \t]+(?=\S)/g, '\n\n').replace(/[ \t]+\*[ \t]+(?=\S)/g, '\n* ')
  // Bullets.
  s = s.replace(/^[ \t]*[*\-+][ \t]+/gm, '• ')
  // Horizontal rules.
  s = s.replace(/^[ \t]*([-*_])([ \t]*\1){2,}[ \t]*$/gm, '')
  // Unescape backslash-escaped punctuation (play\_circle -> play_circle).
  s = s.replace(/\\([\\`*_{}[\]()#+\-.!|<>~&"'])/g, '$1')
  // Material icon names leaked from scraped pages (play_circle_outline, people_alt, lightbulb).
  s = s.replace(/(^|\s)(?:play_circle(?:_outline)?|people_alt|lightbulb|text_snippet)(?=\s)/g, '$1')
  // Whitespace: tidy lines, keep paragraph breaks.
  s = s
    .replace(/[ \t\u00a0]+/g, ' ')
    .replace(/ *\n */g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()

  return truncateAtSentence(s, maxLength)
}

export default plainJobDescription
