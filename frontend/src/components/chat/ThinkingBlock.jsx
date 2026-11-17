import React, { useState, useMemo } from 'react'

/**
 * Sanitizes input into clean, safe user-facing activity milestones.
 * Strips raw model scratchpads, internal prompts, and raw JSON arguments.
 */
function sanitizeActivityMilestones(rawText) {
  if (!rawText || typeof rawText !== 'string') return []

  const lines = rawText.split('\n').map(l => l.trim()).filter(Boolean)
  const milestones = []

  for (const line of lines) {
    const lower = line.toLowerCase()

    // 1. Filter out private scratchpads / internal prompt fragments
    if (
      lower.startsWith('however,') ||
      lower.startsWith('but maybe') ||
      lower.startsWith('let\'s ') ||
      lower.startsWith('lets ') ||
      lower.startsWith('we have ') ||
      lower.startsWith('i should ') ||
      lower.startsWith('i need to ') ||
      lower.includes('chain-of-thought') ||
      lower.includes('internal prompt') ||
      lower.includes('secret') ||
      lower.includes('token')
    ) {
      continue
    }

    // 2. Map tool act calls into clean user-facing milestones
    if (lower.startsWith('tool:') || lower.startsWith('executing')) {
      if (lower.includes('task') || lower.includes('deadline') || lower.includes('coursework') || lower.includes('hackathon')) {
        milestones.push('Retrieving relevant tasks & deadlines')
      } else if (lower.includes('schedule') || lower.includes('calendar') || lower.includes('feasibility') || lower.includes('conflict')) {
        milestones.push('Checking upcoming deadlines & schedule')
      } else if (lower.includes('web')) {
        milestones.push('Searching reference documentation')
      } else if (lower.includes('note') || lower.includes('code') || lower.includes('context') || lower.includes('project')) {
        milestones.push('Reviewing relevant context')
      } else {
        milestones.push('Executing action')
      }
      continue
    }

    // 3. Map critic / verification
    if (lower.includes('critic') || lower.includes('verify')) {
      milestones.push('Verifying plan constraints')
      continue
    }

    // 4. Clean "Thinking:" prefix
    if (lower.startsWith('thinking:')) {
      const rest = line.substring(9).trim()
      milestones.push(rest || 'Understanding your request')
      continue
    }

    // 5. If it's a clean known milestone or short safe label
    if (
      lower.includes('understanding') ||
      lower.includes('retrieving') ||
      lower.includes('checking') ||
      lower.includes('reviewing') ||
      lower.includes('preparing') ||
      lower.includes('analysis complete') ||
      lower.includes('analyz')
    ) {
      milestones.push(line.replace(/^[•\-*]\s*/, '').trim())
      continue
    }

    // 6. Generic "Thinking..."
    if (lower === 'thinking...' || lower === 'thinking') {
      milestones.push('Understanding your request')
      continue
    }
  }

  // Deduplicate consecutive identical milestones
  const deduped = []
  for (const m of milestones) {
    if (deduped.length === 0 || deduped[deduped.length - 1] !== m) {
      deduped.push(m)
    }
  }

  return deduped
}

/**
 * Polished, user-facing Activity Indicator component.
 * Replaces raw chain-of-thought and tool parameter dumps with a clean status pill
 * and optional expandable milestone checklist.
 */
export default function ThinkingBlock({ thought, status, isLive = false }) {
  const [isOpen, setIsOpen] = useState(false)

  const milestones = useMemo(() => sanitizeActivityMilestones(thought), [thought])

  // Resolve user-facing activity label
  const activeLabel = useMemo(() => {
    if (status?.label) {
      if (/continuing response/i.test(status.label)) {
        return 'Finishing the answer…'
      }
      return status.label
    }
    if (status?.stage === 'searching') return 'Searching the web…'
    if (status?.stage === 'reading_sources') return 'Verifying official sources…'
    if (status?.stage === 'reasoning') return 'Analyzing…'
    if (status?.stage === 'generating') return 'Generating response…'
    if (milestones && milestones.length > 0) return milestones[milestones.length - 1]
    return 'Understanding your request…'
  }, [status, milestones])

  if (!milestones || milestones.length === 0) {
    if (!isLive) return null
    return (
      <div className="thinking-pill-container" role="status" aria-live="polite">
        <div className="thinking-wave-dots">
          <span className="thinking-wave-dot" />
          <span className="thinking-wave-dot" />
          <span className="thinking-wave-dot" />
        </div>
        <span className="thinking-shimmer-text">{activeLabel}</span>
      </div>
    )
  }

  return (
    <div style={{
      marginBottom: '10px',
      borderRadius: 'var(--radius-btn, 6px)',
      border: '1px solid var(--border)',
      background: 'var(--bg-card-soft)',
      overflow: 'hidden',
      fontSize: '12px',
      transition: 'all 0.15s ease',
    }}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 12px',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          color: 'var(--text-secondary)',
          fontWeight: '500',
          fontSize: '12px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
          {isLive ? (
            <div className="thinking-wave-dots">
              <span className="thinking-wave-dot" />
              <span className="thinking-wave-dot" />
              <span className="thinking-wave-dot" />
            </div>
          ) : (
            <span style={{ color: 'var(--accent, #f5a623)', fontSize: '11px' }}>✦</span>
          )}
          <span className={isLive ? 'thinking-shimmer-text' : ''}>
            {isLive ? `${activeLabel}` : `Activity: ${milestones.length} step${milestones.length > 1 ? 's' : ''} completed`}
          </span>
        </div>
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{
            transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.15s ease',
          }}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {isOpen && (
        <div style={{
          padding: '8px 12px',
          borderTop: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
          background: 'var(--bg-card)',
        }}>
          {milestones.map((m, idx) => {
            const isLast = idx === milestones.length - 1 && isLive
            return (
              <div key={idx} style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                fontSize: '12px',
                color: isLast ? 'var(--text-primary)' : 'var(--text-secondary)',
              }}>
                <span style={{
                  color: isLast ? 'var(--accent, #f5a623)' : 'var(--domain-code, #1c8a62)',
                  display: 'inline-flex',
                  alignItems: 'center',
                }}>
                  {isLast ? (
                    <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'currentColor' }} />
                  ) : (
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  )}
                </span>
                <span>{m}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
