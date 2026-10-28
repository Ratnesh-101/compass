/**
 * True for a markdown horizontal rule line: three or more dashes, asterisks or underscores and nothing else.
 * @param {string} line a trimmed line of text
 * @returns {boolean}
 */
export function isHorizontalRule(line) {
  return typeof line === 'string' && /^(?:-{3,}|\*{3,}|_{3,})$/.test(line)
}
