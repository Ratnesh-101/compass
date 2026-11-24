import React from 'react'

/**
 * Kind display mapping: maps backend check kinds to plain labels.
 */
const KIND_LABELS = {
  education: 'School',
  employer: 'Employer',
  certification: 'Certificate',
  award: 'Award',
  publication: 'Publication',
  link: 'Link',
  self_reported: 'Your own work',
}

function getKindLabel(kind) {
  if (!kind) return 'Claim'
  const key = String(kind).toLowerCase().trim()
  return KIND_LABELS[key] || (key.charAt(0).toUpperCase() + key.slice(1))
}

function safeHref(url) {
  if (typeof url !== 'string') return null
  const trimmed = url.trim()
  if (/^https?:\/\//i.test(trimmed)) {
    try {
      const parsed = new URL(trimmed)
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        return parsed.href
      }
    } catch {
      return null
    }
  }
  return null
}

function getHostName(url) {
  try {
    const parsed = new URL(url)
    return parsed.hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

function truncate(text, maxLen = 42) {
  if (!text) return ''
  const trimmed = text.trim()
  return trimmed.length > maxLen ? `${trimmed.slice(0, maxLen - 1)}…` : trimmed
}

function formatCheckedTime(checkedAt) {
  if (!checkedAt) return 'Checked just now'
  try {
    const d = new Date(checkedAt)
    if (isNaN(d.getTime())) return 'Checked just now'
    return `Checked just now (${d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })})`
  } catch {
    return 'Checked just now'
  }
}

export default function ClaimVerificationCard({ report, loading, onDismiss, headingRef }) {
  if (!report && !loading) return null

  if (loading) {
    return (
      <div
        role="status"
        aria-live="polite"
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: '12px',
          padding: '18px',
          marginBottom: '16px',
          boxShadow: 'var(--shadow-sm)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
          <span
            aria-hidden="true"
            style={{
              display: 'inline-block',
              width: '16px',
              height: '16px',
              borderRadius: '50%',
              border: '2px solid var(--primary, #f5a623)',
              borderRightColor: 'transparent',
              animation: 'claimCardSpin 0.75s linear infinite',
            }}
          />
          <style>{`@keyframes claimCardSpin { to { transform: rotate(360deg); } }`}</style>
          <span style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)' }}>
            Looking up your schools, employers and links...
          </span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ height: '12px', width: '85%', background: 'var(--border)', borderRadius: '4px', opacity: 0.6 }} />
          <div style={{ height: '12px', width: '65%', background: 'var(--border)', borderRadius: '4px', opacity: 0.4 }} />
        </div>
      </div>
    )
  }

  const checks = Array.isArray(report.checks) ? report.checks : []
  const isFound = (c) => c.status === 'found' && c.kind !== 'self_reported'
  const isNotFound = (c) => c.status === 'not_found' && c.kind !== 'self_reported'

  const foundItems = checks.filter(isFound)
  const notFoundItems = checks.filter(isNotFound)
  const cannotCheckItems = checks.filter(c => !isFound(c) && !isNotFound(c))

  const groups = [
    {
      key: 'found',
      title: 'Found online',
      icon: '✓',
      badgeBg: 'rgba(22, 101, 52, 0.1)',
      badgeColor: '#166534',
      items: foundItems,
    },
    {
      key: 'not_found',
      title: 'Not found',
      icon: '?',
      badgeBg: 'rgba(180, 83, 9, 0.1)',
      badgeColor: '#92400e',
      items: notFoundItems,
    },
    {
      key: 'cannot_check',
      title: 'Could not be checked',
      icon: '—',
      badgeBg: 'rgba(100, 116, 139, 0.1)',
      badgeColor: 'var(--text-secondary)',
      items: cannotCheckItems,
    },
  ]

  return (
    <div
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: '12px',
        padding: '18px',
        marginBottom: '16px',
        boxShadow: 'var(--shadow-sm)',
        display: 'flex',
        flexDirection: 'column',
        gap: '14px',
        width: '100%',
        boxSizing: 'border-box',
      }}
    >
      {/* Header bar: summary heading, checked time, dismiss button */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '10px' }}>
        <div style={{ flex: '1 1 200px' }}>
          <h3
            ref={headingRef}
            tabIndex={-1}
            aria-live="polite"
            style={{
              margin: '0 0 4px 0',
              fontSize: '15px',
              fontWeight: '700',
              color: 'var(--text-primary)',
              lineHeight: 1.35,
              outline: 'none',
            }}
          >
            {report.summary || 'Claim verification completed'}
          </h3>
          <span style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
            {formatCheckedTime(report.checked_at)}
          </span>
        </div>

        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss claim verification"
            style={{
              background: 'transparent',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              padding: '4px 10px',
              fontSize: '12px',
              fontWeight: '600',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            Dismiss
          </button>
        )}
      </div>

      {/* Notice line if provided by backend */}
      {report.notice && (
        <div
          role="note"
          style={{
            background: 'rgba(245, 166, 35, 0.12)',
            border: '1px solid rgba(245, 166, 35, 0.35)',
            borderRadius: '8px',
            padding: '9px 12px',
            fontSize: '12.5px',
            color: 'var(--text-primary)',
            lineHeight: 1.4,
            display: 'flex',
            alignItems: 'flex-start',
            gap: '8px',
          }}
        >
          <span aria-hidden="true" style={{ color: 'var(--amber-text, #b45309)', fontWeight: '700' }}>ℹ</span>
          <span>{report.notice}</span>
        </div>
      )}

      {/* Grouped checks: Found online, Not found, Could not be checked */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        {groups.map((group) => {
          if (group.items.length === 0) return null
          return (
            <div key={group.key} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {/* Group header with both icon and text label */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '4px',
                    fontSize: '12px',
                    fontWeight: '700',
                    padding: '2px 8px',
                    borderRadius: '6px',
                    background: group.badgeBg,
                    color: group.badgeColor,
                  }}
                >
                  <span aria-hidden="true">{group.icon}</span>
                  <span>{group.title}</span>
                  <span style={{ opacity: 0.8 }}>({group.items.length})</span>
                </span>
              </div>

              {/* Rows */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {group.items.map((check, idx) => {
                  const evidenceList = Array.isArray(check.evidence) ? check.evidence.slice(0, 3) : []
                  return (
                    <div
                      key={idx}
                      style={{
                        background: 'var(--bg-card-soft, #faf9f6)',
                        border: '1px solid var(--border)',
                        borderRadius: '8px',
                        padding: '10px 12px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '5px',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: '6px' }}>
                        <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)', flex: '1 1 200px', wordBreak: 'break-word' }}>
                          {check.text}
                        </span>
                        <span
                          style={{
                            fontSize: '11px',
                            fontWeight: '600',
                            padding: '2px 6px',
                            borderRadius: '4px',
                            background: 'var(--border)',
                            color: 'var(--text-secondary)',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {getKindLabel(check.kind)}
                        </span>
                      </div>

                      {/* Server note */}
                      {check.note && (
                        <div style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.35 }}>
                          {check.note}
                        </div>
                      )}

                      {/* Not found helpful hint (never calling claim untrue) */}
                      {group.key === 'not_found' && (
                        <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', lineHeight: 1.3 }}>
                          💡 Check the spelling, or add a public link as proof.
                        </div>
                      )}

                      {/* Evidence links (up to 3, http/https only) */}
                      {evidenceList.length > 0 && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '3px' }}>
                          {evidenceList.map((item, eIdx) => {
                            const rawUrl = item?.url || item?.href || ''
                            const href = safeHref(rawUrl)
                            if (!href) return null
                            const host = getHostName(href)
                            const title = item.title ? truncate(item.title) : host
                            return (
                              <a
                                key={eIdx}
                                href={href}
                                target="_blank"
                                rel="noopener noreferrer"
                                title={item.title || href}
                                style={{
                                  fontSize: '11.5px',
                                  color: 'var(--primary, #2563eb)',
                                  textDecoration: 'underline',
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '3px',
                                  maxWidth: '100%',
                                  wordBreak: 'break-all',
                                }}
                              >
                                <span>🔗 {host}: {title}</span>
                              </a>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
