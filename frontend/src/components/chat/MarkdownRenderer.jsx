import React, { useState } from 'react'
import { splitOnLineBreaks } from '../../utils/markdownBreaks'
import { isHorizontalRule } from '../../utils/markdownRules'

/**
 * Validates and sanitizes a link URL to prevent script injection (XSS).
 * Only allows https:, http:, and mailto: protocols.
 */
function sanitizeUrl(url) {
  if (!url || typeof url !== 'string') return null
  const trimmed = url.trim()
  const lower = trimmed.toLowerCase()
  if (lower.startsWith('https://') || lower.startsWith('http://') || lower.startsWith('mailto:')) {
    return trimmed
  }
  return null
}

/**
 * Parses inline formatting:
 * - Bold: **text**
 * - Italic: *text*
 * - Inline code: `text`
 * - Links: [label](url)
 */
function renderTextWithBreaks(text, keyBase) {
  const segments = splitOnLineBreaks(text)
  if (segments.length === 1) return segments[0]
  const nodes = []
  segments.forEach((segment, i) => {
    if (i > 0) nodes.push(<br key={`${keyBase}-br-${i}`} />)
    if (segment) nodes.push(segment)
  })
  return nodes
}

export function parseInlineFormatting(text) {
  if (!text) return ''

  const parts = []
  // Matches inline code (`...`), bold (**...**), italic (*...*), or markdown links ([label](url))
  const regex = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g
  let lastIndex = 0
  let match

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(...[].concat(renderTextWithBreaks(text.substring(lastIndex, match.index), `t${lastIndex}`)))
    }
    const token = match[0]

    if (token.startsWith('`') && token.endsWith('`') && token.length > 2) {
      parts.push(
        <code
          key={match.index}
          style={{
            fontFamily: 'JetBrains Mono, monospace',
            fontSize: '12px',
            padding: '2px 5px',
            borderRadius: '4px',
            background: 'var(--bg-card-soft, rgba(0, 0, 0, 0.05))',
            color: 'var(--code-text, #e11d48)',
            border: '1px solid var(--border-soft, rgba(0,0,0,0.06))',
          }}
        >
          {token.slice(1, -1)}
        </code>
      )
    } else if (token.startsWith('**') && token.endsWith('**') && token.length > 4) {
      parts.push(
        <strong key={match.index} style={{ fontWeight: '600', color: 'var(--text-primary)' }}>
          {token.slice(2, -2)}
        </strong>
      )
    } else if (token.startsWith('*') && token.endsWith('*') && token.length > 2) {
      parts.push(<em key={match.index}>{token.slice(1, -1)}</em>)
    } else if (token.startsWith('[') && token.includes('](') && token.endsWith(')')) {
      const closingBracket = token.indexOf('](')
      const label = token.slice(1, closingBracket)
      const rawUrl = token.slice(closingBracket + 2, -1)
      const safeUrl = sanitizeUrl(rawUrl)

      if (safeUrl) {
        parts.push(
          <a
            key={match.index}
            href={safeUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              color: 'var(--coursework, #3b82f6)',
              textDecoration: 'underline',
              textUnderlineOffset: '2px',
              wordBreak: 'break-word',
            }}
          >
            {label}
          </a>
        )
      } else {
        parts.push(<span key={match.index}>{label}</span>)
      }
    }
    lastIndex = regex.lastIndex
  }

  if (lastIndex < text.length) {
    parts.push(...[].concat(renderTextWithBreaks(text.substring(lastIndex), `t${lastIndex}`)))
  }

  return parts.length > 0 ? parts : text
}

function CodeBlock({ language, code }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(code).then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      }).catch(() => {})
    }
  }

  return (
    <div style={{
      margin: '8px 0',
      borderRadius: '8px',
      overflow: 'hidden',
      border: '1px solid var(--border)',
      background: 'var(--bg-sidebar, #0f172a)',
      color: '#f8fafc',
      fontSize: '12px',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '6px 12px',
        background: 'rgba(255, 255, 255, 0.05)',
        borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
        fontSize: '11px',
        color: '#94a3b8',
        fontFamily: 'JetBrains Mono, monospace',
      }}>
        <span>{language || 'code'}</span>
        <button
          type="button"
          onClick={handleCopy}
          style={{
            background: 'transparent',
            border: 'none',
            color: copied ? 'var(--coursework, #38bdf8)' : '#94a3b8',
            cursor: 'pointer',
            fontSize: '11px',
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            padding: '2px 6px',
            borderRadius: '4px',
          }}
        >
          {copied ? '✓ Copied' : 'Copy'}
        </button>
      </div>
      <pre style={{
        margin: 0,
        padding: '10px 14px',
        overflowX: 'auto',
        fontFamily: 'JetBrains Mono, monospace',
        lineHeight: '1.5',
      }}>
        <code>{code}</code>
      </pre>
    </div>
  )
}

function TableBlock({ headers, rows }) {
  return (
    <div style={{ overflowX: 'auto', margin: '8px 0', borderRadius: '8px', border: '1px solid var(--border)' }}>
      <table style={{
        width: '100%',
        borderCollapse: 'collapse',
        fontSize: '12.5px',
        textAlign: 'left',
      }}>
        {headers && headers.length > 0 && (
          <thead>
            <tr style={{ background: 'var(--bg-card-soft, rgba(0,0,0,0.04))', borderBottom: '1px solid var(--border)' }}>
              {headers.map((h, i) => (
                <th key={i} style={{ padding: '7px 12px', fontWeight: '600', color: 'var(--text-primary)' }}>
                  {parseInlineFormatting(h)}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {rows.map((row, rIdx) => (
            <tr
              key={rIdx}
              style={{
                borderBottom: rIdx < rows.length - 1 ? '1px solid var(--border-soft, rgba(0,0,0,0.06))' : 'none',
                background: rIdx % 2 === 1 ? 'var(--bg-card-soft, rgba(0,0,0,0.02))' : 'transparent',
              }}
            >
              {row.map((cell, cIdx) => (
                <td key={cIdx} style={{ padding: '6px 12px', color: 'var(--text-primary)' }}>
                  {parseInlineFormatting(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * Upgraded, streaming-resilient Markdown renderer.
 * Parses blocks (code fences, tables, blockquotes, checklists, headings, lists, paragraphs)
 * and inline syntax without external dependencies.
 */
export default function MarkdownRenderer({ content }) {
  if (!content) return null

  const cleaned = content.replace(/\[\[modes\]\]/gi, '').trim()
  const rawLines = cleaned.split('\n')

  const elements = []
  let i = 0

  while (i < rawLines.length) {
    const line = rawLines[i]
    const trimmed = line.trim()

    // 1. Fenced Code Block: ```[lang]
    if (trimmed.startsWith('```')) {
      const language = trimmed.slice(3).trim()
      const codeLines = []
      i++
      while (i < rawLines.length && !rawLines[i].trim().startsWith('```')) {
        codeLines.push(rawLines[i])
        i++
      }
      if (i < rawLines.length && rawLines[i].trim().startsWith('```')) {
        i++ // consume closing fence
      }
      elements.push(
        <CodeBlock
          key={`code-${elements.length}`}
          language={language}
          code={codeLines.join('\n')}
        />
      )
      continue
    }

    // 2. Markdown Table Detection: starts/ends with | or contains |
    if (trimmed.startsWith('|') && trimmed.endsWith('|') && trimmed.length > 2) {
      const tableLines = []
      while (i < rawLines.length && rawLines[i].trim().startsWith('|') && rawLines[i].trim().endsWith('|')) {
        tableLines.push(rawLines[i].trim())
        i++
      }

      if (tableLines.length >= 2) {
        const parseRow = (r) => r.slice(1, -1).split('|').map(c => c.trim())
        const headers = parseRow(tableLines[0])
        const dataRows = []

        for (let r = 1; r < tableLines.length; r++) {
          const cells = parseRow(tableLines[r])
          // Skip delimiter row like |---|---|
          if (cells.every(c => /^[-:\s]+$/.test(c))) {
            continue
          }
          dataRows.push(cells)
        }

        elements.push(
          <TableBlock
            key={`tbl-${elements.length}`}
            headers={headers}
            rows={dataRows}
          />
        )
        continue
      } else {
        // Fallback if not a complete table
        i -= tableLines.length
      }
    }

    // 3. Router Latency Chip
    if (line.includes('Routed via Nemotron-3 Nano') || (line.includes('⚡') && line.includes('ms'))) {
      elements.push(
        <div key={`chip-${elements.length}`} className="router-chip" style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
          padding: '3px 8px',
          borderRadius: '6px',
          background: 'var(--bg-card-soft, rgba(0, 0, 0, 0.04))',
          border: '1px solid var(--border)',
          fontSize: '11.5px',
          color: 'var(--text-secondary)',
          margin: '4px 0',
          fontFamily: 'JetBrains Mono, monospace',
        }}>
          <span>⚡</span>
          <span>{line.replace('⚡', '').trim()}</span>
        </div>
      )
      i++
      continue
    }

    // 4. Headings
    if (trimmed.startsWith('#### ')) {
      elements.push(
        <h5 key={`h5-${elements.length}`} style={{ margin: '8px 0 2px 0', fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>
          {parseInlineFormatting(trimmed.substring(5))}
        </h5>
      )
      i++
      continue
    }
    if (trimmed.startsWith('### ')) {
      elements.push(
        <h4 key={`h4-${elements.length}`} style={{ margin: '12px 0 4px 0', fontSize: '14.5px', fontWeight: '600', color: 'var(--text-primary)' }}>
          {parseInlineFormatting(trimmed.substring(4))}
        </h4>
      )
      i++
      continue
    }
    if (trimmed.startsWith('## ')) {
      elements.push(
        <h3 key={`h3-${elements.length}`} style={{ margin: '14px 0 5px 0', fontSize: '15.5px', fontWeight: '600', color: 'var(--text-primary)' }}>
          {parseInlineFormatting(trimmed.substring(3))}
        </h3>
      )
      i++
      continue
    }
    if (trimmed.startsWith('# ')) {
      elements.push(
        <h2 key={`h2-${elements.length}`} style={{ margin: '16px 0 6px 0', fontSize: '17px', fontWeight: '700', color: 'var(--text-primary)' }}>
          {parseInlineFormatting(trimmed.substring(2))}
        </h2>
      )
      i++
      continue
    }

    // 5. Special Compass Badges
    if (line.includes('Coursework') && (line.includes('📚') || line.includes('CS 61C'))) {
      elements.push(
        <div key={`cw-${elements.length}`} style={{ marginTop: '10px', marginBottom: '4px', color: 'var(--coursework-text)', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="badge-coursework" style={{ padding: '2px 8px', borderRadius: '20px', fontSize: '11px', textTransform: 'uppercase' }}>
            Coursework
          </span>
          <span>{line.replace(/^\d+\.\s*/, '').replace('📚', '').trim()}</span>
        </div>
      )
      i++
      continue
    }
    if (line.includes('Hackathon') && (line.includes('🚀') || line.includes('Nebius'))) {
      elements.push(
        <div key={`hk-${elements.length}`} style={{ marginTop: '10px', marginBottom: '4px', color: 'var(--hackathon-text)', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="badge-hackathon" style={{ padding: '2px 8px', borderRadius: '20px', fontSize: '11px', textTransform: 'uppercase' }}>
            Hackathon
          </span>
          <span>{line.replace(/^\d+\.\s*/, '').replace('🚀', '').trim()}</span>
        </div>
      )
      i++
      continue
    }
    if (line.includes('Next Step:')) {
      elements.push(
        <div key={`ns-${elements.length}`} style={{
          marginTop: '10px',
          marginBottom: '6px',
          padding: '10px 14px',
          borderRadius: '10px',
          background: 'var(--bg-card-soft, rgba(0,0,0,0.03))',
          border: '1px solid var(--border)',
          color: 'var(--code-text, inherit)',
          fontSize: '12.5px',
          fontFamily: 'JetBrains Mono, monospace',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}>
          <span style={{ color: 'var(--code, #e11d48)' }}>❯</span>
          <span>{line}</span>
        </div>
      )
      i++
      continue
    }

    // 6. Blockquote (> quote)
    if (trimmed.startsWith('>')) {
      const quoteText = trimmed.replace(/^>\s*/, '')
      elements.push(
        <blockquote key={`quote-${elements.length}`} style={{
          margin: '6px 0',
          padding: '6px 12px',
          borderLeft: '3px solid var(--coursework, #3b82f6)',
          background: 'var(--bg-card-soft, rgba(0, 0, 0, 0.03))',
          borderRadius: '0 6px 6px 0',
          color: 'var(--text-secondary)',
          fontStyle: 'italic',
          fontSize: '13px',
        }}>
          {parseInlineFormatting(quoteText)}
        </blockquote>
      )
      i++
      continue
    }

    // 7. Checklists: - [ ] or - [x]
    const checklistMatch = trimmed.match(/^[-*•]\s+\[([ xX])\]\s+(.*)$/)
    if (checklistMatch) {
      const isChecked = checklistMatch[1].toLowerCase() === 'x'
      const itemText = checklistMatch[2]
      elements.push(
        <div key={`chk-${elements.length}`} style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: '8px',
          margin: '3px 0 3px 4px',
          fontSize: '13.5px',
        }}>
          <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '15px',
            height: '15px',
            marginTop: '2px',
            borderRadius: '4px',
            border: `1.5px solid ${isChecked ? 'var(--coursework, #3b82f6)' : 'var(--border)'}`,
            background: isChecked ? 'var(--coursework, #3b82f6)' : 'transparent',
            color: '#fff',
            fontSize: '10px',
            fontWeight: '700',
            flexShrink: 0,
          }}>
            {isChecked ? '✓' : ''}
          </span>
          <span style={{
            lineHeight: '1.5',
            color: isChecked ? 'var(--text-muted)' : 'var(--text-primary)',
            textDecoration: isChecked ? 'line-through' : 'none',
          }}>
            {parseInlineFormatting(itemText)}
          </span>
        </div>
      )
      i++
      continue
    }

    // 7b. Horizontal rules (---, ***, ___)
    if (isHorizontalRule(trimmed)) {
      elements.push(
        <hr key={`hr-${elements.length}`} style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '12px 0' }} />
      )
      i++
      continue
    }

    // 8. Bullet Lists (•, -, *)
    if (trimmed.startsWith('•') || trimmed.startsWith('-') || trimmed.startsWith('* ')) {
      const bulletText = trimmed.replace(/^[•\-*]\s*/, '')
      elements.push(
        <div key={`bullet-${elements.length}`} style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: '8px',
          margin: '2px 0 2px 6px',
          color: 'var(--text-primary)',
          fontSize: '13.5px',
        }}>
          <span style={{ color: 'var(--coursework, #3b82f6)', fontWeight: '700', lineHeight: '1.4' }}>•</span>
          <span style={{ lineHeight: '1.5' }}>{parseInlineFormatting(bulletText)}</span>
        </div>
      )
      i++
      continue
    }

    // 9. Numbered lists (1. , 2. )
    const numMatch = trimmed.match(/^(\d+)\.\s+(.*)$/)
    if (numMatch) {
      elements.push(
        <div key={`num-${elements.length}`} style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: '8px',
          margin: '2px 0 2px 6px',
          color: 'var(--text-primary)',
          fontSize: '13.5px',
        }}>
          <span style={{ color: 'var(--coursework, #3b82f6)', fontWeight: '600', minWidth: '18px', lineHeight: '1.4' }}>
            {numMatch[1]}.
          </span>
          <span style={{ lineHeight: '1.5' }}>{parseInlineFormatting(numMatch[2])}</span>
        </div>
      )
      i++
      continue
    }

    // 10. Empty spacing lines
    if (!trimmed) {
      elements.push(<div key={`sp-${elements.length}`} style={{ height: '6px' }} />)
      i++
      continue
    }

    // 11. Standard Paragraph
    elements.push(
      <p key={`p-${elements.length}`} style={{ margin: '3px 0', lineHeight: '1.65', color: 'var(--text-primary)' }}>
        {parseInlineFormatting(line)}
      </p>
    )
    i++
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', fontSize: '13.5px', lineHeight: '1.65' }}>
      {elements}
    </div>
  )
}
