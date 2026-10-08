import React from 'react'

export default function GoogleCloudSetupGuide() {
  return (
    <div
      style={{
        marginTop: '14px',
        background: 'var(--bg-app)',
        border: '1px solid var(--border)',
        borderRadius: '8px',
        padding: '14px',
      }}
    >
      <div style={{ fontSize: '12px', fontWeight: '700', color: '#b45309', marginBottom: '10px' }}>
        📋 One-time Google Cloud setup (5 minutes)
      </div>
      <ol style={{ fontSize: '11.5px', color: 'var(--text-secondary)', lineHeight: '1.8', margin: 0, paddingLeft: '18px' }}>
        <li>
          Go to{' '}
          <a
            href="https://console.cloud.google.com/apis/credentials"
            target="_blank"
            rel="noreferrer"
            style={{ color: 'var(--primary)' }}
          >
            console.cloud.google.com/apis/credentials
          </a>
        </li>
        <li>
          Click <strong style={{ color: 'var(--text-primary)' }}>"+ Create Credentials" → "OAuth client ID"</strong>
        </li>
        <li>
          Set Application type: <strong style={{ color: 'var(--text-primary)' }}>Web application</strong>
        </li>
        <li>
          Add Authorised redirect URI:{' '}
          <code
            style={{
              background: 'var(--bg-card)',
              padding: '2px 6px',
              borderRadius: '4px',
              border: '1px solid var(--border)',
              color: 'var(--primary)',
              fontSize: '11px',
            }}
          >
            http://localhost:8000/api/calendar/callback
          </code>
        </li>
        <li>
          Copy the <strong style={{ color: 'var(--text-primary)' }}>Client ID</strong> and{' '}
          <strong style={{ color: 'var(--text-primary)' }}>Client Secret</strong>
        </li>
        <li>
          Add to your{' '}
          <code
            style={{
              background: 'var(--bg-card)',
              padding: '2px 6px',
              borderRadius: '4px',
              border: '1px solid var(--border)',
              color: 'var(--primary)',
              fontSize: '11px',
            }}
          >
            .env
          </code>{' '}
          file:
          <div
            style={{
              marginTop: '8px',
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              padding: '10px 12px',
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: '11px',
              color: 'var(--text-primary)',
              lineHeight: '1.8',
              userSelect: 'all',
            }}
          >
            GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
            <br />
            GOOGLE_CLIENT_SECRET=GOCSPX-your-secret
          </div>
        </li>
        <li>
          Restart the backend server — then come back and click{' '}
          <strong style={{ color: 'var(--text-primary)' }}>"Connect Google"</strong>
        </li>
      </ol>
      <div style={{ marginTop: '10px', fontSize: '11px', color: 'var(--text-muted)' }}>
        💡 Also add your Gmail to <strong>"Test users"</strong> in the OAuth consent screen if your app is in development/testing mode.
      </div>
    </div>
  )
}
