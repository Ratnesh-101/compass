import React, { useState, useEffect } from 'react'
import { markApplied } from '../../api/careerApi'

export default function ReturnSubmissionPrompt({ onSubmissionConfirmed }) {
  const [pendingPrompt, setPendingPrompt] = useState(null)
  const [confirming, setConfirming] = useState(false)
  const [confirmError, setConfirmError] = useState(null)

  useEffect(() => {
    const handleCheckReturn = () => {
      if (document.visibilityState !== 'visible') return

      try {
        const stored = window.sessionStorage?.getItem('pending_submission_check')
        if (!stored) return

        const parsed = JSON.parse(stored)
        // If pending return and opened more than 3 seconds ago (to avoid immediate tab switch flicker)
        if (parsed.status === 'pending_return' && Date.now() - parsed.openedAt > 3000) {
          // Mark prompt as displayed to prevent looping
          parsed.status = 'prompt_displayed'
          window.sessionStorage?.setItem('pending_submission_check', JSON.stringify(parsed))
          setPendingPrompt(parsed)
        }
      } catch {
        // Ignore storage errors
      }
    }

    document.addEventListener('visibilitychange', handleCheckReturn)
    window.addEventListener('focus', handleCheckReturn)

    return () => {
      document.removeEventListener('visibilitychange', handleCheckReturn)
      window.removeEventListener('focus', handleCheckReturn)
    }
  }, [])

  if (!pendingPrompt) return null

  const handleYesApplied = async () => {
    setConfirming(true)
    setConfirmError(null)
    try {
      const updated = await markApplied(pendingPrompt.applicationId)
      window.sessionStorage?.removeItem('pending_submission_check')
      setPendingPrompt(null)
      if (onSubmissionConfirmed) {
        onSubmissionConfirmed(updated)
      }
    } catch (err) {
      setConfirmError(err.message || 'Could not record your confirmation. Please try again.')
    } finally {
      setConfirming(false)
    }
  }

  const handleNotYet = () => {
    // Snooze: leaves in storage as snoozed so it won't prompt again for this open
    try {
      const stored = JSON.parse(window.sessionStorage?.getItem('pending_submission_check') || '{}')
      stored.status = 'snoozed'
      window.sessionStorage?.setItem('pending_submission_check', JSON.stringify(stored))
    } catch {
      window.sessionStorage?.removeItem('pending_submission_check')
    }
    setPendingPrompt(null)
  }

  const handleSkip = () => {
    window.sessionStorage?.removeItem('pending_submission_check')
    setPendingPrompt(null)
  }

  return (
    <div
      id="return-submission-prompt-backdrop"
      style={{
        position: 'fixed',
        bottom: '24px',
        right: '24px',
        zIndex: 1200,
        maxWidth: '420px',
        width: 'calc(100% - 48px)',
        background: 'var(--bg-card, #ffffff)',
        border: '1px solid var(--border, #cbd5e1)',
        borderRadius: '12px',
        boxShadow: '0 12px 32px rgba(0, 0, 0, 0.18)',
        padding: '18px 20px',
        animation: 'slideUp 0.25s ease-out',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '18px' }}>📬</span>
          <h4 style={{ margin: 0, fontSize: '15px', fontWeight: 700, color: 'var(--text-primary, #0f172a)' }}>
            Did you submit to {pendingPrompt.companyName}?
          </h4>
        </div>
        <button
          type="button"
          onClick={handleSkip}
          aria-label="Dismiss prompt"
          style={{ background: 'transparent', border: 'none', color: 'var(--text-muted, #94a3b8)', cursor: 'pointer', fontSize: '16px' }}
        >
          ✕
        </button>
      </div>

      <p style={{ margin: '0 0 14px 0', fontSize: '12px', color: 'var(--text-muted, #64748b)', lineHeight: 1.5 }}>
        Compass never sets applied status automatically. Confirming will schedule a 14-day follow-up reminder and move this to your submitted pipeline.
      </p>

      {confirmError && (
        <div role="alert" style={{ margin: '0 0 12px 0', padding: '8px 10px', borderRadius: '6px', background: '#fee2e2', color: '#991b1b', fontSize: '12px' }}>
          {confirmError}
        </div>
      )}

      <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        <button
          type="button"
          onClick={handleSkip}
          style={{
            padding: '6px 12px',
            borderRadius: '6px',
            background: 'transparent',
            border: '1px solid var(--border, #cbd5e1)',
            color: 'var(--text-muted, #64748b)',
            fontSize: '12px',
            fontWeight: 500,
            cursor: 'pointer',
          }}
        >
          Skip
        </button>
        <button
          type="button"
          onClick={handleNotYet}
          style={{
            padding: '6px 12px',
            borderRadius: '6px',
            background: 'transparent',
            border: '1px solid var(--border, #cbd5e1)',
            color: 'var(--text-primary, #0f172a)',
            fontSize: '12px',
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          Not yet
        </button>
        <button
          type="button"
          onClick={handleYesApplied}
          disabled={confirming}
          style={{
            padding: '6px 14px',
            borderRadius: '6px',
            background: 'var(--brand, #16a34a)',
            color: '#ffffff',
            border: 'none',
            fontSize: '12px',
            fontWeight: 700,
            cursor: confirming ? 'not-allowed' : 'pointer',
          }}
        >
          {confirming ? 'Confirming…' : 'Yes, applied'}
        </button>
      </div>
    </div>
  )
}
