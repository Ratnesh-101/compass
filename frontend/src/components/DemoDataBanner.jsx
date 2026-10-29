import React from 'react'

export default function DemoDataBanner({ onReset, resetting }) {
  return (
    <div
      role="status"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '12px',
        padding: '10px 16px',
        margin: '0 0 12px 0',
        background: 'var(--surface, var(--bg-card, #fff))',
        border: '1px solid var(--border, #e5e7eb)',
        borderRadius: 'var(--radius-btn, 6px)',
        fontSize: '13px',
        color: 'var(--text-primary, #1b1a17)',
        boxSizing: 'border-box',
      }}
    >
      <span>
        Demo data: you are viewing the Judge Persona sample workspace. Chat uses the same data.
      </span>
      <button
        type="button"
        id="demo-banner-reset"
        className="btn-secondary"
        onClick={onReset}
        disabled={resetting}
        style={{
          borderRadius: 'var(--radius-btn, 6px)',
          padding: '4px 12px',
          fontSize: '13px',
          minHeight: '32px',
          whiteSpace: 'nowrap',
          cursor: resetting ? 'wait' : 'pointer',
        }}
      >
        {resetting ? 'Resetting…' : 'Reset demo'}
      </button>
    </div>
  )
}
