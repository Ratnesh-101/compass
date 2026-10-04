import React from 'react'

/**
 * EvidenceCard — Renders verifiable source claims, domain authority tiers,
 * and verbatim citations directly within chat assistant answers.
 */
export default function EvidenceCard({ evidence }) {
  if (!evidence || (!evidence.claim && !evidence.source_url && !evidence.items)) {
    return null
  }

  const items = evidence.items || (Array.isArray(evidence) ? evidence : [evidence])

  const getVerdictStyle = (verdict) => {
    switch ((verdict || '').toUpperCase()) {
      case 'VERIFIED':
        return { bg: '#e6f4ea', text: '#137333', border: '#ceead6', label: 'VERIFIED' }
      case 'STALE':
        return { bg: '#fef7e0', text: '#b06000', border: '#feefc3', label: 'STALE' }
      case 'CONFLICTING':
        return { bg: '#fce8e6', text: '#c5221f', border: '#fad2cf', label: 'CONFLICTING' }
      default:
        return { bg: '#f1f3f4', text: '#5f6368', border: '#dadce0', label: 'UNVERIFIED' }
    }
  }

  const getTierBadge = (tier) => {
    switch (tier) {
      case 'tier_1_official':
        return { label: 'Official Organizer', color: '#1a73e8' }
      case 'tier_2_technical':
        return { label: 'Platform / Technical Host', color: '#9334e6' }
      default:
        return { label: 'General Web', color: '#5f6368' }
    }
  }

  return (
    <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <div style={{ fontSize: '11px', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-secondary)' }}>
        🔍 Verified Research Evidence
      </div>
      {items.map((item, idx) => {
        const vStyle = getVerdictStyle(item.verdict)
        const tierBadge = getTierBadge(item.authority_tier)

        return (
          <div
            key={idx}
            style={{
              padding: '10px 14px',
              borderRadius: '8px',
              border: `1px solid ${vStyle.border}`,
              background: 'var(--bg-card-soft, #fafafa)',
              display: 'flex',
              flexDirection: 'column',
              gap: '6px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
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

            {item.verbatim_quote && (
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
                "{item.verbatim_quote}"
              </blockquote>
            )}
          </div>
        )
      })}
    </div>
  )
}
