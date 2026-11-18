import React from 'react'
import {
  CheckCircle2,
  XCircle,
  FileEdit,
  ShieldAlert,
  Calendar,
  Trash2,
  PlusCircle,
} from 'lucide-react'

import { friendlyAction, formatActionDescription } from './actionText'

export { formatActionDescription }

function getActionIcon(tool) {
  if (tool === 'add_task') return PlusCircle
  if (tool === 'delete_task') return Trash2
  if (tool === 'schedule_event' || tool === 'commit_schedule') return Calendar
  return FileEdit
}

export default function ConfirmationGate({
  pendingActions,
  rejectFeedback,
  setRejectFeedback,
  onApprove,
  onReject,
}) {
  if (!pendingActions || pendingActions.length === 0) return null

  return (
    <div
      id="action-confirmation-gate"
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-card, 8px)',
        padding: '18px 20px',
        marginTop: '12px',
        marginBottom: '16px',
      }}
    >
      {/* Header with Safety Shield */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
        <div
          style={{
            width: '32px',
            height: '32px',
            borderRadius: 'var(--radius-btn, 6px)',
            background: 'rgba(245, 166, 35, 0.12)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--accent, #f5a623)',
          }}
        >
          <ShieldAlert size={18} strokeWidth={1.8} />
        </div>
        <div>
          <div style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)', letterSpacing: '-0.2px' }}>
            Action Confirmation Gate: {pendingActions.length} Pending Action{pendingActions.length !== 1 ? 's' : ''}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            Zero-mutation safety protocol: AI proposed changes require your explicit authorization.
          </div>
        </div>
      </div>

      {/* Action List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', margin: '14px 0' }}>
        {pendingActions.map((action, i) => {
          const ActionIcon = getActionIcon(action.tool)
          const isDestructive = action.tool === 'delete_task'
          return (
            <div
              key={i}
              style={{
                background: isDestructive ? 'rgba(239, 68, 68, 0.08)' : 'var(--bg-card-soft)',
                border: `1px solid ${isDestructive ? 'rgba(239, 68, 68, 0.25)' : 'var(--border)'}`,
                borderRadius: 'var(--radius-card, 8px)',
                padding: '10px 14px',
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
              }}
            >
              <ActionIcon size={16} strokeWidth={1.8} color={isDestructive ? '#ef4444' : 'var(--text-secondary)'} />
              <div style={{ flex: 1, fontSize: '13px', color: 'var(--text-primary)', fontWeight: '500' }}>
                {formatActionDescription(action)}
              </div>
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: '600',
                  padding: '3px 8px',
                  borderRadius: 'var(--radius-btn, 6px)',
                  background: isDestructive ? 'rgba(239, 68, 68, 0.12)' : 'var(--bg-card)',
                  color: isDestructive ? '#ef4444' : 'var(--text-secondary)',
                  border: '1px solid var(--border)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                }}
              >
                {friendlyAction(action.tool)}
              </span>
            </div>
          )
        })}
      </div>

      {/* Rejection / Modification Guidance Input */}
      <div style={{ marginBottom: '14px' }}>
        <input
          id="agent-reject-input"
          type="text"
          value={rejectFeedback}
          onChange={e => setRejectFeedback(e.target.value)}
          placeholder="Optional revision guidance (e.g. 'Keep current due date, just reduce duration')..."
          style={{
            width: '100%',
            padding: '0 14px',
            minHeight: '44px',
            background: 'var(--bg-card-soft)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-btn, 6px)',
            color: 'var(--text-primary)',
            fontSize: '13px',
            outline: 'none',
            boxSizing: 'border-box',
          }}
        />
      </div>

      {/* Executive Decision Buttons */}
      <div style={{ display: 'flex', gap: '10px' }}>
        <button
          id="agent-approve-btn"
          onClick={onApprove}
          className="btn-primary-amber"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            padding: '0 20px',
            minHeight: '44px',
            borderRadius: 'var(--radius-btn, 6px)',
            fontSize: '13px',
            fontWeight: '600',
            cursor: 'pointer',
          }}
        >
          <CheckCircle2 size={16} strokeWidth={1.8} />
          <span>Authorize Changes</span>
        </button>

        <button
          id="agent-reject-btn"
          onClick={onReject}
          className="btn-secondary"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            padding: '0 18px',
            minHeight: '44px',
            borderRadius: 'var(--radius-btn, 6px)',
            fontSize: '13px',
            fontWeight: '500',
            cursor: 'pointer',
          }}
        >
          <XCircle size={16} strokeWidth={1.8} />
          <span>Reject / Re-plan</span>
        </button>
      </div>
    </div>
  )
}
