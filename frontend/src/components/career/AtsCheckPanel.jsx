import React, { useState } from 'react'
import { runAtsCheck } from '../../api/careerApi'

/**
 * ATS check: an estimate of how a basic applicant tracking system reads this resume. It lists the
 * sections it can find, job keywords your resume does not contain, and formatting risks.
 * Always labelled an estimate. Nothing is sent to any employer.
 */
export default function AtsCheckPanel({ resumeId, opportunityId }) {
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      setReport(await runAtsCheck(resumeId ?? null, opportunityId ?? null))
    } catch (err) {
      setError(err?.message || "We couldn't run the check right now.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-testid="ats-check-panel" style={{ padding: '14px 16px', borderRadius: '10px', background: 'var(--bg-app)', border: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
        <div>
          <h4 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>ATS check</h4>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Many companies use software to scan resumes. This estimates what that software can read.
          </div>
        </div>
        <button
          type="button"
          onClick={run}
          disabled={busy}
          style={{ padding: '7px 14px', borderRadius: '8px', background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-primary)', fontSize: '12px', fontWeight: 600, cursor: busy ? 'not-allowed' : 'pointer' }}
        >
          {busy ? 'Checking…' : report ? 'Check again' : 'Check my resume'}
        </button>
      </div>

      {error && (
        <div role="alert" style={{ marginTop: '10px', fontSize: '12px', color: '#b91c1c' }}>
          {error}
        </div>
      )}

      {report && (
        <div style={{ marginTop: '12px', fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>
            Estimated score: {Math.round(report.score)} out of 100 <span style={{ fontWeight: 500, color: 'var(--text-muted)' }}>(estimate only)</span>
          </div>
          {report.score_explanation && <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{report.score_explanation}</div>}
          <div style={{ marginTop: '8px' }}>
            <strong>Sections found:</strong> {report.detected_sections?.length ? report.detected_sections.join(', ') : 'none'}
          </div>
          {report.missing_sections?.length > 0 && (
            <div>
              <strong>Not found:</strong> {report.missing_sections.join(', ')}
            </div>
          )}
          {report.keywords_checked > 0 && (
            <div>
              <strong>Job keywords missing from your resume:</strong>{' '}
              {report.missing_critical_keywords?.length ? report.missing_critical_keywords.join(', ') : 'none, all found'}
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                Only add a keyword if it is true for you. Compass never adds skills for you.
              </div>
            </div>
          )}
          {report.formatting_warnings?.length > 0 && (
            <ul style={{ margin: '6px 0 0 0', paddingLeft: '18px' }}>
              {report.formatting_warnings.map(w => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
