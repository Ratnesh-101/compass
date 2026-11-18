import React from 'react'
import { descriptionBlocks } from './radarDisplay'

function Segments({ segments }) {
  return segments.map((s, i) => (s.bold ? <strong key={i}>{s.text}</strong> : <React.Fragment key={i}>{s.text}</React.Fragment>))
}

/** Renders a job description as headings, bullets and paragraphs. No raw markdown symbols reach the screen. */
export default function RadarDescription({ text }) {
  const blocks = descriptionBlocks(text)
  if (blocks.length === 0) return null
  const out = []
  let bullets = []
  const flush = key => {
    if (bullets.length) {
      out.push(
        <ul key={`ul-${key}`} style={{ margin: '4px 0 10px 18px', padding: 0 }}>
          {bullets.map((b, i) => (
            <li key={i}>
              <Segments segments={b.segments} />
            </li>
          ))}
        </ul>,
      )
      bullets = []
    }
  }
  blocks.forEach((blk, i) => {
    if (blk.type === 'bullet') {
      bullets.push(blk)
      return
    }
    flush(i)
    if (blk.type === 'heading') {
      out.push(
        <h5 key={i} style={{ fontSize: '13px', fontWeight: 700, margin: '12px 0 4px', color: 'var(--text-primary, #1b1a17)' }}>
          <Segments segments={blk.segments} />
        </h5>,
      )
    } else {
      out.push(
        <p key={i} style={{ margin: '0 0 8px' }}>
          <Segments segments={blk.segments} />
        </p>,
      )
    }
  })
  flush('end')
  return <div style={{ fontSize: '13px', color: 'var(--text-secondary, #3d3a35)', lineHeight: 1.6 }}>{out}</div>
}
