import React from 'react'

export default function ParkedThoughtsShelf({
  parkedThoughts = [],
  onResolveParked,
}) {
  return (
    <div
      id="parked-thoughts-shelf"
      style={{
        padding: '10px 20px',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-card-soft)',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        flexShrink: 0,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: '11px', fontWeight: '700', textTransform: 'uppercase', color: 'var(--text-secondary)', letterSpacing: '0.04em', display: 'flex', alignItems: 'center', gap: '5px' }}>
          <span>📌</span>
          <span>Parked Thoughts Shelf</span>
          <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 'normal' }}>({parkedThoughts.length} open)</span>
        </span>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          Tangents to revisit when you have breathing room
        </span>
      </div>
      {parkedThoughts.length === 0 ? (
        <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic', padding: '4px 0' }}>
          No thoughts parked right now. Tell Compass "park that" anytime in chat to defer a topic.
        </div>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
          {parkedThoughts.map((item) => (
            <div
              key={item.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '5px 11px',
                borderRadius: '8px',
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                fontSize: '12px',
                maxWidth: '100%',
              }}
            >
              <span style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>{item.text}</span>
              <button
                type="button"
                onClick={() => onResolveParked && onResolveParked(item.id)}
                style={{
                  padding: '2px 7px',
                  borderRadius: '5px',
                  border: 'none',
                  background: 'var(--coursework-bg)',
                  color: 'var(--coursework)',
                  fontSize: '10.5px',
                  fontWeight: '700',
                  cursor: 'pointer',
                  flexShrink: 0,
                }}
                title="Mark done"
              >
                ✓ Done
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
