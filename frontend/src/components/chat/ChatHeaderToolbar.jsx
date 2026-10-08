import React from 'react'

export default function ChatHeaderToolbar({
  showHistoryDrawer,
  setShowHistoryDrawer,
  pastConversations = [],
  isOnline,
  tone,
  handleToneChange,
  showParkedShelf,
  setShowParkedShelf,
  parkedThoughts = [],
  showContext,
  setShowContext,
  handleRecap,
  handleNewChat,
  isInputDisabled,
}) {
  return (
    <div
      style={{
        padding: '10px 18px',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-card)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexShrink: 0,
        gap: '10px',
        overflowX: 'auto',
        maxWidth: '100%',
        boxSizing: 'border-box',
      }}
    >
      {/* Left: History drawer toggle & Live connection indicator */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexShrink: 0 }}>
        <button
          id="btn-toggle-history-drawer"
          onClick={() => setShowHistoryDrawer((v) => !v)}
          style={{
            padding: '6px 12px',
            borderRadius: '8px',
            border: '1px solid var(--border)',
            background: showHistoryDrawer ? 'var(--primary)' : 'var(--bg-card-soft)',
            color: showHistoryDrawer ? '#fff' : 'var(--text-primary)',
            fontSize: '12px',
            fontWeight: '700',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            transition: 'all 0.15s ease',
            boxShadow: 'var(--shadow-sm)',
            flexShrink: 0,
          }}
          title="View previous chats, plans, and long-term memory"
        >
          <span>📜</span>
          <span>History & Memory</span>
          {pastConversations.length > 0 && (
            <span
              style={{
                background: showHistoryDrawer ? 'rgba(255,255,255,0.25)' : 'var(--brand)',
                color: showHistoryDrawer ? '#fff' : '#2a1a00',
                fontSize: '10.5px',
                padding: '1px 6px',
                borderRadius: '10px',
                fontWeight: '800',
              }}
            >
              {pastConversations.length}
            </span>
          )}
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', color: 'var(--text-secondary)' }}>
          <span
            style={{
              width: '7px',
              height: '7px',
              borderRadius: '50%',
              background: isOnline ? '#10b981' : '#f5a623',
              display: 'inline-block',
            }}
          />
          <span style={{ whiteSpace: 'nowrap' }}>{isOnline ? 'Workspace connected' : 'Connecting…'}</span>
        </div>
      </div>

      {/* Right: Connected memory pill, Context toggle & New Chat */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '4px 10px',
            borderRadius: '12px',
            background: 'var(--code-bg)',
            border: '1px solid rgba(16, 185, 129, 0.3)',
            fontSize: '11px',
            color: 'var(--code-text)',
            fontWeight: '600',
          }}
          title="Compass long-term memory is active across sessions to prevent schedule clashes"
        >
          <span>🧠</span>
          <span>Memory Active</span>
        </div>

        {/* Tone Dial: Brief / Balanced / Exploratory */}
        <div
          id="chat-tone-dial"
          style={{
            display: 'flex',
            alignItems: 'center',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: '7px',
            padding: '2px',
            gap: '2px',
          }}
          title="Adjust assistant response style (Brief, Balanced, Exploratory)"
        >
          {[
            { id: 'brief', label: 'Brief' },
            { id: 'balanced', label: 'Balanced' },
            { id: 'exploratory', label: 'Exploratory' },
          ].map((t) => (
            <button
              key={t.id}
              type="button"
              id={`btn-tone-${t.id}`}
              onClick={() => handleToneChange(t.id)}
              style={{
                padding: '3px 8px',
                borderRadius: '5px',
                border: 'none',
                background: tone === t.id ? 'var(--coursework)' : 'transparent',
                color: tone === t.id ? '#ffffff' : 'var(--text-secondary)',
                fontSize: '11px',
                fontWeight: tone === t.id ? '700' : '500',
                cursor: 'pointer',
                transition: 'background 0.15s ease, color 0.15s ease',
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Parked Thoughts Shelf Toggle */}
        <button
          id="btn-toggle-parked"
          type="button"
          onClick={() => setShowParkedShelf((v) => !v)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            padding: '4px 9px',
            borderRadius: '7px',
            border: '1px solid var(--border)',
            background: showParkedShelf ? 'var(--coursework-bg)' : 'transparent',
            color: showParkedShelf ? 'var(--coursework)' : 'var(--text-secondary)',
            fontSize: '11px',
            fontWeight: '600',
            cursor: 'pointer',
          }}
          title="Toggle Parked Thoughts Shelf"
        >
          <span>📌</span>
          <span>Parked ({parkedThoughts.length})</span>
        </button>

        <button
          onClick={() => setShowContext((v) => !v)}
          style={{
            padding: '5px 11px',
            borderRadius: '6px',
            border: '1px solid var(--border)',
            background: showContext ? 'var(--bg-card-soft)' : 'transparent',
            color: 'var(--text-secondary)',
            fontSize: '11.5px',
            fontWeight: '600',
            cursor: 'pointer',
          }}
        >
          {showContext ? 'Hide Context' : 'Show Context'}
        </button>

        <button
          id="btn-chat-recap"
          type="button"
          onClick={handleRecap}
          disabled={isInputDisabled}
          style={{
            padding: '5px 11px',
            borderRadius: '6px',
            border: '1px solid var(--border)',
            background: 'transparent',
            color: 'var(--text-secondary)',
            fontSize: '11.5px',
            fontWeight: '600',
            cursor: isInputDisabled ? 'not-allowed' : 'pointer',
            opacity: isInputDisabled ? 0.5 : 1,
          }}
          title="Summarize decisions made, open questions, and next steps"
        >
          📝 Recap
        </button>

        <button
          id="btn-chat-new"
          onClick={handleNewChat}
          disabled={isInputDisabled}
          style={{
            padding: '5px 12px',
            borderRadius: '6px',
            border: '1px solid var(--border)',
            background: 'transparent',
            color: 'var(--text-secondary)',
            fontSize: '11.5px',
            fontWeight: '700',
            cursor: isInputDisabled ? 'not-allowed' : 'pointer',
            opacity: isInputDisabled ? 0.5 : 1,
          }}
        >
          + New Chat
        </button>
      </div>
    </div>
  )
}
