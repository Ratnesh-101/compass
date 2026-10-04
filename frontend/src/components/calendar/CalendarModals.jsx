import React from 'react'
import { getCalendarExportUrl, quickConnectUser, fetchCalendarStatus } from '../../api/client'

export function ProposedPlanModal({ proposedPlan, onClose, onCommit, committing }) {
  if (!proposedPlan) return null

  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(31, 27, 46, 0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, backdropFilter: 'blur(5px)' }}>
      <div style={{ width: '580px', maxWidth: '90vw', background: 'var(--bg-card)', borderRadius: '16px', border: '1px solid var(--border)', boxShadow: 'var(--shadow-lg)', padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ fontSize: '16px', fontWeight: '800', color: 'var(--text-primary)' }}>⚡ Review Proposed Schedule Allocation</h3>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: '16px', cursor: 'pointer' }}>✕</button>
        </div>
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: '1.5' }}>{proposedPlan.summary}</p>
        <div style={{ maxHeight: '260px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px', background: 'var(--bg-card-soft)', padding: '12px', borderRadius: '10px', border: '1px solid var(--border)' }}>
          {proposedPlan.scheduled && proposedPlan.scheduled.map(s => (
            <div key={s.task_id} style={{ padding: '8px 12px', borderRadius: '8px', background: 'var(--bg-card)', border: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <strong style={{ fontSize: '12.5px', color: 'var(--text-primary)' }}>{s.title}</strong>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>Domain: {s.domain} · Duration: {s.duration_minutes}m</div>
              </div>
              <span style={{ fontSize: '11.5px', color: 'var(--coursework-text)', fontFamily: 'JetBrains Mono, monospace', fontWeight: '700' }}>
                {s.scheduled_start.slice(0, 10)} {s.scheduled_start.slice(11, 16)} → {s.scheduled_end.slice(11, 16)}
              </span>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '8px' }}>
          <button onClick={onClose} style={{ padding: '8px 16px', borderRadius: '8px', background: 'var(--bg-card-soft)', border: '1px solid var(--border)', color: 'var(--text-secondary)', fontSize: '13px', fontWeight: '500', cursor: 'pointer' }}>Cancel</button>
          <button
            id="btn-confirm-commit-schedule"
            onClick={onCommit}
            disabled={committing}
            style={{ padding: '8px 20px', borderRadius: '8px', background: 'linear-gradient(135deg, #10b981, #059669)', border: 'none', color: '#ffffff', fontSize: '13px', fontWeight: '700', cursor: committing ? 'wait' : 'pointer' }}>
            {committing ? 'Committing...' : '✅ Approve & Commit to Google Calendar'}
          </button>
        </div>
      </div>
    </div>
  )
}

export function QuickConnectModal({ show, onClose, quickEmailInput, setQuickEmailInput, setCalendarStatus, setBannerMessage }) {
  if (!show) return null

  const handleConnect = async () => {
    try {
      await quickConnectUser(quickEmailInput)
      onClose()
      const status = await fetchCalendarStatus()
      if (status) setCalendarStatus(status)
      setBannerMessage({ type: 'success', text: `✅ Connected as ${quickEmailInput}! Schedule slotted.` })
    } catch (err) {
      alert(`Could not connect: ${err.message}`)
    }
  }

  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(31, 27, 46, 0.45)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '16px', padding: '28px', width: '100%', maxWidth: '420px', boxShadow: 'var(--shadow-lg)' }}>
        <h3 style={{ margin: '0 0 8px', color: 'var(--text-primary)', fontSize: '18px', fontWeight: '800' }}>⚡ Connect Your Gmail</h3>
        <p style={{ color: 'var(--text-secondary)', fontSize: '13px', margin: '0 0 20px', lineHeight: '1.5' }}>
          Enter your Gmail address to activate your schedule profile. Tasks will be slotted deterministically and can be imported or subscribed directly in Google Calendar.
        </p>
        <input
          id="input-quick-email"
          type="email"
          placeholder="e.g. yourname@gmail.com"
          value={quickEmailInput}
          onChange={(e) => setQuickEmailInput(e.target.value)}
          onKeyDown={async (e) => {
            if (e.key === 'Enter' && quickEmailInput.includes('@')) {
              await handleConnect()
            }
          }}
          style={{ width: '100%', padding: '10px 14px', borderRadius: '8px', background: 'var(--bg-app)', border: '1px solid var(--border)', color: 'var(--text-primary)', fontSize: '14px', marginBottom: '18px', boxSizing: 'border-box', outline: 'none' }}
        />
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
          <button onClick={onClose} style={{ padding: '8px 16px', borderRadius: '8px', background: 'var(--bg-card-soft)', border: '1px solid var(--border)', color: 'var(--text-secondary)', fontSize: '13px', fontWeight: '500', cursor: 'pointer' }}>Cancel</button>
          <button
            id="btn-submit-quick-connect"
            disabled={!quickEmailInput.includes('@')}
            onClick={handleConnect}
            style={{ padding: '8px 18px', borderRadius: '8px', background: quickEmailInput.includes('@') ? 'linear-gradient(135deg, #2563eb, #3b82f6)' : 'var(--bg-card-soft)', border: 'none', color: quickEmailInput.includes('@') ? '#ffffff' : 'var(--text-muted)', fontSize: '13px', fontWeight: '700', cursor: quickEmailInput.includes('@') ? 'pointer' : 'not-allowed' }}>
            Connect Account
          </button>
        </div>
      </div>
    </div>
  )
}

export function IcsExportModal({ show, onClose, activeDomain }) {
  if (!show) return null

  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(31, 27, 46, 0.45)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '16px', padding: '28px', width: '100%', maxWidth: '520px', boxShadow: 'var(--shadow-lg)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <h3 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '18px', fontWeight: '800', display: 'flex', alignItems: 'center', gap: '8px' }}>
            🗓️ Sync Tasks to Google Calendar
          </h3>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: '18px', cursor: 'pointer' }}>✕</button>
        </div>
        <p style={{ color: 'var(--text-secondary)', fontSize: '13px', lineHeight: '1.5', margin: '0 0 16px' }}>
          Because direct Google Calendar API write requires registered Google Cloud OAuth credentials, you can sync all your scheduled tasks into your Google Calendar right now in 2 easy steps:
        </p>
        <div style={{ background: 'var(--bg-card-soft)', border: '1px solid var(--border)', borderRadius: '10px', padding: '14px', marginBottom: '16px' }}>
          <h4 style={{ margin: '0 0 8px', color: 'var(--coursework-text)', fontSize: '13px', fontWeight: '700' }}>Option 1: Instant 1-Click File Import (Recommended)</h4>
          <ol style={{ margin: '0 0 10px', paddingLeft: '18px', color: 'var(--text-primary)', fontSize: '12.5px', lineHeight: '1.6' }}>
            <li>
              Click below to download the <code style={{ color: 'var(--coursework-text)' }}>compass_schedule.ics</code> file:
              <div style={{ marginTop: '6px', marginBottom: '6px' }}>
                <a href={getCalendarExportUrl(activeDomain)} download="compass_schedule.ics" style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '6px 12px', background: 'linear-gradient(135deg, #3b82f6, #1d4ed8)', borderRadius: '6px', color: '#ffffff', fontSize: '12px', fontWeight: '700', textDecoration: 'none' }}>
                  📥 Download compass_schedule.ics
                </a>
              </div>
            </li>
            <li>In Google Calendar, look at the left sidebar under <b>Other calendars</b> and click <b>+</b>.</li>
            <li>Click <b>Import</b>, select the downloaded file, and click <b>Import</b>.</li>
            <li>All scheduled tasks immediately appear in your Google Calendar!</li>
          </ol>
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: '10px', marginTop: '10px' }}>
            <h4 style={{ margin: '0 0 8px', color: 'var(--code-text)', fontSize: '13px', fontWeight: '700' }}>Option 2: Live Auto-Sync via Calendar Subscription URL</h4>
            <p style={{ color: 'var(--text-secondary)', fontSize: '12px', margin: '0 0 8px' }}>
              In Google Calendar &gt; <b>Other calendars (+)</b> &gt; <b>From URL</b>, paste this feed URL:
            </p>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <input readOnly value={`${window.location.origin}/api/calendar/export.ics`} style={{ flex: 1, padding: '6px 10px', borderRadius: '6px', background: 'var(--bg-app)', border: '1px solid var(--border)', color: 'var(--text-primary)', fontSize: '11.5px', fontFamily: 'JetBrains Mono, monospace' }} />
              <button
                onClick={(e) => {
                  navigator.clipboard.writeText(`${window.location.origin}/api/calendar/export.ics`)
                  e.target.innerText = 'Copied! ✓'
                  setTimeout(() => { e.target.innerText = 'Copy' }, 2000)
                }}
                style={{ padding: '6px 12px', borderRadius: '6px', background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-primary)', fontSize: '12px', fontWeight: '600', cursor: 'pointer' }}>
                Copy
              </button>
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
          <a href="https://calendar.google.com" target="_blank" rel="noreferrer" style={{ padding: '8px 16px', borderRadius: '8px', background: 'var(--bg-card-soft)', border: '1px solid var(--border)', color: 'var(--text-primary)', fontSize: '13px', fontWeight: '600', textDecoration: 'none' }}>
            Open Google Calendar ↗
          </a>
          <button onClick={onClose} style={{ padding: '8px 18px', borderRadius: '8px', background: 'linear-gradient(135deg, #3b82f6, #1d4ed8)', border: 'none', color: '#ffffff', fontSize: '13px', fontWeight: '700', cursor: 'pointer' }}>
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
