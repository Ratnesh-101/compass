import React, { useState, useEffect, useRef } from 'react'
import { SPECIALIST_AGENTS, filterSpecialists, getSpecialistById } from '../../api/specialistRegistry'

const QUICK_PROMPTS = [
  { icon: '⚠️', text: 'Check my weekend schedule for conflicts across hackathon and coursework', specialistId: 'calendar' },
  { icon: '🧠', text: 'Why did we choose 768-dim Matryoshka embeddings for pgvector?', specialistId: 'memory' },
  { icon: '🌐', text: 'Verify the Nebius hackathon deadline on Devpost', specialistId: 'research' },
  { icon: '📚', text: "Review CS 61C RISC-V pipeline lab notes and coursework tasks", specialistId: 'coursework' }
]

export default function ChatInputBar({
  input,
  setInput,
  onSend,
  isInputDisabled,
  isStreaming,
  activeSpecialist,
  setActiveSpecialist,
}) {
  const [showSlashPicker, setShowSlashPicker] = useState(false)
  const [slashQuery, setSlashQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)

  const inputRef = useRef(null)
  const pickerRef = useRef(null)

  // Filter specialists dynamically as user types after '/'
  const filteredSpecialists = filterSpecialists(slashQuery)

  // Handle typing input and slash detector
  const handleInputChange = (e) => {
    const val = e.target.value
    setInput(val)

    // Check if input begins with '/' or contains a slash command
    if (val.startsWith('/')) {
      const match = val.match(/^\/([a-zA-Z0-9_-]*)/)
      if (match) {
        setShowSlashPicker(true)
        setSlashQuery(match[1])
        setSelectedIndex(0)
        return
      }
    }

    setShowSlashPicker(false)
    setSlashQuery('')
  }

  const handleSelectSpecialist = (spec) => {
    setActiveSpecialist(spec)
    setShowSlashPicker(false)
    setSlashQuery('')

    // Remove slash command prefix from input
    if (input.startsWith('/')) {
      const cleaned = input.replace(/^\/[a-zA-Z0-9_-]*\s*/, '')
      setInput(cleaned)
    }

    if (inputRef.current) {
      inputRef.current.focus()
    }
  }

  const handleKeyDown = (e) => {
    if (showSlashPicker && filteredSpecialists.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedIndex((prev) => (prev + 1) % filteredSpecialists.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedIndex((prev) => (prev - 1 + filteredSpecialists.length) % filteredSpecialists.length)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        const selected = filteredSpecialists[selectedIndex] || filteredSpecialists[0]
        if (selected) {
          handleSelectSpecialist(selected)
        }
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setShowSlashPicker(false)
        return
      }
    }

    // Clear active specialist on backspace when input is empty
    if (e.key === 'Backspace' && !input && activeSpecialist) {
      setActiveSpecialist(null)
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!input.trim() || isInputDisabled) return
    onSend(input.trim(), activeSpecialist ? activeSpecialist.id : null)
  }

  const handleQuickPromptClick = (item) => {
    if (isInputDisabled) return
    if (item.specialistId) {
      const spec = getSpecialistById(item.specialistId)
      if (spec) setActiveSpecialist(spec)
    }
    onSend(item.text, item.specialistId || (activeSpecialist ? activeSpecialist.id : null))
  }

  // Close picker when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target) && inputRef.current && !inputRef.current.contains(e.target)) {
        setShowSlashPicker(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <div className="chat-input-container" style={{ padding: '14px 24px 20px', background: 'var(--bg-app)', flexShrink: 0, position: 'relative' }}>
      {/* Slash Command Specialist Picker Modal */}
      {showSlashPicker && (
        <div
          ref={pickerRef}
          id="slash-specialist-picker"
          role="listbox"
          aria-label="Specialist Agents Slash Command Picker"
          style={{
            position: 'absolute',
            bottom: '100%',
            left: '24px',
            right: '24px',
            marginBottom: '10px',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: '12px',
            boxShadow: 'var(--shadow-lg)',
            zIndex: 100,
            overflow: 'hidden',
            backdropFilter: 'blur(10px)',
          }}
        >
          <div style={{
            padding: '10px 14px',
            borderBottom: '1px solid var(--border)',
            background: 'var(--bg-card-soft)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}>
            <span style={{ fontSize: '12px', fontWeight: '700', color: 'var(--text-secondary)', letterSpacing: '0.04em' }}>
              SPECIALIST AGENTS
            </span>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              Use ↑↓ to navigate, Enter to select, Esc to dismiss
            </span>
          </div>

          <div style={{ maxHeight: '240px', overflowY: 'auto', padding: '6px' }}>
            {filteredSpecialists.length > 0 ? (
              filteredSpecialists.map((spec, idx) => {
                const isSelected = idx === selectedIndex
                return (
                  <div
                    key={spec.id}
                    id={`slash-item-${spec.id}`}
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => handleSelectSpecialist(spec)}
                    onMouseEnter={() => setSelectedIndex(idx)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '12px',
                      padding: '10px 12px',
                      borderRadius: '8px',
                      background: isSelected ? 'rgba(255, 255, 255, 0.08)' : 'transparent',
                      border: isSelected ? `1px solid ${spec.border}` : '1px solid transparent',
                      cursor: 'pointer',
                      transition: 'all 0.12s ease',
                    }}
                  >
                    <span style={{ fontSize: '18px', flexShrink: 0 }}>{spec.icon}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontWeight: '700', fontSize: '13px', color: spec.color }}>
                          {spec.name}
                        </span>
                        <span style={{ fontSize: '11px', color: 'var(--text-muted)', background: 'var(--bg-card-soft)', padding: '1px 6px', borderRadius: '4px' }}>
                          {spec.command}
                        </span>
                      </div>
                      <div style={{ fontSize: '11.5px', color: 'var(--text-secondary)', marginTop: '2px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {spec.description}
                      </div>
                    </div>
                  </div>
                )
              })
            ) : (
              <div style={{ padding: '16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12.5px' }}>
                No specialist agents matching "/{slashQuery}"
              </div>
            )}
          </div>
        </div>
      )}

      {/* Quick prompt suggestions */}
      <div className="quick-prompts-scroll" style={{ display: 'flex', gap: '8px', marginBottom: '10px', overflowX: 'auto', overflowY: 'hidden', paddingBottom: '6px' }}>
        {QUICK_PROMPTS.map((item, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => handleQuickPromptClick(item)}
            disabled={isInputDisabled}
            style={{
              padding: '6px 12px',
              borderRadius: '20px',
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              color: 'var(--text-secondary)',
              fontSize: '11.5px',
              fontWeight: '500',
              cursor: isInputDisabled ? 'not-allowed' : 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              whiteSpace: 'nowrap',
              transition: 'all 0.15s ease',
              boxShadow: 'var(--shadow-sm)',
              flexShrink: 0
            }}
            onMouseEnter={e => {
              if (!isInputDisabled) {
                e.currentTarget.style.borderColor = 'var(--brand)'
                e.currentTarget.style.color = 'var(--text-primary)'
                e.currentTarget.style.background = 'var(--bg-card-soft)'
              }
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = 'var(--border)'
              e.currentTarget.style.color = 'var(--text-secondary)'
              e.currentTarget.style.background = 'var(--bg-card)'
            }}
          >
            <span>{item.icon}</span>
            <span>{item.text}</span>
          </button>
        ))}
      </div>

      {/* Composer Container */}
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {/* Active Specialist Pill Badge */}
        {activeSpecialist && (
          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            alignSelf: 'flex-start',
            gap: '8px',
            padding: '4px 10px',
            borderRadius: '6px',
            background: activeSpecialist.bg,
            border: `1px solid ${activeSpecialist.border}`,
            fontSize: '12px',
            fontWeight: '700',
            color: activeSpecialist.color,
          }}>
            <span>{activeSpecialist.icon}</span>
            <span>{activeSpecialist.name}</span>
            <span style={{ fontSize: '11px', opacity: 0.7, fontWeight: '500' }}>({activeSpecialist.command})</span>
            <button
              type="button"
              onClick={() => setActiveSpecialist(null)}
              style={{
                background: 'transparent',
                border: 'none',
                color: activeSpecialist.color,
                fontSize: '14px',
                cursor: 'pointer',
                padding: '0 2px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                lineHeight: 1,
              }}
              title="Remove specialist (switch to standard Chat Copilot)"
            >
              ✕
            </button>
          </div>
        )}

        <div style={{ display: 'flex', gap: '10px', width: '100%' }}>
          <input
            ref={inputRef}
            type="text"
            className="chat-input-box"
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder={
              isStreaming
                ? 'Streaming response...'
                : activeSpecialist
                ? activeSpecialist.placeholder
                : 'Ask Compass anything, or type "/" to pick a Specialist Agent...'
            }
            disabled={isInputDisabled}
            style={{
              flex: 1,
              padding: '13px 17px',
              borderRadius: '10px',
              background: isInputDisabled ? 'var(--bg-card-soft)' : 'var(--bg-card)',
              border: activeSpecialist ? `1px solid ${activeSpecialist.border}` : '1px solid var(--border)',
              color: isInputDisabled ? 'var(--text-muted)' : 'var(--text-primary)',
              fontSize: '13.5px',
              outline: 'none',
              cursor: isInputDisabled ? 'not-allowed' : 'text',
              boxShadow: activeSpecialist ? `0 0 12px ${activeSpecialist.bg}` : 'none',
              transition: 'all 0.15s ease',
            }}
          />
          <button
            type="submit"
            className="chat-send-btn btn-touch-target"
            disabled={isInputDisabled || !input.trim()}
            style={{
              padding: '0 24px',
              borderRadius: '10px',
              background: activeSpecialist ? activeSpecialist.color : 'var(--brand)',
              border: 'none',
              color: '#18181b',
              fontWeight: '700',
              fontSize: '13px',
              cursor: (isInputDisabled || !input.trim()) ? 'not-allowed' : 'pointer',
              opacity: (!input.trim() || isInputDisabled) ? 0.5 : 1,
              transition: 'opacity 0.15s ease, background 0.15s ease'
            }}>
            Send
          </button>
        </div>
      </form>
    </div>
  )
}
