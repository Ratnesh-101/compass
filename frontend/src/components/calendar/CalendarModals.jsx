import React from 'react'
import { getCalendarExportUrl, quickConnectUser, fetchCalendarStatus, downloadAuthedFile } from '../../api/client'

import { Zap, X, Check, Calendar, Download, ExternalLink } from 'lucide-react'
import { planCommitState } from '../../utils/scheduleHonesty'
import Dialog from '../Dialog'

export function ProposedPlanModal({ proposedPlan, onClose, onCommit, committing }) {
  if (!proposedPlan) return null
  const { canCommit, reasons } = planCommitState(proposedPlan)

  return (
    <Dialog onClose={onClose} style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(27, 26, 23, 0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, backdropFilter: 'blur(3px)' }}>
      <div style={{ width: '580px', maxWidth: '90vw', background: 'var(--bg-card)', borderRadius: 'var(--radius-card, 8px)', border: '1px solid var(--border)', boxShadow: '0 8px 30px rgba(0,0,0,0.12)', padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Zap size={16} strokeWidth={1.8} />
            <span>Review Proposed Schedule Allocation</span>
          </h3>
          <button onClick={onClose} aria-label="Close" style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex', alignItems: 'center' }}>
            <X size={16} strokeWidth={1.8} />
          </button>
        </div>
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: '1.5', margin: 0 }}>{proposedPlan.summary}</p>
        <div style={{ maxHeight: '260px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px', background: 'var(--bg-card-soft)', padding: '12px', borderRadius: 'var(--radius-card, 8px)', border: '1px solid var(--border)' }}>
          {proposedPlan.scheduled && proposedPlan.scheduled.map(s => (
            <div key={s.task_id} style={{ padding: '8px 12px', borderRadius: 'var(--radius-btn, 6px)', background: 'var(--bg-card)', border: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <strong style={{ fontSize: '13px', color: 'var(--text-primary)', fontWeight: '600' }}>{s.title}</strong>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>Domain: {s.domain} · Duration: {s.duration_minutes}m</div>
              </div>
              <span style={{ fontSize: '12px', color: 'var(--accent)', fontWeight: '600' }}>
                {s.scheduled_start.slice(0, 10)} {s.scheduled_start.slice(11, 16)} → {s.scheduled_end.slice(11, 16)}
              </span>
            </div>
          ))}
        </div>
        {reasons.length > 0 && (
          <div id="proposed-plan-unplaced" style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: '1.5' }}>
            <strong>{canCommit ? 'Not placed' : 'Nothing could be placed'}</strong>
            <ul style={{ margin: '4px 0 0', paddingLeft: '18px' }}>
              {reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '8px' }}>
          <button onClick={onClose} className="btn-touch-target btn-secondary" style={{ padding: '8px 16px', borderRadius: 'var(--radius-btn, 6px)', fontSize: '13px', fontWeight: '500', minHeight: '44px' }}>Cancel</button>
          <button
            id="btn-confirm-commit-schedule"
            onClick={onCommit}
            disabled={committing || !canCommit}
            className="btn-touch-target btn-primary-amber"
            style={{ padding: '8px 20px', borderRadius: 'var(--radius-btn, 6px)', fontSize: '13px', fontWeight: '600', cursor: committing ? 'wait' : (canCommit ? 'pointer' : 'not-allowed'), minHeight: '44px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
            <Check size={14} strokeWidth={1.8} />
            <span>{committing ? 'Committing...' : 'Approve & Commit Schedule'}</span>
          </button>
        </div>
      </div>
    </Dialog>
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
      setBannerMessage({ type: 'success', text: `Connected as ${quickEmailInput}! Schedule slotted.` })
    } catch (err) {
      alert(`Could not connect: ${err.message}`)
    }
  }

  return (
    <Dialog onClose={onClose} style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(27, 26, 23, 0.45)', backdropFilter: 'blur(3px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-card, 8px)', padding: '24px', width: '100%', maxWidth: '420px', boxShadow: '0 8px 30px rgba(0,0,0,0.12)' }}>
        <h3 style={{ margin: '0 0 8px', color: 'var(--text-primary)', fontSize: '18px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Zap size={18} strokeWidth={1.8} />
          <span>Connect Your Gmail</span>
        </h3>
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
          style={{ width: '100%', padding: '10px 14px', borderRadius: 'var(--radius-btn, 6px)', background: 'var(--bg-app)', border: '1px solid var(--border)', color: 'var(--text-primary)', fontSize: '14px', marginBottom: '18px', boxSizing: 'border-box', outline: 'none', minHeight: '44px' }}
        />
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
          <button onClick={onClose} className="btn-touch-target btn-secondary" style={{ padding: '8px 16px', borderRadius: 'var(--radius-btn, 6px)', fontSize: '13px', fontWeight: '500', minHeight: '44px' }}>Cancel</button>
          <button
            id="btn-submit-quick-connect"
            disabled={!quickEmailInput.includes('@')}
            onClick={handleConnect}
            className={`btn-touch-target ${quickEmailInput.includes('@') ? 'btn-primary-amber' : 'btn-secondary'}`}
            style={{ padding: '8px 18px', borderRadius: 'var(--radius-btn, 6px)', fontSize: '13px', fontWeight: '600', cursor: quickEmailInput.includes('@') ? 'pointer' : 'not-allowed', minHeight: '44px' }}>
            Connect Account
          </button>
        </div>
      </div>
    </Dialog>
  )
}

export function IcsExportModal({ show, onClose, activeDomain }) {
  if (!show) return null

  return (
    <Dialog onClose={onClose} style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(27, 26, 23, 0.45)', backdropFilter: 'blur(3px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-card, 8px)', padding: '24px', width: '100%', maxWidth: '520px', boxShadow: '0 8px 30px rgba(0,0,0,0.12)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <h3 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '18px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Calendar size={18} strokeWidth={1.8} />
            <span>Sync Tasks to Google Calendar</span>
          </h3>
          <button onClick={onClose} aria-label="Close" style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex', alignItems: 'center' }}>
            <X size={18} strokeWidth={1.8} />
          </button>
        </div>
        <p style={{ color: 'var(--text-secondary)', fontSize: '13px', lineHeight: '1.5', margin: '0 0 16px' }}>
          Download your schedule as a file and import it into Google Calendar. This is a one-time import: later changes in Compass need a fresh download.
        </p>
        <div style={{ background: 'var(--bg-card-soft)', border: '1px solid var(--border)', borderRadius: 'var(--radius-card, 8px)', padding: '14px', marginBottom: '16px' }}>
          <h4 style={{ margin: '0 0 8px', color: 'var(--text-primary)', fontSize: '13px', fontWeight: '600' }}>Import a .ics file</h4>
          <ol style={{ margin: '0 0 10px', paddingLeft: '18px', color: 'var(--text-primary)', fontSize: '13px', lineHeight: '1.6' }}>
            <li>
              Click below to download the <code style={{ color: 'var(--accent)', background: 'var(--bg-card)', padding: '2px 4px', borderRadius: '4px' }}>compass_schedule.ics</code> file:
              <div style={{ marginTop: '8px', marginBottom: '8px' }}>
                <button
                  type="button"
                  onClick={() => downloadAuthedFile(getCalendarExportUrl(activeDomain), 'compass_schedule.ics')}
                  className="btn-touch-target btn-secondary"
                  style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '8px 14px', borderRadius: 'var(--radius-btn, 6px)', fontSize: '13px', fontWeight: '600', minHeight: '44px', cursor: 'pointer', border: '1px solid var(--border)' }}
                >
                  <Download size={14} strokeWidth={1.8} />
                  <span>Download compass_schedule.ics</span>
                </button>
              </div>
            </li>
            <li>In Google Calendar, look at the left sidebar under <b>Other calendars</b> and click <b>+</b>.</li>
            <li>Click <b>Import</b>, select the downloaded file, and click <b>Import</b>.</li>
            <li>All scheduled tasks immediately appear in your Google Calendar!</li>
          </ol>
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
          <a href="https://calendar.google.com" target="_blank" rel="noreferrer" className="btn-touch-target btn-secondary" style={{ padding: '8px 16px', borderRadius: 'var(--radius-btn, 6px)', fontSize: '13px', fontWeight: '500', textDecoration: 'none', minHeight: '44px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
            <span>Open Google Calendar</span>
            <ExternalLink size={13} strokeWidth={1.8} />
          </a>
          <button onClick={onClose} className="btn-touch-target btn-primary-amber" style={{ padding: '8px 18px', borderRadius: 'var(--radius-btn, 6px)', fontSize: '13px', fontWeight: '600', cursor: 'pointer', minHeight: '44px' }}>
            Done
          </button>
        </div>
      </div>
    </Dialog>
  )
}
