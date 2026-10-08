import React from 'react'

export default function ChatConversationItem({
  conv,
  isCurrent,
  isMenuOpen,
  onToggleMenu,
  isEditing,
  editingTitle,
  setEditingTitle,
  onSelect,
  onStartRename,
  onSaveRename,
  onCancelRename,
  onTogglePin,
  onToggleArchive,
  onOpenDeleteConfirm,
}) {
  return (
    <div
      onClick={() => {
        if (!isEditing) onSelect(conv.id)
      }}
      style={{
        padding: '10px 12px',
        borderRadius: '8px',
        border: `1px solid ${isCurrent ? 'var(--primary)' : 'var(--border)'}`,
        background: isCurrent ? 'var(--bg-card-soft)' : 'var(--bg-card)',
        cursor: isEditing ? 'default' : 'pointer',
        display: 'flex',
        flexDirection: 'column',
        gap: '4px',
        transition: 'all 0.15s ease',
        position: 'relative',
      }}
      onMouseEnter={e => {
        if (!isCurrent) e.currentTarget.style.borderColor = 'var(--brand)'
      }}
      onMouseLeave={e => {
        if (!isCurrent) e.currentTarget.style.borderColor = 'var(--border)'
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
        {isEditing ? (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              e.stopPropagation()
              onSaveRename(conv.id)
            }}
            onClick={(e) => e.stopPropagation()}
            style={{ display: 'flex', alignItems: 'center', gap: '4px', flex: 1 }}
          >
            <input
              autoFocus
              value={editingTitle}
              onChange={(e) => setEditingTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  e.stopPropagation()
                  onCancelRename()
                }
              }}
              style={{
                flex: 1,
                padding: '3px 6px',
                fontSize: '12px',
                borderRadius: '4px',
                border: '1px solid var(--primary)',
                background: 'var(--bg-app)',
                color: 'var(--text-primary)',
                outline: 'none',
              }}
            />
            <button
              type="submit"
              style={{
                background: 'var(--primary)',
                color: '#fff',
                border: 'none',
                borderRadius: '4px',
                padding: '3px 6px',
                fontSize: '11px',
                cursor: 'pointer',
                fontWeight: '700'
              }}
              title="Save name"
            >
              ✓
            </button>
            <button
              type="button"
              onClick={onCancelRename}
              style={{
                background: 'transparent',
                color: 'var(--text-muted)',
                border: 'none',
                borderRadius: '4px',
                padding: '3px 6px',
                fontSize: '11px',
                cursor: 'pointer'
              }}
              title="Cancel"
            >
              ✕
            </button>
          </form>
        ) : (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', overflow: 'hidden', flex: 1 }}>
              {conv.is_pinned && (
                <span style={{ fontSize: '11.5px', flexShrink: 0 }} title="Pinned chat">📌</span>
              )}
              <span style={{
                fontSize: '12.5px',
                fontWeight: '700',
                color: 'var(--text-primary)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap'
              }}>
                {conv.title || 'Chat Session'}
              </span>
            </div>

            <button
              className="chat-item-menu-btn"
              onClick={(e) => {
                e.stopPropagation()
                onToggleMenu()
              }}
              style={{
                background: isMenuOpen ? 'var(--bg-card-soft)' : 'none',
                border: 'none',
                color: isMenuOpen ? 'var(--text-primary)' : 'var(--text-muted)',
                fontSize: '16px',
                fontWeight: '800',
                cursor: 'pointer',
                padding: '1px 5px',
                borderRadius: '4px',
                lineHeight: 1,
                letterSpacing: '-0.5px',
                transition: 'color 0.15s ease',
              }}
              title="Chat options"
            >
              ···
            </button>
          </>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '10.5px', color: 'var(--text-muted)' }}>
        <span>{new Date(conv.last_active_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
        <span>{conv.message_count} message{conv.message_count !== 1 ? 's' : ''}</span>
      </div>

      {conv.preview && (
        <div style={{ fontSize: '11px', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', opacity: 0.85 }}>
          {conv.preview}
        </div>
      )}

      {isMenuOpen && (
        <div
          className="chat-item-menu-container"
          onClick={(e) => e.stopPropagation()}
          style={{
            position: 'absolute',
            right: '8px',
            top: '32px',
            zIndex: 100,
            background: '#202123',
            border: '1px solid rgba(255, 255, 255, 0.14)',
            borderRadius: '12px',
            boxShadow: '0 10px 28px rgba(0, 0, 0, 0.65), 0 2px 8px rgba(0, 0, 0, 0.4)',
            padding: '5px',
            minWidth: '150px',
            display: 'flex',
            flexDirection: 'column',
            gap: '2px',
          }}
        >
          <button
            onClick={() => onStartRename(conv)}
            style={{
              display: 'flex', alignItems: 'center', gap: '10px', width: '100%',
              padding: '8px 12px', borderRadius: '8px', border: 'none', background: 'transparent',
              color: '#ececed', fontSize: '12.5px', fontWeight: '500', cursor: 'pointer', textAlign: 'left'
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.08)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
            <span>Rename</span>
          </button>

          <button
            onClick={() => onTogglePin(conv)}
            style={{
              display: 'flex', alignItems: 'center', gap: '10px', width: '100%',
              padding: '8px 12px', borderRadius: '8px', border: 'none', background: 'transparent',
              color: '#ececed', fontSize: '12.5px', fontWeight: '500', cursor: 'pointer', textAlign: 'left'
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.08)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="17" x2="12" y2="22"/>
              <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/>
            </svg>
            <span>{conv.is_pinned ? 'Unpin chat' : 'Pin chat'}</span>
          </button>

          <button
            onClick={() => onToggleArchive(conv)}
            style={{
              display: 'flex', alignItems: 'center', gap: '10px', width: '100%',
              padding: '8px 12px', borderRadius: '8px', border: 'none', background: 'transparent',
              color: '#ececed', fontSize: '12.5px', fontWeight: '500', cursor: 'pointer', textAlign: 'left'
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.08)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="21 8 21 21 3 21 3 8"/>
              <rect x="1" y="3" width="22" height="5"/>
              <line x1="10" y1="12" x2="14" y2="12"/>
            </svg>
            <span>{conv.is_archived ? 'Unarchive' : 'Archive'}</span>
          </button>

          <div style={{ height: '1px', background: 'rgba(255, 255, 255, 0.08)', margin: '2px 0' }} />

          <button
            onClick={() => onOpenDeleteConfirm(conv)}
            style={{
              display: 'flex', alignItems: 'center', gap: '10px', width: '100%',
              padding: '8px 12px', borderRadius: '8px', border: 'none', background: 'transparent',
              color: '#ef4444', fontSize: '12.5px', fontWeight: '600', cursor: 'pointer', textAlign: 'left'
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(239, 68, 68, 0.14)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3 6 5 6 21 6"/>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
              <line x1="10" y1="11" x2="10" y2="17"/>
              <line x1="14" y1="11" x2="14" y2="17"/>
            </svg>
            <span>Delete</span>
          </button>
        </div>
      )}
    </div>
  )
}
