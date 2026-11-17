import React, { useEffect, useRef, useState } from 'react'
import { describeIntakeItem } from '../../utils/chatRequest'

// Preview of several pasted tasks. Nothing is saved until the user confirms.
export default function IntakePreviewCard({ pendingAction, onConfirm, onCancel }) {
  const [busy, setBusy] = useState(false)
  const confirmRef = useRef(null)
  const items = Array.isArray(pendingAction?.items) ? pendingAction.items : []
  const count = items.length || pendingAction?.count || 0

  // The primary button takes focus when the card appears, so pressing Enter confirms.
  // Escape has no handler here and Cancel is a separate button, so neither can confirm.
  useEffect(() => {
    confirmRef.current?.focus({ preventScroll: true })
  }, [])

  const handleConfirm = async () => {
    if (busy) return
    setBusy(true)
    try {
      await onConfirm?.()
    } finally {
      setBusy(false)
    }
  }

  const handleCancel = async () => {
    if (busy) return
    setBusy(true)
    try {
      await onCancel?.()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="chat-intake-preview-card"
      role="region"
      aria-label="Tasks ready to add"
      style={{
        marginTop: '10px',
        padding: '10px 14px',
        background: 'var(--bg-card-soft, rgba(255,255,255,0.03))',
        border: '1px solid var(--border)',
        borderRadius: '6px',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
      }}
    >
      <div style={{ fontSize: '12px', fontWeight: '500', color: 'var(--text-primary)' }}>
        {count} {count === 1 ? 'task is' : 'tasks are'} ready to add. Nothing is saved until you confirm.
      </div>
      <ol style={{ margin: 0, paddingLeft: '18px', fontSize: '12px', color: 'var(--text-secondary)' }}>
        {items.map((item, i) => (
          <li key={i}>
            <strong style={{ color: 'var(--text-primary)' }}>{item.title}</strong>
            <span> — {describeIntakeItem(item)}</span>
          </li>
        ))}
      </ol>
      <div style={{ display: 'flex', gap: '10px', alignItems: 'center', marginTop: '6px' }}>
        <button
          type="button"
          id="btn-intake-confirm"
          ref={confirmRef}
          className="btn-primary"
          disabled={busy}
          style={{
            padding: '8px 20px',
            minHeight: '38px',
            fontSize: '13px',
            fontWeight: '600',
            borderRadius: '6px',
            cursor: busy ? 'not-allowed' : 'pointer',
            background: 'var(--primary, #2563eb)',
            color: '#ffffff',
            border: 'none',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
          }}
          onClick={handleConfirm}
        >
          {count > 1 ? `Add all ${count}` : 'Confirm & add task'}
        </button>
        <button
          type="button"
          id="btn-intake-cancel"
          className="btn-secondary"
          disabled={busy}
          style={{
            padding: '5px 12px',
            minHeight: '30px',
            fontSize: '12px',
            borderRadius: '6px',
            cursor: busy ? 'not-allowed' : 'pointer',
            background: 'transparent',
            color: 'var(--text-secondary)',
            border: '1px solid var(--border)',
          }}
          onClick={handleCancel}
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
