import React, { useState } from 'react'
import { Sparkles, Loader2 } from 'lucide-react'
import { prepareTopMatches } from '../../api/careerApi'
import { summarizeTopMatchesResult } from '../../utils/careerFlowText'

const barStyle = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: '12px',
  flexWrap: 'wrap',
  padding: '12px 16px',
  marginBottom: '16px',
  borderRadius: 'var(--radius-card, 8px)',
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
}

const primaryButton = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: '8px',
  padding: '9px 18px',
  borderRadius: 'var(--radius-btn, 6px)',
  background: 'var(--brand)',
  color: 'var(--accent-text, #1b1a17)',
  border: 'none',
  fontWeight: 600,
  fontSize: '13px',
  cursor: 'pointer',
}

const linkButton = {
  background: 'transparent',
  border: 'none',
  padding: 0,
  color: 'var(--brand)',
  fontWeight: 600,
  fontSize: '13px',
  cursor: 'pointer',
  textDecoration: 'underline',
}

export default function TopMatchesBar({ hasProfile, hasMatches, onPrepared, onShowApplications, onGoToResume }) {
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState(null)

  const handleClick = async () => {
    setBusy(true)
    setOutcome(null)
    try {
      const result = await prepareTopMatches()
      const summary = summarizeTopMatchesResult(result)
      setOutcome(summary)
      if (summary.preparedCount > 0 && onPrepared) onPrepared(result)
    } catch (err) {
      setOutcome({ tone: 'error', message: err?.message || 'Could not prepare your top matches. Try again in a moment.', lines: [] })
    } finally {
      setBusy(false)
    }
  }

  if (!hasMatches && !outcome) return null

  return (
    <div data-testid="top-matches-bar" style={barStyle}>
      <div style={{ minWidth: '240px', flex: '1 1 320px' }}>
        <div style={{ fontWeight: 700, fontSize: '14px', color: 'var(--text-primary)' }}>
          Ready to apply?
        </div>
        <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
          Compass reads each job page, tailors your resume, writes a cover letter and adds an apply-by date to your Timeline. You review everything before you apply.
        </div>
        {outcome && (
          <div
            role="status"
            aria-live="polite"
            data-testid="top-matches-outcome"
            style={{ marginTop: '10px', fontSize: '13px', color: outcome.tone === 'error' ? '#b91c1c' : 'var(--text-primary)' }}
          >
            <div style={{ fontWeight: 600 }}>{outcome.message}</div>
            {outcome.lines.length > 0 && (
              <ul style={{ margin: '6px 0 0 0', paddingLeft: '18px', color: 'var(--text-secondary)' }}>
                {outcome.lines.map(line => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
            <div style={{ display: 'flex', gap: '14px', marginTop: '8px', flexWrap: 'wrap' }}>
              {outcome.preparedCount > 0 && onShowApplications && (
                <button type="button" style={linkButton} onClick={onShowApplications}>
                  See my applications
                </button>
              )}
              {outcome.needsResume && onGoToResume && (
                <button type="button" style={linkButton} onClick={onGoToResume}>
                  Go to My resume
                </button>
              )}
            </div>
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={handleClick}
        disabled={busy || !hasProfile}
        title={hasProfile ? 'Prepare applications for your three best matches' : 'Upload your resume first'}
        style={{ ...primaryButton, opacity: busy || !hasProfile ? 0.6 : 1, cursor: busy || !hasProfile ? 'not-allowed' : 'pointer' }}
      >
        {busy ? <Loader2 size={15} className="spin" aria-hidden="true" /> : <Sparkles size={15} aria-hidden="true" />}
        <span>{busy ? 'Preparing your top 3…' : 'Prepare my top 3 matches'}</span>
      </button>
    </div>
  )
}
