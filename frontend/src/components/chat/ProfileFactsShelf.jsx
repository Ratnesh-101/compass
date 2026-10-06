import React from 'react'

export default function ProfileFactsShelf({
  facts = {},
  onDeleteFact,
  onForgetAll,
}) {
  const factEntries = Object.entries(facts || {})

  return (
    <div
      id="profile-facts-shelf"
      style={{
        padding: '8px 20px',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-card-soft)',
        display: 'flex',
        flexDirection: 'column',
        gap: '6px',
        flexShrink: 0,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: '11px', fontWeight: '700', textTransform: 'uppercase', color: 'var(--text-secondary)', letterSpacing: '0.04em', display: 'flex', alignItems: 'center', gap: '5px' }}>
          <span>🧠</span>
          <span>Remembered Facts</span>
          <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 'normal' }}>({factEntries.length} saved)</span>
        </span>
        {factEntries.length > 0 && (
          <button
            type="button"
            id="forget-all-facts-btn"
            onClick={onForgetAll}
            style={{
              padding: '2px 8px',
              borderRadius: '5px',
              border: '1px solid var(--border)',
              background: 'transparent',
              color: 'var(--text-muted)',
              fontSize: '10.5px',
              cursor: 'pointer',
            }}
            title="Forget all facts"
          >
            Forget all
          </button>
        )}
      </div>

      {factEntries.length === 0 ? (
        <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic', padding: '2px 0' }}>
          No personal facts stored yet. Tell Compass "call me [name]" or "remember that [preference]" to persist facts.
        </div>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
          {factEntries.map(([k, v]) => (
            <div
              key={k}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '3px 8px',
                borderRadius: '6px',
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                fontSize: '11.5px',
              }}
            >
              <span style={{ fontWeight: '600', color: 'var(--accent)' }}>{k.replace('_', ' ')}:</span>
              <span style={{ color: 'var(--text-primary)' }}>{String(v)}</span>
              <button
                type="button"
                onClick={() => onDeleteFact && onDeleteFact(k)}
                style={{
                  border: 'none',
                  background: 'transparent',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  padding: '0 2px',
                  fontSize: '12px',
                  lineHeight: '1',
                }}
                title={`Forget ${k}`}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
