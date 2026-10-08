import React from 'react'

/**
 * EvidenceCard — Renders verifiable source claims, domain authority tiers,
 * local-time deadline normalized schedules, and verbatim citations directly
 * within chat assistant answers with full dark mode and mobile responsiveness.
 */
export default function EvidenceCard({ evidence }) {
  if (!evidence || (!evidence.claim && !evidence.source_url && !evidence.items)) {
    return null
  }

  const items = evidence.items || (Array.isArray(evidence) ? evidence : [evidence])
  if (items.length === 0) {
    return null
  }

  const getVerdictStyle = (verdict) => {
    switch ((verdict || '').toUpperCase()) {
      case 'VERIFIED':
        return {
          bg: 'rgba(19, 115, 51, 0.15)',
          text: '#2e7d32',
          border: 'rgba(46, 125, 50, 0.35)',
          label: 'VERIFIED',
        }
      case 'STALE':
        return {
          bg: 'rgba(176, 96, 0, 0.15)',
          text: '#e65100',
          border: 'rgba(230, 81, 0, 0.35)',
          label: 'STALE',
        }
      case 'CONFLICTING':
        return {
          bg: 'rgba(197, 34, 31, 0.15)',
          text: '#c62828',
          border: 'rgba(198, 40, 40, 0.35)',
          label: 'CONFLICTING',
        }
      default:
        return {
          bg: 'var(--bg-secondary, rgba(95, 99, 104, 0.12))',
          text: 'var(--text-secondary, #5f6368)',
          border: 'var(--border, #dadce0)',
          label: 'UNVERIFIED',
        }
    }
  }

  const getTierBadge = (item) => {
    if (item.authority_badge === 'User-trusted source' || item.is_user_trusted) {
      return { label: 'User-trusted source', color: '#0f9d58' }
    }
    switch (item.authority_tier) {
      case 'tier_1_official':
        return { label: 'Official Organizer', color: '#1a73e8' }
      case 'tier_2_technical':
        return { label: 'Platform / Technical Host', color: '#9334e6' }
      default:
        return { label: 'General Web', color: 'var(--text-secondary, #5f6368)' }
    }
  }

  return (
    <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <div style={{ fontSize: '11px', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-secondary)' }}>
        🔍 Verified Research Evidence
      </div>
      {items.map((item, idx) => {
        const vStyle = getVerdictStyle(item.verdict)
        const tierBadge = getTierBadge(item)
        const quote = item.display_quote || item.exact_quote || item.verbatim_quote
        const localDeadline = item.local_deadline_ist

        return (
          <div
            key={idx}
            style={{
              padding: '10px 14px',
              borderRadius: '8px',
              border: `1px solid ${vStyle.border}`,
              background: 'var(--bg-card, var(--bg-card-soft, #fafafa))',
              display: 'flex',
              flexDirection: 'column',
              gap: '6px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                <span
                  style={{
                    padding: '2px 8px',
                    borderRadius: '12px',
                    fontSize: '10.5px',
                    fontWeight: '700',
                    background: vStyle.bg,
                    color: vStyle.text,
                    border: `1px solid ${vStyle.border}`,
                  }}
                >
                  {vStyle.label}
                </span>
                <span
                  style={{
                    fontSize: '11px',
                    fontWeight: '600',
                    color: tierBadge.color,
                  }}
                >
                  [{tierBadge.label}]
                </span>
              </div>
              {item.source_url && (
                <a
                  href={item.source_url}
                  target="_blank"
                  rel="noreferrer noopener"
                  style={{
                    fontSize: '11px',
                    color: 'var(--coursework, #1a73e8)',
                    textDecoration: 'none',
                    maxWidth: '220px',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  🔗 {item.source_url.replace(/^https?:\/\//, '')}
                </a>
              )}
            </div>

            {item.claim && (
              <div style={{ fontSize: '12.5px', fontWeight: '500', color: 'var(--text-primary)' }}>
                {item.claim}
              </div>
            )}

            {localDeadline && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '4px 8px',
                  borderRadius: '6px',
                  background: 'rgba(26, 115, 232, 0.08)',
                  border: '1px solid rgba(26, 115, 232, 0.2)',
                  fontSize: '11.5px',
                  fontWeight: '600',
                  color: 'var(--coursework, #1a73e8)',
                  width: 'fit-content',
                }}
              >
                🕒 Local Deadline: {localDeadline}
              </div>
            )}

            {quote && (
              <blockquote
                style={{
                  margin: '4px 0 0 0',
                  padding: '4px 10px',
                  borderLeft: '3px solid var(--border)',
                  fontSize: '11.5px',
                  fontStyle: 'italic',
                  color: 'var(--text-secondary)',
                  background: 'var(--bg-sidebar, #f8f9fa)',
                  borderRadius: '0 4px 4px 0',
                }}
              >
                "{quote}"
              </blockquote>
            )}
          </div>
        )
      })}
    </div>
  )
}
