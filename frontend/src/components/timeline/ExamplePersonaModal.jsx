import React from 'react'
import Dialog from '../Dialog'
import { Sparkles, X, Info } from 'lucide-react'

export default function ExamplePersonaModal({ isOpen, onClose, onConfirm, loading = false }) {
  if (!isOpen) return null

  return (
    <Dialog
      onClose={onClose}
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(15, 23, 42, 0.45)',
        backdropFilter: 'blur(3px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1100,
        padding: '20px',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--bg-card)',
          borderRadius: 'var(--radius-card, 8px)',
          border: '1px solid var(--border)',
          width: '100%',
          maxWidth: '460px',
          padding: '22px',
          boxShadow: 'var(--shadow-lg)',
          color: 'var(--text-primary)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                width: '36px',
                height: '36px',
                borderRadius: '8px',
                background: 'rgba(245, 166, 35, 0.12)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--accent)',
              }}
            >
              <Sparkles size={20} strokeWidth={2} />
            </div>
            <h3 style={{ fontSize: '17px', fontWeight: '600', margin: 0, color: 'var(--text-primary)' }}>
              See an example workspace?
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="btn-touch-target"
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--text-secondary)',
              padding: '4px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <X size={16} />
          </button>
        </div>

        <p style={{ fontSize: '13.5px', color: 'var(--text-secondary)', lineHeight: 1.5, margin: '0 0 14px 0' }}>
          This will add sample student deadlines (such as coursework, exam dates, and hackathon milestones) so you can explore how Compass organizes tasks and weekly schedules.
        </p>

        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: '8px',
            padding: '10px 12px',
            borderRadius: '6px',
            background: 'var(--bg-card-soft)',
            border: '1px solid var(--border)',
            fontSize: '12.5px',
            color: 'var(--text-secondary)',
            marginBottom: '20px',
            lineHeight: 1.4,
          }}
        >
          <Info size={15} strokeWidth={2} style={{ color: 'var(--accent)', flexShrink: 0, marginTop: '2px' }} />
          <span>
            <strong>How to remove:</strong> You can remove these sample items at any time by clicking <strong>&quot;Reset demo&quot;</strong> in the banner at the top of the page.
          </span>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="btn-secondary"
            style={{
              minHeight: '38px',
              padding: '0 14px',
              fontSize: '13px',
              fontWeight: '500',
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={loading}
            className="btn-primary-amber"
            style={{
              minHeight: '38px',
              padding: '0 16px',
              fontSize: '13px',
              fontWeight: '600',
            }}
          >
            {loading ? 'Loading sample…' : 'Load sample tasks'}
          </button>
        </div>
      </div>
    </Dialog>
  )
}
