import React from 'react'
import { describeIntakeItem } from '../../utils/chatRequest'

// Preview of several pasted tasks. Nothing is saved until the user confirms.
export default function IntakePreviewCard({ pendingAction, onConfirm, onCancel }) {
  const items = Array.isArray(pendingAction?.items) ? pendingAction.items : []
  const count = items.length || pendingAction?.count || 0
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
      <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
        <button
          type="button"
          id="btn-intake-confirm"
          className="btn-primary"
          style={{ padding: '4px 14px', minHeight: '30px', fontSize: '12px', borderRadius: '4px', cursor: 'pointer', fontWeight: '600' }}
          onClick={onConfirm}
        >
          Add all {count}
        </button>
        <button
          type="button"
          id="btn-intake-cancel"
          className="btn-secondary"
          style={{ padding: '4px 14px', minHeight: '30px', fontSize: '12px', borderRadius: '4px', cursor: 'pointer' }}
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
