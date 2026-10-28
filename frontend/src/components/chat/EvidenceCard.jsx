import React from 'react'
import { getSafeHttpUrl } from '../../utils/safeUrl.js'

/**
 * EvidenceCard — Renders verifiable source claims, domain authority tiers,
 * local-time deadline normalized schedules, and verbatim citations directly
 * within chat assistant answers with full dark mode and mobile responsiveness.
 */
export default function EvidenceCard({ evidence }) {
  if (!evidence || (!evidence.claim && !evidence.claim_checked && !evidence.source_url && !evidence.items && !evidence.sources)) {
    return null
  }

  const items = evidence.items || (Array.isArray(evidence) ? evidence : (evidence.sources || [evidence]))
  const overallVerdict = evidence.verdict || (items[0] && items[0].verdict) || 'UNVERIFIED'
  const claimChecked = evidence.claim_checked || evidence.claim || (items[0] && items[0].claim) || ''
  const verifiedAt = evidence.verified_at || ''
  const limitations = evidence.limitations || []

  const getVerdictStyle = (verdict) => {
    switch ((verdict || '').toUpperCase()) {
      case 'VERIFIED':
        return {
          bg: 'rgba(19, 115, 51, 0.15)',
          text: '#2e7d32',
          border: 'rgba(46, 125, 50, 0.35)',
          label: 'VERIFIED',
        }
      case 'PARTIALLY_VERIFIED':
        return {
          bg: 'rgba(230, 81, 0, 0.15)',
          text: '#e65100',
          border: 'rgba(230, 81, 0, 0.35)',
          label: 'PARTIALLY VERIFIED',
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
      case 'CONTRADICTED':
        return {
          bg: 'rgba(197, 34, 31, 0.18)',
          text: '#c62828',
          border: 'rgba(198, 40, 40, 0.45)',
          label: 'CONTRADICTED',
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
    const tier = item.authority_tier || item.authority
    switch (tier) {
      case 'tier_1_official':
      case 'Official Organizer':
        return { label: 'Official Organizer', color: '#1a73e8' }
      case 'tier_2_technical':
      case 'Platform / Technical Host':
        return { label: 'Platform / Technical Host', color: '#9334e6' }
      default:
        return { label: 'General Web', color: 'var(--text-secondary, #5f6368)' }
    }
  }

  const overallStyle = getVerdictStyle(overallVerdict)

  return (
    <div
      style={{
        marginTop: '12px',
        padding: '12px 14px',
        borderRadius: '10px',
        border: `1px solid ${overallStyle.border}`,
        background: 'var(--bg-card, var(--bg-card-soft, rgba(255,255,255,0.02)))',
        display: 'flex',
        flexDirection: 'column',
        gap: '10px',
      }}
    >
      {/* Header bar: Badge + Timestamp */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '11px', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-secondary)' }}>
            🔍 Tavily Verification
          </span>
          <span
            style={{
              padding: '2px 8px',
              borderRadius: '12px',
              fontSize: '10.5px',
              fontWeight: '700',
              background: overallStyle.bg,
              color: overallStyle.text,
              border: `1px solid ${overallStyle.border}`,
            }}
          >
            {overallStyle.label}
          </span>
        </div>
        {verifiedAt && (
          <span style={{ fontSize: '10.5px', color: 'var(--text-muted, var(--text-secondary))' }}>
            Verified on: {verifiedAt}
          </span>
        )}
      </div>

      {/* Claim checked */}
      {claimChecked && (
        <div style={{ fontSize: '12.5px', color: 'var(--text-primary)', lineHeight: '1.4' }}>
          <span style={{ fontWeight: '600', color: 'var(--text-secondary)' }}>Claim: </span>
          <span>{claimChecked}</span>
        </div>
      )}

      {/* Evidence Sources List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {items.map((item, idx) => {
          const itemVerdict = item.verdict || overallVerdict
          const vStyle = getVerdictStyle(itemVerdict)
          const tierBadge = getTierBadge(item)
          const quote = item.display_quote || item.exact_quote || item.verbatim_quote || item.evidence
          const localDeadline = item.local_deadline_ist
          const sUrl = getSafeHttpUrl(item.source_url || item.url)

          return (
            <div
              key={idx}
              style={{
                padding: '8px 12px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                background: 'var(--bg-sidebar, rgba(0,0,0,0.02))',
                display: 'flex',
                flexDirection: 'column',
                gap: '5px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                  <span
                    style={{
                      padding: '1px 6px',
                      borderRadius: '8px',
                      fontSize: '10px',
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
                {sUrl && (
                  <a
                    href={sUrl}
                    target="_blank"
                    rel="noreferrer noopener"
                    style={{
                      fontSize: '11px',
                      color: 'var(--coursework, #1a73e8)',
                      textDecoration: 'underline',
                      maxWidth: '240px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    🔗 {sUrl.replace(/^https?:\/\//, '').replace(/\/$/, '')}
                  </a>
                )}
              </div>

              {localDeadline && (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '3px 8px',
                    borderRadius: '4px',
                    background: 'rgba(26, 115, 232, 0.08)',
                    border: '1px solid rgba(26, 115, 232, 0.2)',
                    fontSize: '11px',
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
                    margin: '3px 0 0 0',
                    padding: '4px 8px',
                    borderLeft: '3px solid var(--border)',
                    fontSize: '11.5px',
                    fontStyle: 'italic',
                    color: 'var(--text-secondary)',
                    background: 'var(--bg-card, rgba(255,255,255,0.03))',
                    borderRadius: '0 4px 4px 0',
                    lineHeight: '1.4',
                  }}
                >
                  "{quote}"
                </blockquote>
              )}
            </div>
          )
        })}
      </div>

      {/* Limitations note */}
      {Array.isArray(limitations) && limitations.length > 0 && (
        <div style={{ fontSize: '11px', color: 'var(--text-secondary)', fontStyle: 'italic', borderTop: '1px dashed var(--border)', paddingTop: '6px' }}>
          <strong>Limitations:</strong> {limitations.join(' ')}
        </div>
      )}
    </div>
  )
}
