import React, { useMemo, useState, useEffect } from 'react'
import EvidenceCard from './EvidenceCard'
import { fetchPersonaPhrases } from '../../api/chatApi'

const DEFAULT_STARTING_PHRASES = [
  "Where should we begin?",
  "Ready when you are.",
  "Pick a direction, or just start talking and we'll find one.",
  "No wrong place to start. What's pulling at you?",
  "Half-formed thoughts welcome.",
  "Take your time. I'm not going anywhere.",
]

const DEFAULT_RETURNING_PHRASES = [
  "You returned! Want to pick up where we left off, or start somewhere new?",
  "Welcome back. What changed since last time?",
  "Good to see you again. Where shall we dive in?",
  "Ready to pick up the thread, or start somewhere fresh?",
]

const SUGGESTION_CHIPS = [
  "Let's noodle on something",
  "What's due this week?",
  "Recap where I left off",
]

function getTimeGreeting() {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

function getEmptyStateGreeting(isReturning, userName, startingPool = DEFAULT_STARTING_PHRASES, returningPool = DEFAULT_RETURNING_PHRASES) {
  const pool = (isReturning ? returningPool : startingPool) || DEFAULT_STARTING_PHRASES
  const storageKey = isReturning ? 'compass_last_returning_phrase_idx' : 'compass_last_starting_phrase_idx'
  let lastIdx = -1
  try {
    const val = localStorage.getItem(storageKey)
    if (val !== null) lastIdx = parseInt(val, 10)
  } catch {}

  let candidates = pool.map((_, i) => i).filter(i => isNaN(lastIdx) || i !== lastIdx)
  if (candidates.length === 0) candidates = pool.map((_, i) => i)

  const chosenIdx = candidates[Math.floor(Math.random() * candidates.length)]
  try {
    localStorage.setItem(storageKey, String(chosenIdx))
  } catch {}

  let phrase = pool[chosenIdx] || pool[0] || "Where should we begin?"

  if (userName && isReturning) {
    if (phrase.includes("Welcome back.")) {
      phrase = `Welcome back, ${userName}. What changed since last time?`
    } else if (phrase.includes("You returned!")) {
      phrase = `Welcome back, ${userName}! Want to pick up where we left off, or start somewhere new?`
    } else if (phrase.includes("Good to see you again.")) {
      phrase = `Good to see you again, ${userName}. Where shall we dive in?`
    }
  }

  // 15% chance of subtle time-aware touch
  if (Math.random() < 0.15) {
    const hour = new Date().getHours()
    let touch = null
    if (hour >= 23 || hour < 5) touch = "Burning the midnight oil."
    else if (hour >= 5 && hour < 8) touch = "Early start today."
    else if (hour >= 8 && hour < 12) touch = "Morning focus."
    else if (hour >= 18 && hour < 23) touch = "Evening unwind."
    if (touch) {
      phrase = `${touch} ${phrase}`
    }
  }

  return phrase
}

/**
 * Preserves formatting, line breaks, bullet points, and router latency chips
 */
function renderFormattedMessage(text) {
  if (!text) return null
  const lines = text.split('\n')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
      {lines.map((line, i) => {
        const trimmed = line.trim()

        // 1. Router Latency Badge Chip (⚡ [Routed via Nemotron-3 Nano in 342ms])
        if (line.includes('Routed via Nemotron-3 Nano') || line.includes('⚡')) {
          return (
            <div key={i} className="router-chip">
              <span style={{ fontSize: '13px' }}>⚡</span>
              <span>{line.replace('⚡', '').trim()}</span>
            </div>
          )
        }

        // 2. Coursework Deliverables Heading
        if (line.includes('Coursework') && (line.includes('📚') || line.includes('CS 61C'))) {
          return (
            <div key={i} style={{ marginTop: '10px', marginBottom: '4px', color: 'var(--coursework-text)', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className="badge-coursework" style={{ padding: '2px 8px', borderRadius: '20px', fontSize: '11px', textTransform: 'uppercase' }}>
                Coursework
              </span>
              <span>{line.replace(/^\d+\.\s*/, '').replace('📚', '').trim()}</span>
            </div>
          )
        }

        // 3. Hackathon Deliverables Heading
        if (line.includes('Hackathon') && (line.includes('🚀') || line.includes('Nebius'))) {
          return (
            <div key={i} style={{ marginTop: '10px', marginBottom: '4px', color: 'var(--hackathon-text)', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className="badge-hackathon" style={{ padding: '2px 8px', borderRadius: '20px', fontSize: '11px', textTransform: 'uppercase' }}>
                Hackathon
              </span>
              <span>{line.replace(/^\d+\.\s*/, '').replace('🚀', '').trim()}</span>
            </div>
          )
        }

        // 4. Actionable Next Step Callout
        if (line.includes('Next Step:')) {
          return (
            <div key={i} style={{ marginTop: '12px', padding: '10px 14px', borderRadius: '10px', background: 'var(--bg-card-soft)', border: '1px solid var(--border)', color: 'var(--code-text)', fontSize: '12.5px', fontFamily: 'JetBrains Mono, monospace', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ color: 'var(--code)' }}>❯</span>
              <span>{line}</span>
            </div>
          )
        }

        // 5. Bullet Points (• or -)
        if (trimmed.startsWith('•') || trimmed.startsWith('-')) {
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', margin: '3px 0 3px 6px', color: 'var(--text-primary)', fontSize: '13.5px' }}>
              <span style={{ color: 'var(--coursework)', fontWeight: '700', lineHeight: '1.4' }}>•</span>
              <span style={{ lineHeight: '1.5' }}>{trimmed.replace(/^[•-]\s*/, '')}</span>
            </div>
          )
        }

        // 6. Empty Lines / Spacing
        if (!trimmed) {
          return <div key={i} style={{ height: '6px' }} />
        }

        // 7. Regular Text Paragraph
        return (
          <p key={i} style={{ margin: '2px 0', lineHeight: '1.6', color: 'var(--text-primary)' }}>
            {line}
          </p>
        )
      })}
    </div>
  )
}

export default function ChatMessageList({
  messages,
  isStreaming,
  streamingText,
  isTyping,
  messagesEndRef,
  profileFacts = {},
  pastConversations = [],
  onSendMessage,
}) {
  const [startingPhrases, setStartingPhrases] = useState(DEFAULT_STARTING_PHRASES)
  const [returningPhrases, setReturningPhrases] = useState(DEFAULT_RETURNING_PHRASES)

  useEffect(() => {
    let isMounted = true
    fetchPersonaPhrases().then((data) => {
      if (!isMounted || !data) return
      if (Array.isArray(data.starting_phrases) && data.starting_phrases.length > 0) {
        setStartingPhrases(data.starting_phrases)
      }
      if (Array.isArray(data.returning_phrases) && data.returning_phrases.length > 0) {
        setReturningPhrases(data.returning_phrases)
      }
    }).catch(() => {})
    return () => {
      isMounted = false
    }
  }, [])

  const isReturning = Boolean(
    (pastConversations && pastConversations.length > 0) ||
    (profileFacts && (profileFacts.name || Object.keys(profileFacts).length > 0))
  )
  const userName = profileFacts?.name || null

  const greeting = useMemo(() => {
    return getEmptyStateGreeting(isReturning, userName, startingPhrases, returningPhrases)
  }, [isReturning, userName, startingPhrases, returningPhrases])

  const showEmptyState = messages.length === 0 && !isStreaming

  return (
    <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', padding: '24px 28px', minWidth: 0 }}>
      {showEmptyState ? (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          margin: 'auto 0',
          padding: '40px 20px',
          textAlign: 'center',
        }}>
          <div style={{
            width: '56px',
            height: '56px',
            borderRadius: '16px',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '26px',
            marginBottom: '18px',
            boxShadow: 'var(--shadow-sm)',
          }}>
            🧭
          </div>

          <h2 className="serif-accent" style={{
            fontSize: '22px',
            fontWeight: '600',
            color: 'var(--text-primary)',
            marginBottom: '10px',
            maxWidth: '560px',
            lineHeight: '1.4',
          }}>
            {greeting}
          </h2>

          <p style={{
            fontSize: '13.5px',
            color: 'var(--text-secondary)',
            marginBottom: '26px',
            maxWidth: '480px',
            lineHeight: '1.5',
          }}>
            {userName
              ? `I have your personal context and preferences loaded. Think out loud, plan your week, or pick a direction.`
              : `Your warm thinking partner for coursework, deadlines, and hackathons. No wrong place to start.`
            }
          </p>

          {/* Suggestion Chips */}
          <div style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '10px',
            justifyContent: 'center',
            maxWidth: '520px',
          }}>
            {SUGGESTION_CHIPS.map((chip, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => onSendMessage && onSendMessage(chip)}
                className="persona-suggestion-chip"
              >
                <span style={{ color: 'var(--coursework)', fontSize: '14px' }}>✦</span>
                <span>{chip}</span>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <>
          <div className="serif-accent" style={{ fontSize: '15px', color: 'var(--text-secondary)', marginBottom: '18px' }}>
            {getTimeGreeting()}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {messages.map((msg, idx) => (
              <div key={idx} style={{ display: 'flex', gap: '10px', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
                {msg.role === 'assistant' && (
                  <div style={{
                    width: '30px', height: '30px', borderRadius: '8px', background: 'var(--bg-sidebar)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '14px', flexShrink: 0
                  }}>
                    🧭
                  </div>
                )}
                <div style={{
                  maxWidth: '75%',
                  padding: '13px 17px',
                  borderRadius: '14px',
                  background: msg.role === 'user' ? 'var(--bg-sidebar)' : 'var(--bg-card)',
                  color: msg.role === 'user' ? 'var(--text-on-dark)' : 'var(--text-primary)',
                  fontSize: '13.5px',
                  lineHeight: '1.5',
                  border: msg.role === 'user' ? 'none' : '1px solid var(--border)',
                  boxShadow: 'var(--shadow-sm)'
                }}>
                  {msg.role === 'user' ? msg.text : renderFormattedMessage(msg.text)}
                  {msg.role === 'assistant' && msg.evidence && (
                    <EvidenceCard evidence={msg.evidence} />
                  )}
                </div>
              </div>
            ))}

            {/* Active Progressive Token Streaming Bubble */}
            {isStreaming && (
              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-start' }}>
                <div style={{
                  width: '30px', height: '30px', borderRadius: '8px', background: 'var(--bg-sidebar)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '14px', flexShrink: 0
                }}>
                  🧭
                </div>
                <div style={{
                  maxWidth: '75%',
                  padding: '13px 17px',
                  borderRadius: '14px',
                  background: 'var(--bg-card)',
                  color: 'var(--text-primary)',
                  fontSize: '13.5px',
                  lineHeight: '1.5',
                  border: '1px solid var(--border)',
                  boxShadow: 'var(--shadow-md)'
                }}>
                  {renderFormattedMessage(streamingText)}
                  <span className="streaming-caret" style={{ background: 'var(--coursework)' }} />
                </div>
              </div>
            )}

            {/* Loading Indicator */}
            {isTyping && !isStreaming && (
              <div style={{ color: 'var(--text-muted)', fontSize: '12px', fontStyle: 'italic', display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 12px' }}>
                <span style={{ display: 'inline-block', width: '7px', height: '7px', borderRadius: '50%', background: 'var(--coursework)' }} />
                Thinking...
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </>
      )}
    </div>
  )
}

