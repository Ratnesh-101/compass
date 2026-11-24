import React, { useState } from 'react'

export default function LinkedInImportGuide() {
  const [isOpen, setIsOpen] = useState(false)

  return (
    <div
      style={{
        border: '1px solid var(--border, #e2e8f0)',
        borderRadius: '10px',
        background: 'var(--bg-card-soft, #f8fafc)',
        marginBottom: '16px',
        overflow: 'hidden',
      }}
    >
      <button
        type="button"
        id="linkedin-guide-toggle"
        aria-expanded={isOpen}
        aria-controls="linkedin-guide-panel"
        onClick={() => setIsOpen((prev) => !prev)}
        style={{
          width: '100%',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '10px 14px',
          background: 'transparent',
          border: 'none',
          color: 'var(--text-primary, #0f172a)',
          fontSize: '12.5px',
          fontWeight: '700',
          cursor: 'pointer',
          textAlign: 'left',
          outline: 'none',
        }}
        onFocus={(e) => {
          e.currentTarget.style.boxShadow = 'inset 0 0 0 2px var(--primary, #2563eb)'
        }}
        onBlur={(e) => {
          e.currentTarget.style.boxShadow = 'none'
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span aria-hidden="true">💡</span>
          <span>How do I get my LinkedIn data?</span>
        </span>
        <span
          style={{
            fontSize: '11px',
            color: 'var(--text-muted, #64748b)',
            transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.15s ease',
          }}
          aria-hidden="true"
        >
          ▼
        </span>
      </button>

      {isOpen && (
        <div
          id="linkedin-guide-panel"
          role="region"
          aria-labelledby="linkedin-guide-toggle"
          style={{
            padding: '10px 14px 14px',
            borderTop: '1px solid var(--border, #e2e8f0)',
            fontSize: '12px',
            lineHeight: 1.55,
            color: 'var(--text-secondary, #334155)',
          }}
        >
          <div style={{ marginBottom: '10px' }}>
            <strong style={{ color: 'var(--text-primary, #0f172a)' }}>Method 1 (fastest, 30 seconds):</strong>{' '}
            open your LinkedIn profile on a computer, click More (or Resources), choose Save to PDF, upload that PDF here.
          </div>

          <div style={{ marginBottom: '10px' }}>
            <strong style={{ color: 'var(--text-primary, #0f172a)' }}>Method 2 (everything):</strong>{' '}
            LinkedIn Settings &gt; Data privacy &gt; Get a copy of your data &gt; pick only Profile, Positions, Education, Skills, Certifications (a smaller download) &gt; Request archive &gt; when the email arrives download the .zip and upload it here.
          </div>

          <div
            style={{
              padding: '8px 10px',
              borderRadius: '6px',
              background: 'var(--bg-card, #ffffff)',
              border: '1px solid var(--border, #e2e8f0)',
              fontSize: '11.5px',
              color: 'var(--text-muted, #64748b)',
              fontStyle: 'italic',
            }}
          >
            Compass never logs in to LinkedIn or scrapes it. It only reads files you choose, and it ignores everything in the download that is not part of your profile (messages and connections are never read).
          </div>
        </div>
      )}
    </div>
  )
}
