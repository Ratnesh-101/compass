import React, { useState } from 'react'

export default function DarkModeToggle({
  isDarkMode,
  onToggleDarkMode,
  id = 'header-theme-toggle',
}) {
  const [isHovered, setIsHovered] = useState(false)

  if (!onToggleDarkMode) return null

  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={isDarkMode}
      aria-label={`Switch to ${isDarkMode ? 'Light' : 'Dark'} Mode`}
      title={`Switch to ${isDarkMode ? 'Light' : 'Dark'} Mode`}
      onClick={() => onToggleDarkMode()}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: isHovered ? 'var(--fill-ghost-hover)' : 'transparent',
        border: 'none',
        borderRadius: '8px',
        cursor: 'pointer',
        fontSize: '20px',
        lineHeight: 1,
        padding: '6px 8px',
        color: 'var(--text-primary)',
        transition: 'background-color 0.15s ease',
        flexShrink: 0,
      }}
    >
      <span style={{ fontSize: '20px', lineHeight: 1 }}>
        {isDarkMode ? '☀️' : '🌙'}
      </span>
    </button>
  )
}
