import React from 'react'
import { Star, DollarSign, Calendar, ExternalLink } from 'lucide-react'

function isCleanString(val) {
  if (!val) return false
  const s = String(val).trim().toLowerCase()
  return s !== '' && s !== 'nan' && s !== 'null' && s !== 'undefined' && s !== 'none' && s !== 'n/a'
}

export default function RadarOpportunityCard({
  opportunity,
  onOpenDetail,
  onToggleSave,
  onUpdateAppStatus: _onUpdateAppStatus,
  onApply: _onApply,
}) {
  const {
    id,
    company_name,
    role_title,
    location,
    work_arrangement,
    current_status,
    official_source_confirmed,
    sources = [],
    eligibility_classification,
    eligibility_explanation,
    official_application_url,
    canonical_url,
    prediction,
    is_saved,
    application_status,
    last_verified_at,
    posted_at,
    confirmed_open_date,
    compensation,
    requirements,
  } = opportunity

  // Rectangular Status Label (At most 2 compact labels on top row)
  const getStatusBadge = () => {
    switch (current_status) {
      case 'OPEN_CONFIRMED':
        return {
          label: 'Verified Open',
          bg: 'rgba(28, 138, 98, 0.08)',
          text: 'var(--domain-code, #1c8a62)',
          border: 'rgba(28, 138, 98, 0.25)',
        }
      case 'UPCOMING_CONFIRMED':
      case 'ANNOUNCED':
        return {
          label: 'Upcoming Confirmed',
          bg: 'rgba(47, 100, 200, 0.08)',
          text: 'var(--domain-coursework, #2f64c8)',
          border: 'rgba(47, 100, 200, 0.25)',
        }
      case 'CLOSED_CONFIRMED':
        return {
          label: 'Closed',
          bg: 'var(--bg-card-soft, #f2eee6)',
          text: 'var(--text-muted, #5f5a52)',
          border: 'var(--border, #e6e1d6)',
        }
      default:
        return {
          label: 'Needs Verification',
          bg: 'var(--bg-card-soft, #f2eee6)',
          text: 'var(--text-secondary, #3d3a35)',
          border: 'var(--border, #e6e1d6)',
        }
    }
  }

  // Rectangular Eligibility Match Label
  const getEligibilityBadge = () => {
    switch (eligibility_classification) {
      case 'ELIGIBLE':
        return {
          label: 'Confirmed Match',
          bg: 'rgba(28, 138, 98, 0.08)',
          text: 'var(--domain-code, #1c8a62)',
          border: 'rgba(28, 138, 98, 0.25)',
        }
      case 'POTENTIAL_MATCH':
      case 'POTENTIALLY_ELIGIBLE':
        return {
          label: 'Possible Match',
          bg: 'rgba(245, 166, 35, 0.1)',
          text: 'var(--brand-dark, #b47507)',
          border: 'rgba(245, 166, 35, 0.3)',
        }
      case 'INELIGIBLE':
        return {
          label: 'Likely Ineligible',
          bg: 'var(--danger-bg, #fdeaea)',
          text: 'var(--danger-text, #b91c1c)',
          border: 'rgba(185, 28, 28, 0.25)',
        }
      case 'INSUFFICIENT_INFORMATION':
      default:
        return {
          label: 'Eligibility Unconfirmed',
          bg: 'var(--bg-card-soft, #f2eee6)',
          text: 'var(--text-muted, #5f5a52)',
          border: 'var(--border, #e6e1d6)',
        }
    }
  }

  const statusBadge = getStatusBadge()
  const eligBadge = getEligibilityBadge()

  // Guard against malformed values
  const cleanCompany = isCleanString(company_name) ? company_name.trim() : 'Company'
  const cleanRole = isCleanString(role_title) ? role_title.trim() : 'Internship Opportunity'
  const cleanLocation = isCleanString(location) ? location.trim() : null
  const cleanCompensation = isCleanString(compensation) ? compensation.trim() : null
  const cleanArrangement = isCleanString(work_arrangement) ? work_arrangement.trim() : 'unspecified'

  // Surface restrictions near the title
  const restrictions = []
  if (requirements) {
    if (requirements.eligible_graduation_years && requirements.eligible_graduation_years.length > 0) {
      restrictions.push(`Batch: ${requirements.eligible_graduation_years.join('/')}`)
    }
    if (requirements.eligible_academic_years && requirements.eligible_academic_years.length > 0) {
      restrictions.push(`Year: ${requirements.eligible_academic_years.join('/')}`)
    }
    if (requirements.eligible_degree_types && requirements.eligible_degree_types.length > 0) {
      restrictions.push(`Degree: ${requirements.eligible_degree_types.join('/')}`)
    }
    if (requirements.no_active_backlogs === true) {
      restrictions.push('0 Active Backlogs')
    }
    if (requirements.work_auth_required === true && opportunity.country && opportunity.country.toLowerCase() !== 'india') {
      restrictions.push(`Requires ${opportunity.country} Work Auth`)
    }
    if (requirements.eligible_countries && requirements.eligible_countries.length > 0) {
      restrictions.push(`Location: ${requirements.eligible_countries.join('/')}`)
    }
  }

  // Format distinct dates: posting date vs verification date
  const rawPostingDate = posted_at || confirmed_open_date
  const formattedPosted = rawPostingDate
    ? new Date(rawPostingDate).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    : null

  const formattedVerified = last_verified_at
    ? new Date(last_verified_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    : null

  const primarySource = sources.length > 0
    ? sources[0].source_name
    : (official_source_confirmed ? 'Official Careers Site' : null)

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
        borderRadius: 'var(--radius-card, 8px)',
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
          {/* Label 1: Status Label (Rectangular) */}
          <span
            style={{
              padding: '2px 8px',
              borderRadius: '4px',
              fontSize: '11px',
              fontWeight: 600,
              letterSpacing: '0.2px',
              background: statusBadge.bg,
              color: statusBadge.text,
              border: `1px solid ${statusBadge.border}`,
            }}
          >
            ● {statusBadge.label}
          </span>

          {/* Label 2: Eligibility Match Label (Rectangular) */}
          <span
            style={{
              padding: '2px 8px',
              borderRadius: '4px',
              fontSize: '11px',
              fontWeight: 600,
              letterSpacing: '0.2px',
              background: eligBadge.bg,
              color: eligBadge.text,
              border: `1px solid ${eligBadge.border}`,
            }}
          >
            {eligBadge.label}
          </span>
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
          {cleanRole}
        </h3>

        {/* Surface important job restrictions near the title */}
        {restrictions.length > 0 && (
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', margin: '4px 0 6px 0' }}>
            {restrictions.map((resText, idx) => (
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

        {/* Company, Work Arrangement, and Location */}
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
          <span style={{ fontWeight: 600 }}>{cleanCompany}</span>
          <span>•</span>
          <span style={{ textTransform: 'capitalize' }}>{cleanArrangement}</span>
          {cleanLocation && (
            <>
              <span>•</span>
              <span style={{ fontSize: '12px' }}>{cleanLocation}</span>
            </>
          )}
        </div>
      </div>

      {/* Validated Compensation Display */}
      {cleanCompensation && (
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
          <span>{cleanCompensation}</span>
        </div>
      )}

      {/* Grounded Concise Eligibility Result */}
      {eligibility_explanation && (
        <div
          style={{
            fontSize: '12px',
            color: 'var(--text-secondary, #3d3a35)',
            background: 'var(--bg-card-soft, #f2eee6)',
            padding: '8px 10px',
            borderRadius: '4px',
            marginBottom: '10px',
            lineHeight: 1.4,
            borderLeft: `3px solid ${eligBadge.border}`,
          }}
        >
          {eligibility_explanation}
        </div>
      )}

      {/* Historical Window Forecast (if upcoming/announced) */}
      {current_status !== 'OPEN_CONFIRMED' && prediction?.estimated_open_window && (
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
        {/* Distinguish Posting Date from Last Checked Date */}
        <div style={{ fontSize: '11px', color: 'var(--text-muted, #5f5a52)', display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <div>
            {formattedPosted ? `Posted: ${formattedPosted}` : 'Posting date unrecorded'}
            {formattedVerified && ` • Checked: ${formattedVerified}`}
          </div>
          {primarySource && (
            <div style={{ fontSize: '10px', color: 'var(--text-muted, #5f5a52)' }}>
              Source: {primarySource}
            </div>
          )}
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {/* In-app Details Action */}
          <button
            type="button"
            onClick={() => onOpenDetail(opportunity)}
            style={{
              padding: '6px 12px',
              borderRadius: 'var(--radius-btn, 6px)',
              border: '1px solid var(--border, #e6e1d6)',
              background: 'var(--bg-card-soft, #f2eee6)',
              color: 'var(--text-primary, #1b1a17)',
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            View details
          </button>

          {/* Validated External Original Listing Action */}
          {hasValidExternalUrl ? (
            <a
              href={originalUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px',
                padding: '6px 12px',
                borderRadius: 'var(--radius-btn, 6px)',
                background: 'var(--brand, #f5a623)',
                color: 'var(--accent-text, #1b1a17)',
                border: 'none',
                fontSize: '12px',
                fontWeight: 600,
                textDecoration: 'none',
                cursor: 'pointer',
              }}
              title="Open external original job posting in a new tab"
            >
              <span>Open original listing</span>
              <ExternalLink size={12} strokeWidth={2} />
            </a>
          ) : (
            <button
              type="button"
              disabled
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px',
                padding: '6px 12px',
                borderRadius: 'var(--radius-btn, 6px)',
                background: 'var(--bg-card-soft, #f2eee6)',
                color: 'var(--text-muted, #5f5a52)',
                border: '1px solid var(--border, #e6e1d6)',
                fontSize: '12px',
                fontWeight: 500,
                cursor: 'not-allowed',
                opacity: 0.6,
              }}
              title="Original listing URL unavailable"
            >
              <span>Open original listing</span>
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
