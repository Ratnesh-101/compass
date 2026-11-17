import React from 'react'

/**
 * "What changed" after tailoring a resume to a job: a short list in plain words, a small preview,
 * or the reason nothing changed. Tailoring only reorders what is already on the resume.
 */
export default function TailorChangesCard({ changes, justUpdated = false }) {
  if (!changes) return null
  return (
    <div
      data-testid="tailor-changes"
      role="status"
      aria-live="polite"
      style={{ padding: '14px 16px', borderRadius: '10px', background: 'var(--bg-app)', border: '1px solid var(--border)' }}
    >
      <h4 style={{ margin: '0 0 8px 0', fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>
        {justUpdated ? 'Updated. What changed' : 'What changed for this job'}
      </h4>
      {changes.changed ? (
        <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          {changes.lines.map(line => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : (
        <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
          Nothing needed to change. {changes.reason}
        </p>
      )}
      {(changes.preview.skills.length > 0 || changes.preview.projects.length > 0) && (
        <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Preview</div>
          {changes.preview.skills.length > 0 && <div>Skills first: {changes.preview.skills.join(', ')}</div>}
          {changes.preview.projects.length > 0 && <div>Projects: {changes.preview.projects.join(', ')}</div>}
        </div>
      )}
      {changes.note && <div style={{ marginTop: '8px', fontSize: '11px', color: 'var(--text-muted)' }}>{changes.note}</div>}
    </div>
  )
}
