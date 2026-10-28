/**
 * Split text on HTML line-break tags (<br>, <br/>, <br />, any case) so callers can render real line breaks.
 * @param {string} text
 * @returns {string[]} the text segments between breaks (always at least one element)
 */
export function splitOnLineBreaks(text) {
  if (typeof text !== 'string' || text === '') return [typeof text === 'string' ? text : '']
  return text.split(/<br ?\/?>/i)
}
