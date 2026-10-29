import React from 'react'
import { FileText, X, Copy } from 'lucide-react'
import Dialog from '../Dialog'

export default function CoverLetterModal({
  activeLetterApp,
  onClose,
  onSave,
}) {
  if (!activeLetterApp) return null

  return (
    <Dialog onClose={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(27, 26, 23, 0.45)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '16px',
        backdropFilter: 'blur(3px)',
      }}
    >
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-card, 8px)',
          maxWidth: '650px',
          width: '100%',
          padding: '24px',
          boxShadow: '0 8px 30px rgba(0, 0, 0, 0.12)',
          maxHeight: '90vh',
          overflowY: 'auto',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '18px', fontWeight: '600', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <FileText size={18} strokeWidth={1.8} />
              <span>Tailored Cover Letter</span>
            </h3>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
              {activeLetterApp.opportunity?.company_name}: {activeLetterApp.opportunity?.role_title}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex', alignItems: 'center' }}
          >
            <X size={18} strokeWidth={1.8} />
          </button>
        </div>

        <textarea
          defaultValue={activeLetterApp.cover_letter || ''}
          id={`cover_letter_input_${activeLetterApp.id}`}
          rows={14}
          style={{
            width: '100%',
            padding: '12px',
            borderRadius: 'var(--radius-btn, 6px)',
            border: '1px solid var(--border)',
            background: 'var(--bg-card-soft)',
            color: 'var(--text-primary)',
            boxSizing: 'border-box',
            fontSize: '13px',
            lineHeight: '1.5',
            fontFamily: 'monospace',
            marginBottom: '16px',
          }}
        />

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <button
            type="button"
            onClick={() => {
              const val = document.getElementById(`cover_letter_input_${activeLetterApp.id}`)?.value
              if (val) {
                navigator.clipboard?.writeText(val)
                alert('Cover letter copied!')
              }
            }}
            className="btn-touch-target btn-secondary"
            style={{
              padding: '8px 16px',
              borderRadius: 'var(--radius-btn, 6px)',
              fontSize: '13px',
              fontWeight: '500',
              cursor: 'pointer',
              minHeight: '44px',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <Copy size={14} strokeWidth={1.8} />
            <span>Copy</span>
          </button>
          <button
            type="button"
            onClick={() => {
              const val = document.getElementById(`cover_letter_input_${activeLetterApp.id}`)?.value
              if (val !== undefined) {
                onSave(activeLetterApp.id, val)
              }
            }}
            className="btn-touch-target btn-primary-amber"
            style={{
              padding: '8px 18px',
              borderRadius: 'var(--radius-btn, 6px)',
              fontSize: '13px',
              fontWeight: '600',
              cursor: 'pointer',
              minHeight: '44px',
            }}
          >
            Save Cover Letter
          </button>
        </div>
      </div>
    </Dialog>
  )
}
