import React, { useState, useRef, useEffect, useCallback } from 'react'
import { X } from 'lucide-react'
import { DUE_OPTIONS, STATUS_OPTIONS } from './filterConstants'

function DueIcon({ type }) {
  if (type === 'overdue') {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
    )
  }
  if (type === 'due_today') {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect width="18" height="18" x="3" y="4" rx="2" />
        <line x1="16" y1="2" x2="16" y2="6" />
        <line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
        <circle cx="12" cy="15" r="1.5" fill="currentColor" />
      </svg>
    )
  }
  if (type === 'urgent') {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 2v4" />
        <path d="m4.93 4.93 2.83 2.83" />
        <path d="M2 12h4" />
        <circle cx="12" cy="12" r="7" />
        <polyline points="12 9 12 12 13.5 13.5" />
      </svg>
    )
  }
  if (type === 'due_soon') {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M5 22h14" />
        <path d="M5 2h14" />
        <path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22" />
        <path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2" />
      </svg>
    )
  }
  if (type === 'upcoming') {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect width="18" height="18" x="3" y="4" rx="2" />
        <line x1="16" y1="2" x2="16" y2="6" />
        <line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
        <path d="m10 14 2 2 4-4" />
      </svg>
    )
  }
  // Any time / all
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  )
}

export default function TimelineFilterBar({
  statusFilter = 'all',
  onStatusChange,
  dueFilter = 'all',
  onDueChange,
  statusCounts = {},
  dueCounts = {},
  baseOverdueCount = 0,
  totalCount = 0,
  filteredCount = 0,
  onClearFilters,
}) {
  const [isDueMenuOpen, setIsDueMenuOpen] = useState(false)
  const [focusedMenuIndex, setFocusedMenuIndex] = useState(-1)
  const dueTriggerRef = useRef(null)
  const menuContainerRef = useRef(null)
  const statusRefs = useRef([])

  const isFiltered = statusFilter !== 'all' || dueFilter !== 'all'
  const activeDueOption = DUE_OPTIONS.find((opt) => opt.key === dueFilter) || DUE_OPTIONS[0]
  const currentDueCount = dueCounts[dueFilter] ?? 0
  const hasOverdueAlert = baseOverdueCount > 0

  // Close menu on outside click
  useEffect(() => {
    if (!isDueMenuOpen) return

    function handlePointerDown(e) {
      if (
        menuContainerRef.current &&
        !menuContainerRef.current.contains(e.target) &&
        dueTriggerRef.current &&
        !dueTriggerRef.current.contains(e.target)
      ) {
        setIsDueMenuOpen(false)
      }
    }

    document.addEventListener('pointerdown', handlePointerDown)
    return () => document.removeEventListener('pointerdown', handlePointerDown)
  }, [isDueMenuOpen])

  // Close on Escape and restore focus
  useEffect(() => {
    if (!isDueMenuOpen) return

    function handleKeyDown(e) {
      if (e.key === 'Escape') {
        e.preventDefault()
        setIsDueMenuOpen(false)
        if (dueTriggerRef.current) dueTriggerRef.current.focus()
      } else if (e.key === 'ArrowDown') {
        e.preventDefault()
        setFocusedMenuIndex((prev) => (prev + 1) % DUE_OPTIONS.length)
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setFocusedMenuIndex((prev) => (prev <= 0 ? DUE_OPTIONS.length - 1 : prev - 1))
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isDueMenuOpen])

  // Keyboard navigation for Segmented Control (Left/Right arrows)
  const handleStatusKeyDown = useCallback(
    (e, currentIndex) => {
      let nextIndex = currentIndex
      if (e.key === 'ArrowRight') {
        e.preventDefault()
        nextIndex = (currentIndex + 1) % STATUS_OPTIONS.length
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        nextIndex = currentIndex <= 0 ? STATUS_OPTIONS.length - 1 : currentIndex - 1
      } else if (e.key === 'Home') {
        e.preventDefault()
        nextIndex = 0
      } else if (e.key === 'End') {
        e.preventDefault()
        nextIndex = STATUS_OPTIONS.length - 1
      }

      if (nextIndex !== currentIndex) {
        const nextOpt = STATUS_OPTIONS[nextIndex]
        onStatusChange(nextOpt.key)
        if (statusRefs.current[nextIndex]) {
          statusRefs.current[nextIndex].focus()
        }
      }
    },
    [onStatusChange]
  )

  const handleSelectDueOption = (key) => {
    onDueChange(key)
    setIsDueMenuOpen(false)
    if (dueTriggerRef.current) dueTriggerRef.current.focus()
  }

  const dueButtonLabel =
    dueFilter === 'all'
      ? `Due: Any time (${currentDueCount})`
      : `Due: ${activeDueOption.label} (${currentDueCount})`

  return (
    <div
      className="timeline-filter-toolbar"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '12px',
        marginBottom: '16px',
        maxWidth: '100%',
        boxSizing: 'border-box',
      }}
    >
      {/* Left controls: Status segmented control + Due menu button */}
      <div
        className="timeline-filter-controls-left"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          minWidth: 0,
          flexWrap: 'nowrap',
        }}
      >
        {/* Status Group: Segmented Control */}
        <div
          className="timeline-status-segmented-control"
          role="radiogroup"
          aria-label="Filter tasks by lifecycle status"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            background: 'var(--bg-card-soft)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-btn, 6px)',
            padding: '3px',
            gap: '2px',
            flexShrink: 0,
            overflowX: 'auto',
            maxWidth: '100%',
            WebkitOverflowScrolling: 'touch',
          }}
        >
          {STATUS_OPTIONS.map((opt, idx) => {
            const isSelected = statusFilter === opt.key
            const count = statusCounts[opt.key] ?? 0
            const isDimmed = count === 0 && !isSelected

            return (
              <button
                key={opt.key}
                ref={(el) => (statusRefs.current[idx] = el)}
                type="button"
                role="radio"
                id={`status-filter-${opt.key}`}
                aria-checked={isSelected}
                tabIndex={isSelected ? 0 : -1}
                onClick={() => onStatusChange(opt.key)}
                onKeyDown={(e) => handleStatusKeyDown(e, idx)}
                className={`timeline-status-segment-btn ${isSelected ? 'active' : ''}`}
                style={{
                  minHeight: '44px',
                  padding: '0 12px',
                  borderRadius: 'calc(var(--radius-btn, 6px) - 2px)',
                  border: isSelected ? '1px solid var(--border)' : '1px solid transparent',
                  background: isSelected ? 'var(--bg-card)' : 'transparent',
                  color: isSelected ? 'var(--text-primary)' : 'var(--text-secondary)',
                  fontWeight: isSelected ? '600' : '500',
                  fontSize: '13px',
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '5px',
                  whiteSpace: 'nowrap',
                  boxShadow: isSelected ? 'var(--shadow-sm)' : 'none',
                  transition: 'background 0.15s ease, color 0.15s ease',
                  flexShrink: 0,
                }}
              >
                <span>{opt.label}</span>
                <span
                  style={{
                    fontSize: '12px',
                    fontWeight: isSelected ? '700' : '600',
                    color: isSelected ? 'var(--tab-active-text)' : 'var(--text-secondary)',
                  }}
                >
                  ({count})
                </span>
              </button>
            )
          })}
        </div>

        {/* Due Group: Dropdown Trigger & Menu */}
        <div className="timeline-due-dropdown-anchor" style={{ position: 'relative', flexShrink: 0 }}>
          <button
            ref={dueTriggerRef}
            type="button"
            id="timeline-btn-due-dropdown"
            aria-haspopup="menu"
            aria-expanded={isDueMenuOpen}
            aria-controls="timeline-due-dropdown-menu"
            onClick={() => {
              setIsDueMenuOpen((prev) => !prev)
              setFocusedMenuIndex(DUE_OPTIONS.findIndex((o) => o.key === dueFilter))
            }}
            className={`timeline-due-btn btn-secondary ${dueFilter !== 'all' ? 'active-due' : ''}`}
            style={{
              minHeight: '44px',
              padding: '0 12px',
              borderRadius: 'var(--radius-btn, 6px)',
              border: dueFilter !== 'all' ? '1px solid var(--accent, #f5a623)' : '1px solid var(--border)',
              background: dueFilter !== 'all' ? 'var(--bg-card)' : 'var(--bg-card-soft)',
              color: dueFilter !== 'all' ? 'var(--text-primary)' : 'var(--text-secondary)',
              fontWeight: dueFilter !== 'all' ? '600' : '500',
              fontSize: '13px',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              whiteSpace: 'nowrap',
              boxShadow: dueFilter !== 'all' ? 'var(--shadow-sm)' : 'none',
              transition: 'all 0.15s ease',
            }}
            title="Filter tasks by due date timing"
          >
            <span style={{ display: 'inline-flex', alignItems: 'center', color: dueFilter !== 'all' ? 'var(--accent, #f5a623)' : 'currentColor' }}>
              <DueIcon type={dueFilter} />
            </span>

            <span>{dueButtonLabel}</span>

            {/* Overdue alert indicator dot */}
            {hasOverdueAlert && (
              <span
                id="timeline-due-overdue-dot"
                title={`${baseOverdueCount} overdue task(s)`}
                aria-label={`${baseOverdueCount} overdue task(s)`}
                style={{
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  background: '#ef4444',
                  boxShadow: '0 0 0 2px var(--bg-card)',
                  display: 'inline-block',
                  flexShrink: 0,
                }}
              />
            )}

            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              style={{
                transform: isDueMenuOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                transition: 'transform 0.15s ease',
                color: 'var(--text-muted)',
                marginLeft: '2px',
              }}
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>

          {/* Desktop & Mobile Dropdown Menu / Bottom Sheet */}
          {isDueMenuOpen && (
            <>
              {/* Mobile Sheet Backdrop (hidden on desktop via CSS) */}
              <div
                className="timeline-due-sheet-backdrop"
                onClick={() => setIsDueMenuOpen(false)}
                aria-hidden="true"
              />

              <div
                ref={menuContainerRef}
                id="timeline-due-dropdown-menu"
                role="menu"
                aria-orientation="vertical"
                aria-labelledby="timeline-btn-due-dropdown"
                className="timeline-due-dropdown-panel"
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-btn, 6px)',
                  boxShadow: 'var(--shadow-lg)',
                  padding: '6px',
                }}
              >
                {/* Mobile Bottom Sheet Header */}
                <div className="timeline-due-sheet-header">
                  <span style={{ fontWeight: '600', fontSize: '14px', color: 'var(--text-primary)' }}>
                    Filter by Due Date
                  </span>
                  <button
                    type="button"
                    onClick={() => setIsDueMenuOpen(false)}
                    aria-label="Close due menu"
                    className="timeline-sheet-close-btn"
                  >
                    <X size={15} strokeWidth={1.8} />
                  </button>
                </div>

                <div className="timeline-due-menu-items-list" style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                  {DUE_OPTIONS.map((opt, i) => {
                    const isSelected = dueFilter === opt.key
                    const count = dueCounts[opt.key] ?? 0
                    const isDimmed = count === 0 && !isSelected
                    const isFocused = focusedMenuIndex === i

                    return (
                      <button
                        key={opt.key}
                        type="button"
                        role="menuitem"
                        id={`due-option-${opt.key}`}
                        aria-selected={isSelected}
                        tabIndex={isSelected || isFocused ? 0 : -1}
                        onClick={() => handleSelectDueOption(opt.key)}
                        className={`timeline-due-menu-item ${isSelected ? 'active' : ''} ${isFocused ? 'focused' : ''}`}
                        style={{
                          minHeight: '44px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: '12px',
                          padding: '0 12px',
                          borderRadius: 'var(--radius-btn, 6px)',
                          border: 'none',
                          background: isSelected
                            ? 'var(--bg-card-soft)'
                            : isFocused
                            ? 'var(--sidebar-hover)'
                            : 'transparent',
                          color: isSelected ? 'var(--text-primary)' : 'var(--text-secondary)',
                          fontWeight: isSelected ? '600' : '500',
                          fontSize: '13px',
                          cursor: 'pointer',
                          width: '100%',
                          textAlign: 'left',
                          opacity: isDimmed ? 0.45 : 1,
                          transition: 'background 0.12s ease',
                          boxSizing: 'border-box',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{ color: isSelected ? 'var(--accent, #f5a623)' : 'var(--text-muted)', display: 'inline-flex', alignItems: 'center' }}>
                            <DueIcon type={opt.key} />
                          </span>
                          <span>{opt.label}</span>
                          {opt.key === 'overdue' && baseOverdueCount > 0 && (
                            <span
                              style={{
                                width: '6px',
                                height: '6px',
                                borderRadius: '50%',
                                background: '#ef4444',
                                display: 'inline-block',
                              }}
                            />
                          )}
                        </div>

                        <span
                          style={{
                            fontSize: '11.5px',
                            fontWeight: isSelected ? '700' : '500',
                            color: isSelected ? 'var(--accent, #f5a623)' : 'var(--text-muted)',
                            background: 'var(--bg-card-soft)',
                            padding: '2px 7px',
                            borderRadius: '10px',
                          }}
                        >
                          {count}
                        </span>
                      </button>
                    )
                  })}
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Right controls: Result line & Clear filters action */}
      <div
        className="timeline-filter-controls-right"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          flexShrink: 0,
        }}
      >
        <span
          id="timeline-filter-result-line"
          style={{
            fontSize: '12.5px',
            color: 'var(--text-secondary)',
            fontWeight: '500',
            whiteSpace: 'nowrap',
          }}
        >
          Showing {filteredCount} of {totalCount} task{totalCount === 1 ? '' : 's'}
        </span>

        {isFiltered && (
          <button
            type="button"
            id="timeline-btn-clear-filters"
            onClick={onClearFilters}
            className="btn-touch-target"
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--accent, #f5a623)',
              fontSize: '12.5px',
              fontWeight: '600',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              padding: '6px 8px',
              borderRadius: 'var(--radius-btn, 6px)',
              minHeight: '44px',
              transition: 'opacity 0.15s ease',
            }}
            title="Reset filters to All Tasks and Any time"
          >
            <span>Clear filters</span>
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        )}
      </div>
    </div>
  )
}
