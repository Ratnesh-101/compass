import React, { useState, useEffect, useRef } from 'react'
import { filterSpecialists } from '../../api/specialistRegistry'
import { Send, X } from 'lucide-react'
import Logo from '../Logo'

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
    onSend(input.trim(), null, activeSpecialist ? activeSpecialist.id : null)
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
    <div className="chat-input-container" style={{ padding: '14px 20px 20px', background: 'var(--bg-app)', flexShrink: 0, position: 'relative' }}>
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
            left: '20px',
            right: '20px',
            marginBottom: '10px',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-card, 8px)',
            boxShadow: 'none',
            zIndex: 100,
            overflow: 'hidden',
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
            <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-secondary)', letterSpacing: '0.04em' }}>
              SPECIALIST AGENTS
            </span>
            <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
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
                      borderRadius: 'var(--radius-btn, 6px)',
                      background: isSelected ? 'var(--bg-card-soft)' : 'transparent',
                      border: isSelected ? '1px solid var(--border)' : '1px solid transparent',
                      cursor: 'pointer',
                      transition: 'all 0.12s ease',
                    }}
                  >
                    {spec.icon === 'compass' ? (
                      <Logo size={16} alt="" />
                    ) : (
                      <span style={{ fontSize: '16px', flexShrink: 0 }}>{spec.icon}</span>
                    )}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontWeight: '600', fontSize: '13px', color: 'var(--text-primary)' }}>
                          {spec.name}
                        </span>
                        <span style={{ fontSize: '11px', color: 'var(--text-secondary)', background: 'var(--bg-card-soft)', padding: '1px 6px', borderRadius: 'var(--radius-btn, 6px)' }}>
                          {spec.command}
                        </span>
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {spec.description}
                      </div>
                    </div>
                  </div>
                )
              })
            ) : (
              <div style={{ padding: '16px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '12px' }}>
                No specialist agents matching "/{slashQuery}"
              </div>
            )}
          </div>
        </div>
      )}

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
            borderRadius: 'var(--radius-btn, 6px)',
            background: 'var(--bg-card-soft)',
            border: '1px solid var(--border)',
            fontSize: '12px',
            fontWeight: '600',
            color: 'var(--text-primary)',
          }}>
            {activeSpecialist.icon === 'compass' ? (
              <Logo size={14} alt="" />
            ) : (
              <span>{activeSpecialist.icon}</span>
            )}
            <span>{activeSpecialist.name}</span>
            <span style={{ fontSize: '11px', color: 'var(--text-secondary)', fontWeight: '400' }}>({activeSpecialist.command})</span>
            <button
              type="button"
              onClick={() => setActiveSpecialist(null)}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-secondary)',
                fontSize: '14px',
                cursor: 'pointer',
                padding: '0 2px',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              title="Remove specialist (switch to standard Chat Copilot)"
            >
              <X size={13} strokeWidth={1.8} />
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
              padding: '0 16px',
              minHeight: '44px',
              borderRadius: 'var(--radius-btn, 6px)',
              background: isInputDisabled ? 'var(--bg-card-soft)' : 'var(--bg-card)',
              border: '1px solid var(--border)',
              color: isInputDisabled ? 'var(--text-secondary)' : 'var(--text-primary)',
              fontSize: '13px',
              outline: 'none',
              cursor: isInputDisabled ? 'not-allowed' : 'text',
              boxSizing: 'border-box',
            }}
          />
          <button
            type="submit"
            className="btn-primary-amber"
            disabled={isInputDisabled || !input.trim()}
            style={{
              padding: '0 20px',
              minHeight: '44px',
              borderRadius: 'var(--radius-btn, 6px)',
              fontWeight: '600',
              fontSize: '13px',
              cursor: (isInputDisabled || !input.trim()) ? 'not-allowed' : 'pointer',
              opacity: (!input.trim() || isInputDisabled) ? 0.5 : 1,
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
            }}>
            <span>Send</span>
            <Send size={14} strokeWidth={1.8} />
          </button>
        </div>
      </form>
    </div>
  )
}
