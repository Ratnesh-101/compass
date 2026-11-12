import React from 'react'
import { Star, DollarSign, Calendar, ExternalLink, Rocket } from 'lucide-react'
import { cleanOpportunity } from '../../utils/jobCardCleaner'
import { formatOpportunityVerifiedAge, needsRecheck } from '../../utils/radarFreshness'

export default function RadarOpportunityCard({
  opportunity,
  onOpenDetail,
  onToggleSave,
  onUpdateAppStatus: _onUpdateAppStatus,
  onApply,
}) {
  const {
    id,
    official_application_url,
    canonical_url,
    prediction,
    is_saved,
    application_status,
  } = opportunity || {}

  const cleaned = cleanOpportunity(opportunity)

  // Validate external application URL
  const originalUrl = official_application_url || canonical_url
  const hasValidExternalUrl = Boolean(
    originalUrl &&
    typeof originalUrl === 'string' &&
    /^https?:\/\//i.test(originalUrl.trim()) &&
    !originalUrl.toLowerCase().includes('javascript:')
  )

  return (
    <div
      className="radar-card"
      style={{
        display: 'flex',
        flexDirection: 'column',
        borderRadius: 'var(--radius-card, 6px)',
        background: 'var(--bg-card, #ffffff)',
        border: '1px solid var(--border, #e6e1d6)',
        boxShadow: 'var(--shadow-sm)',
        padding: '18px 20px',
        transition: 'transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease',
        position: 'relative',
        boxSizing: 'border-box',
      }}
    >
      {/* Top Row: Exactly at most two compact rectangular status labels + bookmark */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '10px',
          gap: '8px',
        }}
      >
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
          {/* Label 1: Status Label (Rectangular, 6px/4px radius) */}
          <span
            style={{
              padding: '2px 8px',
              borderRadius: '4px',
              fontSize: '11px',
              fontWeight: 600,
              letterSpacing: '0.2px',
              background: cleaned.verificationBadge.bg,
              color: cleaned.verificationBadge.text,
              border: `1px solid ${cleaned.verificationBadge.border}`,
            }}
          >
            ● {cleaned.verificationBadge.label}
          </span>

          {/* Label 2: Eligibility Match Label (Rectangular, 6px/4px radius) */}
          <span
            style={{
              padding: '2px 8px',
              borderRadius: '4px',
              fontSize: '11px',
              fontWeight: 600,
              letterSpacing: '0.2px',
              background: cleaned.eligibilityBadge.bg,
              color: cleaned.eligibilityBadge.text,
              border: `1px solid ${cleaned.eligibilityBadge.border}`,
            }}
          >
            {cleaned.eligibilityBadge.label}
          </span>

          {needsRecheck(opportunity) && (
            <span
              data-testid="needs-recheck-chip"
              title="Last checked more than 14 days ago. Confirm on the company site before applying."
              style={{
                padding: '2px 8px',
                borderRadius: '4px',
                fontSize: '11px',
                fontWeight: 600,
                background: 'rgba(245, 166, 35, 0.12)',
                color: 'var(--text-primary, #1b1a17)',
                border: '1px solid rgba(245, 166, 35, 0.35)',
              }}
            >
              Needs re-check
            </span>
          )}
        </div>

        {/* Bookmark Button */}
        <button
          type="button"
          onClick={() => onToggleSave(id, is_saved)}
          title={is_saved ? 'Remove from Watchlist' : 'Add to Watchlist'}
          aria-label={is_saved ? 'Remove from Watchlist' : 'Add to Watchlist'}
          style={{
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            padding: '4px',
            lineHeight: 1,
            color: is_saved ? 'var(--brand, #f5a623)' : 'var(--text-muted, #5f5a52)',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Star
            size={16}
            strokeWidth={1.8}
            fill={is_saved ? 'var(--brand, #f5a623)' : 'none'}
            color={is_saved ? 'var(--brand, #f5a623)' : 'var(--text-muted, #5f5a52)'}
          />
        </button>
      </div>

      {/* Role Title & Restrictions Header */}
      <div style={{ marginBottom: '8px' }}>
        <h3
          style={{
            fontSize: '16px',
            fontWeight: 600,
            color: 'var(--text-primary, #1b1a17)',
            margin: '0 0 4px 0',
            lineHeight: 1.3,
          }}
        >
          {cleaned.role}
        </h3>

        {/* Surface important job restrictions near the title (no separate Location: India tag) */}
        {cleaned.restrictions.length > 0 && (
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', margin: '4px 0 6px 0' }}>
            {cleaned.restrictions.map((resText, idx) => (
              <span
                key={idx}
                style={{
                  fontSize: '11px',
                  fontWeight: 500,
                  color: 'var(--text-secondary, #3d3a35)',
                  background: 'var(--bg-card-soft, #f2eee6)',
                  border: '1px solid var(--border, #e6e1d6)',
                  borderRadius: '4px',
                  padding: '1px 6px',
                }}
              >
                {resText}
              </span>
            ))}
          </div>
        )}

        {/* Company & Single Location Line */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            color: 'var(--text-secondary, #3d3a35)',
            fontSize: '13px',
            fontWeight: 500,
            flexWrap: 'wrap',
          }}
        >
          <span style={{ fontWeight: 600 }}>{cleaned.company}</span>
          <span>•</span>
          <span>{cleaned.locationLine}</span>
        </div>
      </div>

      {/* Validated Compensation Display */}
      {cleaned.salary && (
        <div
          style={{
            fontSize: '13px',
            color: 'var(--domain-code, #1c8a62)',
            fontWeight: 600,
            marginBottom: '8px',
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
          }}
        >
          <DollarSign size={13} strokeWidth={2} />
          <span>{cleaned.salary}</span>
        </div>
      )}

      {/* Grounded Concise Eligibility Result (Profile missing message moved to top banner) */}
      {cleaned.cleanedExplanation && (
        <div
          style={{
            fontSize: '12px',
            color: 'var(--text-secondary, #3d3a35)',
            background: 'var(--bg-card-soft, #f2eee6)',
            padding: '8px 10px',
            borderRadius: '4px',
            marginBottom: '10px',
            lineHeight: 1.4,
            borderLeft: `3px solid ${cleaned.eligibilityBadge.border}`,
          }}
        >
          {cleaned.cleanedExplanation}
        </div>
      )}

      {/* Historical Window Forecast (if upcoming/announced) */}
      {opportunity?.current_status !== 'OPEN_CONFIRMED' && prediction?.estimated_open_window && (
        <div
          style={{
            fontSize: '11px',
            color: 'var(--domain-coursework, #2f64c8)',
            background: 'rgba(47, 100, 200, 0.06)',
            padding: '5px 8px',
            borderRadius: '4px',
            marginBottom: '10px',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            border: '1px solid rgba(47, 100, 200, 0.2)',
          }}
        >
          <Calendar size={12} strokeWidth={1.8} />
          <span>
            <strong>Historical Window:</strong> {prediction.estimated_open_window} ({prediction.confidence} Confidence)
          </span>
        </div>
      )}

      {/* Tracking Pipeline State (if user is tracking) */}
      {application_status && (
        <div
          style={{
            fontSize: '12px',
            color: 'var(--text-secondary, #3d3a35)',
            fontWeight: 500,
            marginBottom: '10px',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
          }}
        >
          <span>Pipeline:</span>
          <span
            style={{
              textTransform: 'capitalize',
              background: 'var(--bg-card-soft, #f2eee6)',
              border: '1px solid var(--border, #e6e1d6)',
              padding: '1px 6px',
              borderRadius: '4px',
              fontSize: '11px',
              fontWeight: 600,
            }}
          >
            {application_status.replace(/_/g, ' ')}
          </span>
        </div>
      )}

      {/* Card Footer: Metadata Dates and Actions */}
      <div
        style={{
          marginTop: 'auto',
          paddingTop: '12px',
          borderTop: '1px solid var(--border-soft, #eee9de)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '8px',
        }}
      >
        {/* Single clean footer line: e.g. "Posted 23 Oct, checked 24 Oct via Glassdoor" */}
        <div style={{ fontSize: '11px', color: 'var(--text-muted, #5f5a52)' }}>
          {cleaned.footerLine}
          <div data-testid="verified-age">{formatOpportunityVerifiedAge(opportunity)}</div>
        </div>

        {/* Action Controls */}
        <div className="radar-card-actions">
          {!application_status && (
            <button
              type="button"
              onClick={() => onApply(opportunity)}
              className="radar-card-btn radar-card-btn-primary"
            >
              <Rocket size={14} strokeWidth={1.8} aria-hidden="true" />
              <span>Prepare Application</span>
            </button>
          )}
          <button
            type="button"
            onClick={() => onOpenDetail(opportunity)}
            className="radar-card-btn radar-card-btn-secondary"
          >
            {application_status ? 'View Progress' : 'View details'}
          </button>
          {hasValidExternalUrl && (
            <a
              href={originalUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="radar-card-btn radar-card-btn-secondary"
              title="Open original listing"
              aria-label="Open original listing"
            >
              <span>Open listing</span>
              <ExternalLink size={14} strokeWidth={1.8} aria-hidden="true" />
            </a>
          )}
        </div>
      </div>
    </div>
  )
}
