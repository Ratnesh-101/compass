import React, { useState, useEffect, useRef } from 'react'

export default function ChatHeaderToolbar({
  showHistoryDrawer: _showHistoryDrawer,
  setShowHistoryDrawer,
  pastConversations = [],
  isOnline = false,
  memoryActive = true,
  onToggleMemoryActive,
  tone = 'balanced',
  handleToneChange,
  showParkedShelf: _showParkedShelf,
  setShowParkedShelf,
  parkedThoughts = [],
  showContext = false,
  setShowContext,
  handleRecap,
  handleNewChat,
  isInputDisabled = false,
  tasks = [],
}) {
  const [statusPopoverOpen, setStatusPopoverOpen] = useState(false)
  const [toolsMenuOpen, setToolsMenuOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window !== 'undefined') {
      return window.innerWidth < 768
    }
    return false
  })

  const statusAnchorRef = useRef(null)
  const toolsAnchorRef = useRef(null)
  const statusBtnRef = useRef(null)
  const toolsBtnRef = useRef(null)

  // Track responsive screen width for mobile bottom sheet
  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth < 768)
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  // Close menus on click outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (statusAnchorRef.current && !statusAnchorRef.current.contains(e.target)) {
        setStatusPopoverOpen(false)
      }
      if (toolsAnchorRef.current && !toolsAnchorRef.current.contains(e.target)) {
        setToolsMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        if (statusPopoverOpen) {
          setStatusPopoverOpen(false)
          statusBtnRef.current?.focus()
        }
        if (toolsMenuOpen) {
          setToolsMenuOpen(false)
          toolsBtnRef.current?.focus()
        }
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [statusPopoverOpen, toolsMenuOpen])

  // Determine status dot color & summary text
  const getStatusMeta = () => {
    if (isOnline && memoryActive) {
      return {
        dotColor: 'var(--domain-code, #1c8a62)',
        text: 'Memory is on',
        ariaText: 'Workspace connected and cross-session memory is active',
      }
    }
    if (isOnline && !memoryActive) {
      return {
        dotColor: 'var(--accent, #f5a623)',
        text: 'Connected, memory paused',
        ariaText: 'Workspace connected, but cross-session memory is paused',
      }
    }
    if (!isOnline && memoryActive) {
      return {
        dotColor: 'var(--accent, #f5a623)',
        text: 'Connecting, memory on',
        ariaText: 'Workspace connecting or offline, memory is on',
      }
    }
    return {
      dotColor: 'var(--danger-text, #ef4444)',
      text: 'Offline, memory off',
      ariaText: 'Workspace offline and memory is paused',
    }
  }

  const statusMeta = getStatusMeta()

  const toneOptions = [
    { id: 'brief', label: 'Short' },
    { id: 'balanced', label: 'Normal' },
    { id: 'exploratory', label: 'Detailed' },
  ]

  const handleToneKeyDown = (e, currentId) => {
    const currentIndex = toneOptions.findIndex((t) => t.id === currentId)
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault()
      const nextIndex = (currentIndex + 1) % toneOptions.length
      handleToneChange(toneOptions[nextIndex].id)
      document.getElementById(`btn-tone-${toneOptions[nextIndex].id}`)?.focus()
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault()
      const prevIndex = (currentIndex - 1 + toneOptions.length) % toneOptions.length
      handleToneChange(toneOptions[prevIndex].id)
      document.getElementById(`btn-tone-${toneOptions[prevIndex].id}`)?.focus()
    }
  }

  return (
    <div
      className="compass-toolbar-row"
      role="toolbar"
      aria-label="Assistant and planner toolbar"
    >
      {/* GROUP 1: Conversation (Left) */}
      <div className="compass-toolbar-group compass-toolbar-conversation">
        {/* Single amber primary button: New */}
        <button
          id="btn-chat-new"
          type="button"
          onClick={handleNewChat}
          disabled={isInputDisabled}
          className="btn-primary-amber compass-toolbar-btn"
          aria-label="Start new conversation"
          title="Start a fresh conversation"
          style={{
            cursor: isInputDisabled ? 'not-allowed' : 'pointer',
            opacity: isInputDisabled ? 0.6 : 1,
          }}
        >
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          <span>New</span>
        </button>

        {/* Secondary button: History & Memory with count badge */}
        <button
          id="btn-toggle-history-drawer"
          type="button"
          onClick={() => setShowHistoryDrawer((v) => !v)}
          className="btn-secondary compass-toolbar-btn"
          title="View previous chats, plans, and long-term memory"
          aria-label={`History and Memory (${pastConversations.length} past chats)`}
        >
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M12 8v4l3 3m6-3a9 9 0 1 1-18 0 9 9 0 0 1 18 0z" />
          </svg>
          <span className="compass-btn-text-long">History & Memory</span>
          <span className="compass-btn-text-short">History</span>
          <span className="compass-count-badge" aria-hidden="true">
            {pastConversations.length}
          </span>
        </button>
      </div>

      {/* Slim Divider between Group 1 & 2 */}
      <div className="compass-toolbar-divider" aria-hidden="true" />

      {/* GROUP 2: Response Style (Middle) */}
      <div className="compass-toolbar-group compass-toolbar-style">
        <div className="compass-style-container">
          <span className="compass-style-label" id="label-compass-style">
            Style
          </span>
          <div
            id="chat-tone-dial"
            role="radiogroup"
            aria-labelledby="label-compass-style"
            className="compass-style-segmented"
            title="Adjust assistant response style (Short, Normal, Detailed)"
          >
            {toneOptions.map((t) => {
              const isSelected = tone === t.id
              return (
                <button
                  key={t.id}
                  type="button"
                  id={`btn-tone-${t.id}`}
                  role="radio"
                  aria-checked={isSelected}
                  tabIndex={isSelected ? 0 : -1}
                  onClick={() => handleToneChange(t.id)}
                  onKeyDown={(e) => handleToneKeyDown(e, t.id)}
                  className={`compass-style-btn ${isSelected ? 'active' : ''}`}
                >
                  {t.label}
                </button>
              )
            })}
          </div>
        </div>
      </div>

      {/* Slim Divider between Group 2 & 3 */}
      <div className="compass-toolbar-divider" aria-hidden="true" />

      {/* GROUP 3: Status and Tools (Right) */}
      <div className="compass-toolbar-group compass-toolbar-tools">
        {/* Single Combined Status Chip */}
        <div className="compass-popover-anchor compass-toolbar-status-desktop" ref={statusAnchorRef}>
          <button
            id="btn-workspace-status"
            ref={statusBtnRef}
            type="button"
            onClick={() => {
              setStatusPopoverOpen((v) => !v)
              setToolsMenuOpen(false)
            }}
            className="btn-secondary compass-toolbar-btn compass-status-chip"
            aria-haspopup="dialog"
            aria-expanded={statusPopoverOpen}
            aria-label={`Status: ${statusMeta.ariaText}. Click to view details and toggle memory.`}
            title={`${statusMeta.text} - Click for workspace status and memory settings`}
          >
            <span
              className="compass-status-dot"
              style={{ background: statusMeta.dotColor }}
              aria-hidden="true"
            />
            <span style={{ fontSize: '12.5px' }}>{statusMeta.text}</span>
            <svg
              className={`compass-chevron ${statusPopoverOpen ? 'open' : ''}`}
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>

          {/* Desktop Status Popover */}
          {!isMobile && statusPopoverOpen && (
            <div
              className="compass-popover-panel"
              role="dialog"
              aria-label="Workspace and Memory Settings"
            >
              {/* Workspace Status Section */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span
                      style={{
                        width: '8px',
                        height: '8px',
                        borderRadius: '50%',
                        background: isOnline ? 'var(--domain-code, #1c8a62)' : 'var(--danger-text, #ef4444)',
                        display: 'inline-block',
                      }}
                    />
                    <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>
                      Workspace Connection
                    </span>
                  </div>
                  <span
                    style={{
                      fontSize: '11px',
                      color: isOnline ? 'var(--domain-code, #1c8a62)' : 'var(--danger-text, #ef4444)',
                      fontWeight: '600',
                      background: 'var(--bg-card-soft)',
                      padding: '2px 6px',
                      borderRadius: '4px',
                      border: '1px solid var(--border)',
                    }}
                  >
                    {isOnline ? 'Connected' : 'Offline'}
                  </span>
                </div>
                <p style={{ fontSize: '11.5px', color: 'var(--text-secondary)', margin: '2px 0 0 16px', lineHeight: 1.4 }}>
                  {isOnline
                    ? 'Connected to live database. All deadlines, edits and tasks are synced.'
                    : 'Backend server is connecting or offline. Demo data displayed.'}
                </p>
              </div>

              <div style={{ height: '1px', background: 'var(--border)', margin: '2px 0' }} />

              {/* Memory Active Toggle Section */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <svg
                      width="15"
                      height="15"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke={memoryActive ? 'var(--domain-code, #1c8a62)' : 'var(--text-muted)'}
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden="true"
                    >
                      <rect x="4" y="4" width="16" height="16" rx="2" />
                      <rect x="9" y="9" width="6" height="6" />
                    </svg>
                    <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>
                      Memory Active
                    </span>
                  </div>

                  {/* Toggle Switch */}
                  <button
                    type="button"
                    role="switch"
                    aria-checked={memoryActive}
                    onClick={onToggleMemoryActive}
                    style={{
                      width: '40px',
                      height: '22px',
                      borderRadius: '11px',
                      background: memoryActive ? 'var(--domain-code, #1c8a62)' : 'var(--border)',
                      border: 'none',
                      cursor: 'pointer',
                      position: 'relative',
                      transition: 'background-color 0.2s ease',
                      padding: 0,
                    }}
                    title={memoryActive ? 'Pause cross-session memory' : 'Enable cross-session memory'}
                    aria-label={`Toggle cross-session memory (currently ${memoryActive ? 'active' : 'paused'})`}
                  >
                    <span
                      style={{
                        position: 'absolute',
                        top: '2px',
                        left: memoryActive ? '20px' : '2px',
                        width: '18px',
                        height: '18px',
                        borderRadius: '50%',
                        background: '#ffffff',
                        transition: 'left 0.2s ease',
                        boxShadow: 'var(--shadow-sm)',
                      }}
                    />
                  </button>
                </div>
                <p style={{ fontSize: '11.5px', color: 'var(--text-secondary)', margin: '2px 0 0 23px', lineHeight: 1.4 }}>
                  {memoryActive
                    ? 'Long-term memory is active across sessions to prevent schedule clashes and remember key facts.'
                    : 'Long-term memory is paused. New chat messages will not write to persistent memory.'}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Tools Menu Button */}
        <div className="compass-popover-anchor" ref={toolsAnchorRef}>
          <button
            id="btn-toolbar-tools-menu"
            ref={toolsBtnRef}
            type="button"
            onClick={() => {
              setToolsMenuOpen((v) => !v)
              setStatusPopoverOpen(false)
            }}
            className="btn-secondary compass-toolbar-btn"
            aria-haspopup="menu"
            aria-expanded={toolsMenuOpen}
            aria-label={`Tools menu with ${parkedThoughts.length} parked thoughts`}
            title="Assistant tools: Context, Recap, and Parked Thoughts"
          >
            {isMobile && (
              <span
                className="compass-status-dot"
                style={{ background: statusMeta.dotColor }}
                aria-hidden="true"
              />
            )}
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
            <span>Tools</span>
            {/* Always visible count badge with Parked count */}
            <span className="compass-count-badge" aria-label={`${parkedThoughts.length} parked thoughts`}>
              {parkedThoughts.length}
            </span>
            {/* Amber dot when Parked > 0 so count is never hidden */}
            {parkedThoughts.length > 0 && (
              <span
                className="compass-amber-dot"
                title={`${parkedThoughts.length} parked thoughts waiting`}
                aria-hidden="true"
              />
            )}
            <svg
              className={`compass-chevron compass-tools-chevron ${toolsMenuOpen ? 'open' : ''}`}
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>

          {/* Desktop Tools Dropdown Menu */}
          {!isMobile && toolsMenuOpen && (
            <div
              className="compass-menu-dropdown"
              role="menu"
              aria-label="Assistant Tools"
            >
              {/* Tool 1: Show Context */}
              <button
                id="btn-toggle-context"
                type="button"
                role="menuitem"
                onClick={() => {
                  setShowContext((v) => !v)
                  setToolsMenuOpen(false)
                }}
                className="compass-menu-item"
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <svg
                    width="15"
                    height="15"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                  <span>{showContext ? 'Hide Context' : 'Show Context'}</span>
                </div>
                {tasks.length > 0 && (
                  <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                    {tasks.length} tasks
                  </span>
                )}
              </button>

              {/* Tool 2: Recap */}
              <button
                id="btn-chat-recap"
                type="button"
                role="menuitem"
                onClick={() => {
                  handleRecap()
                  setToolsMenuOpen(false)
                }}
                disabled={isInputDisabled}
                className="compass-menu-item"
                title="Summarize decisions made, open questions, and next steps"
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <svg
                    width="15"
                    height="15"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <line x1="16" y1="13" x2="8" y2="13" />
                    <line x1="16" y1="17" x2="8" y2="17" />
                    <polyline points="10 9 9 9 8 9" />
                  </svg>
                  <span>Recap</span>
                </div>
              </button>

              {/* Tool 3: Parked */}
              <button
                id="btn-toggle-parked"
                type="button"
                role="menuitem"
                onClick={() => {
                  setShowParkedShelf((v) => !v)
                  setToolsMenuOpen(false)
                }}
                className="compass-menu-item"
                title="Toggle Parked Thoughts Shelf"
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <svg
                    width="15"
                    height="15"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <line x1="12" y1="17" x2="12" y2="22" />
                    <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.89A2 2 0 0 1 15 10.77V6a3 3 0 0 0-6 0v4.77a2 2 0 0 1-1.11 1.79l-1.78.89A2 2 0 0 0 5 15.24Z" />
                  </svg>
                  <span>Parked Thoughts</span>
                </div>
                <span className="compass-count-badge">
                  {parkedThoughts.length}
                </span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* MOBILE BOTTOM SHEET (< 768px): Opens on status or tools click */}
      {isMobile && (statusPopoverOpen || toolsMenuOpen) && (
        <div
          className="compass-sheet-backdrop"
          onClick={() => {
            setStatusPopoverOpen(false)
            setToolsMenuOpen(false)
          }}
          role="presentation"
        >
          <div
            className="compass-bottom-sheet"
            role="dialog"
            aria-modal="true"
            aria-label="Assistant Settings and Tools"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Sheet Handle */}
            <div
              style={{
                width: '36px',
                height: '4px',
                borderRadius: '2px',
                background: 'var(--border)',
                margin: '0 auto 12px',
              }}
            />

            {/* Sheet Header */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                paddingBottom: '12px',
                borderBottom: '1px solid var(--border)',
                marginBottom: '16px',
              }}
            >
              <span style={{ fontSize: '15px', fontWeight: '700', color: 'var(--text-primary)' }}>
                {statusPopoverOpen ? 'Status & Memory' : 'Assistant Tools & Style'}
              </span>
              <button
                type="button"
                onClick={() => {
                  setStatusPopoverOpen(false)
                  setToolsMenuOpen(false)
                }}
                className="btn-secondary"
                style={{
                  minHeight: '36px',
                  height: '36px',
                  width: '36px',
                  padding: 0,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  borderRadius: 'var(--radius-btn, 6px)',
                  cursor: 'pointer',
                }}
                aria-label="Close bottom sheet"
              >
                ✕
              </button>
            </div>

            {/* Mobile Section 1: Response Style */}
            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-secondary)', marginBottom: '8px' }}>
                Response Style
              </div>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(3, 1fr)',
                  gap: '6px',
                  background: 'var(--bg-card-soft)',
                  padding: '4px',
                  borderRadius: 'var(--radius-btn, 6px)',
                  border: '1px solid var(--border)',
                }}
              >
                {toneOptions.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => handleToneChange(t.id)}
                    style={{
                      minHeight: '44px',
                      height: '44px',
                      borderRadius: 'calc(var(--radius-btn, 6px) - 2px)',
                      border: tone === t.id ? '1px solid var(--border)' : '1px solid transparent',
                      background: tone === t.id ? 'var(--bg-card)' : 'transparent',
                      color: tone === t.id ? 'var(--text-primary)' : 'var(--text-secondary)',
                      fontSize: '13px',
                      fontWeight: tone === t.id ? '600' : '500',
                      boxShadow: tone === t.id ? 'var(--shadow-sm)' : 'none',
                      cursor: 'pointer',
                    }}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Mobile Section 2: Workspace & Memory Status */}
            <div
              style={{
                background: 'var(--bg-card-soft)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-btn, 6px)',
                padding: '12px',
                marginBottom: '16px',
                display: 'flex',
                flexDirection: 'column',
                gap: '12px',
              }}
            >
              {/* Workspace connection item */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span
                    style={{
                      width: '8px',
                      height: '8px',
                      borderRadius: '50%',
                      background: isOnline ? 'var(--domain-code, #1c8a62)' : 'var(--danger-text, #ef4444)',
                    }}
                  />
                  <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>
                    Workspace
                  </span>
                </div>
                <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                  {isOnline ? 'Connected' : 'Offline'}
                </span>
              </div>

              {/* Memory Active toggle */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke={memoryActive ? 'var(--domain-code, #1c8a62)' : 'var(--text-muted)'}
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <rect x="4" y="4" width="16" height="16" rx="2" />
                    <rect x="9" y="9" width="6" height="6" />
                  </svg>
                  <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>
                    Memory Active
                  </span>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={memoryActive}
                  onClick={onToggleMemoryActive}
                  style={{
                    width: '42px',
                    height: '24px',
                    borderRadius: '12px',
                    background: memoryActive ? 'var(--domain-code, #1c8a62)' : 'var(--border)',
                    border: 'none',
                    cursor: 'pointer',
                    position: 'relative',
                    transition: 'background-color 0.2s ease',
                    padding: 0,
                  }}
                  aria-label={`Toggle cross-session memory (currently ${memoryActive ? 'active' : 'paused'})`}
                >
                  <span
                    style={{
                      position: 'absolute',
                      top: '2px',
                      left: memoryActive ? '20px' : '2px',
                      width: '20px',
                      height: '20px',
                      borderRadius: '50%',
                      background: '#ffffff',
                      transition: 'left 0.2s ease',
                      boxShadow: 'var(--shadow-sm)',
                    }}
                  />
                </button>
              </div>
            </div>

            {/* Mobile Section 3: Tools Actions */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <button
                type="button"
                onClick={() => {
                  setShowContext((v) => !v)
                  setStatusPopoverOpen(false)
                  setToolsMenuOpen(false)
                }}
                className="btn-secondary"
                style={{
                  minHeight: '44px',
                  width: '100%',
                  justifyContent: 'space-between',
                  padding: '0 14px',
                  borderRadius: 'var(--radius-btn, 6px)',
                  fontSize: '13px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                  <span>{showContext ? 'Hide Context' : 'Show Context'}</span>
                </div>
                {tasks.length > 0 && (
                  <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                    {tasks.length} tasks
                  </span>
                )}
              </button>

              <button
                type="button"
                onClick={() => {
                  handleRecap()
                  setStatusPopoverOpen(false)
                  setToolsMenuOpen(false)
                }}
                disabled={isInputDisabled}
                className="btn-secondary"
                style={{
                  minHeight: '44px',
                  width: '100%',
                  justifyContent: 'flex-start',
                  padding: '0 14px',
                  borderRadius: 'var(--radius-btn, 6px)',
                  fontSize: '13px',
                  opacity: isInputDisabled ? 0.5 : 1,
                  cursor: isInputDisabled ? 'not-allowed' : 'pointer',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <line x1="16" y1="13" x2="8" y2="13" />
                    <line x1="16" y1="17" x2="8" y2="17" />
                    <polyline points="10 9 9 9 8 9" />
                  </svg>
                  <span>Recap Conversation</span>
                </div>
              </button>

              <button
                type="button"
                onClick={() => {
                  setShowParkedShelf((v) => !v)
                  setStatusPopoverOpen(false)
                  setToolsMenuOpen(false)
                }}
                className="btn-secondary"
                style={{
                  minHeight: '44px',
                  width: '100%',
                  justifyContent: 'space-between',
                  padding: '0 14px',
                  borderRadius: 'var(--radius-btn, 6px)',
                  fontSize: '13px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="12" y1="17" x2="12" y2="22" />
                    <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.89A2 2 0 0 1 15 10.77V6a3 3 0 0 0-6 0v4.77a2 2 0 0 1-1.11 1.79l-1.78.89A2 2 0 0 0 5 15.24Z" />
                  </svg>
                  <span>Parked Thoughts</span>
                </div>
                <span className="compass-count-badge">
                  {parkedThoughts.length}
                </span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
