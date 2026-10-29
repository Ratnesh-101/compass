import React, { useMemo, useState, useEffect } from 'react'
import EvidenceCard from './EvidenceCard'
import ThinkingBlock from './ThinkingBlock'
import MarkdownRenderer from './MarkdownRenderer'
import ChatTaskCard from './ChatTaskCard'
import IntakePreviewCard from './IntakePreviewCard'
import { fetchPersonaPhrases } from '../../api/chatApi'
import Logo from '../Logo'
import { generateFollowUpSuggestions, formatSuggestionText } from '../../utils/suggestionGenerator'
import { isMessageEligibleForVerification } from '../../utils/verificationEligibility'

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
  } catch {
    /* ignore storage access error */
  }

  let candidates = pool.map((_, i) => i).filter(i => isNaN(lastIdx) || i !== lastIdx)
  if (candidates.length === 0) candidates = pool.map((_, i) => i)

  const chosenIdx = candidates[Math.floor(Math.random() * candidates.length)]
  try {
    localStorage.setItem(storageKey, String(chosenIdx))
  } catch {
    /* ignore storage access error */
  }

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


export default function ChatMessageList({
  messages,
  isStreaming,
  streamingText,
  streamingThought = '',
  streamingStatus = null,
  isTyping,
  messagesEndRef,
  profileFacts = {},
  pastConversations = [],
  onSendMessage,
  onSelectMode,
  onRetry,
  tasks = [],
  userInput = '',
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
            borderRadius: 'var(--radius-card, 8px)',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: '18px',
            color: 'var(--accent, #f5a623)',
          }}>
            <Logo size={28} alt="Compass logo" />
          </div>

          <h2 style={{
            fontSize: '26px',
            fontWeight: '600',
            color: 'var(--text-primary)',
            marginBottom: '10px',
            maxWidth: '560px',
            lineHeight: '1.4',
          }}>
            {greeting}
          </h2>

          <p style={{
            fontSize: '13px',
            color: 'var(--text-secondary)',
            margin: '0',
            maxWidth: '480px',
            lineHeight: '1.5',
          }}>
            {userName
              ? `I have your personal context and preferences loaded. Think out loud, plan your week, or pick a direction.`
              : `Your warm thinking partner for coursework, deadlines, and hackathons. No wrong place to start.`
            }
          </p>
        </div>
      ) : (
        <>
          <div style={{ fontSize: '15px', color: 'var(--text-secondary)', marginBottom: '18px', fontWeight: '500' }}>
            {getTimeGreeting()}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {messages.map((msg, idx) => {
              const hasModes = msg.role === 'assistant' && typeof msg.text === 'string' && msg.text.includes('[[modes]]')
              const isLatest = idx === messages.length - 1
              const showModes = hasModes && isLatest && !isStreaming
              const pendingAction = msg.data?.pending_action || msg.pending_action
              const pendingKind = pendingAction?.action || pendingAction?.kind

              return (
                <div key={idx} style={{ display: 'flex', flexDirection: 'column', alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start', gap: '8px' }}>
                  <div style={{ display: 'flex', gap: '10px', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start', width: '100%' }}>
                    {msg.role === 'assistant' && (
                      <div className="chat-msg-avatar" style={{
                        width: '32px', height: '32px', borderRadius: 'var(--radius-btn, 6px)', background: 'var(--bg-sidebar)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent, #f5a623)', flexShrink: 0
                      }}>
                        <Logo size={20} alt="Compass logo" />
                      </div>
                    )}
                    <div className="chat-msg-bubble" style={{
                      maxWidth: 'min(85%, 820px)',
                      padding: '13px 17px',
                      borderRadius: 'var(--radius-card, 8px)',
                      background: msg.role === 'user' ? 'var(--bg-sidebar)' : 'var(--bg-card)',
                      color: msg.role === 'user' ? 'var(--sidebar-text-active, #ffffff)' : 'var(--text-primary)',
                      fontSize: '13.5px',
                      lineHeight: '1.5',
                      border: msg.role === 'user' ? 'none' : '1px solid var(--border)',
                    }}>
                      {msg.role === 'assistant' && msg.thought && (
                        <ThinkingBlock thought={msg.thought} />
                      )}
                      {msg.role === 'user' ? (
                        msg.text
                      ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                          {msg.text ? <MarkdownRenderer content={msg.text} /> : null}
                          {msg.savedNotice && (
                            <div role="status" style={{ marginTop: msg.text ? '10px' : '0', fontSize: '13px', color: 'var(--text-secondary)' }}>
                              {msg.savedNotice}
                            </div>
                          )}
                          {msg.error && (
                            <div style={{
                              display: 'flex',
                              flexDirection: 'column',
                              gap: '8px',
                              marginTop: msg.text ? '10px' : '0',
                              padding: msg.text ? '8px 12px' : '0',
                              background: msg.text ? 'rgba(239, 68, 68, 0.08)' : 'transparent',
                              borderRadius: msg.text ? '6px' : '0',
                              border: msg.text ? '1px solid rgba(239, 68, 68, 0.2)' : 'none',
                            }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--danger, #ef4444)', fontSize: '13px' }}>
                                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                                  <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
                                  <line x1="12" y1="9" x2="12" y2="13" />
                                  <line x1="12" y1="17" x2="12.01" y2="17" />
                                </svg>
                                <span>{msg.text ? `Stream interrupted: ${msg.error} (partial output preserved)` : msg.error}</span>
                              </div>
                              {msg.canRetry && msg.retryPrompt && (
                                <button
                                  type="button"
                                  onClick={() => {
                                    if (onRetry) {
                                      onRetry(idx, msg.retryPrompt, msg.retrySpecialistId, msg.retryRequestId)
                                    } else if (onSendMessage) {
                                      onSendMessage(msg.retryPrompt)
                                    }
                                  }}
                                  className="btn-secondary"
                                  style={{
                                    alignSelf: 'flex-start',
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '6px',
                                    padding: '0 12px',
                                    minHeight: '32px',
                                    borderRadius: 'var(--radius-btn, 6px)',
                                    fontSize: '12px',
                                    cursor: 'pointer',
                                    fontWeight: '500',
                                  }}
                                >
                                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                                    <polyline points="1 4 1 10 7 10" />
                                    <polyline points="23 20 23 14 17 14" />
                                    <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15" />
                                  </svg>
                                  <span>Retry</span>
                                </button>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                      {msg.role === 'assistant' && msg.tasks && Array.isArray(msg.tasks) && msg.tasks.length > 0 && (
                        <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                          <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                            Relevant Tasks ({msg.tasks.length})
                          </span>
                          {msg.tasks.slice(0, 4).map((t, tIdx) => (
                            <ChatTaskCard key={tIdx} task={t} onAction={(action, task) => onSendMessage && onSendMessage(`View task "${task.title}"`)} />
                          ))}
                        </div>
                      )}
                      {msg.role === 'assistant' && msg.evidence && (
                        <EvidenceCard evidence={msg.evidence} />
                      )}
                      {msg.role === 'assistant' && msg.isTruncated && (
                        <div style={{
                          marginTop: '10px',
                          padding: '8px 12px',
                          borderRadius: '6px',
                          background: 'rgba(230, 81, 0, 0.1)',
                          border: '1px solid rgba(230, 81, 0, 0.3)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: '8px',
                          flexWrap: 'wrap',
                        }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: '#e65100' }}>
                            <span>⚠️</span>
                            <span>Response reached output token limit and may be incomplete.</span>
                          </div>
                          <button
                            type="button"
                            onClick={() => onSendMessage && onSendMessage("Continue response")}
                            className="btn-secondary"
                            style={{
                              padding: '2px 10px',
                              minHeight: '28px',
                              fontSize: '11.5px',
                              borderRadius: '4px',
                              cursor: 'pointer',
                              fontWeight: '600',
                              color: '#e65100',
                              border: '1px solid rgba(230, 81, 0, 0.4)',
                            }}
                          >
                            Continue response ➔
                          </button>
                        </div>
                      )}
                      {pendingKind === 'add_tasks' && isLatest && !isStreaming && !isTyping && (
                        <IntakePreviewCard
                          pendingAction={pendingAction}
                          onConfirm={() => onSendMessage && onSendMessage("Confirm")}
                          onCancel={() => onSendMessage && onSendMessage("Cancel")}
                        />
                      )}
                      {(msg.data?.pending_action || msg.pending_action) && isLatest && !isStreaming && !isTyping && pendingKind !== 'add_tasks' && (
                        <div
                          className="chat-pending-action-card"
                          role="region"
                          aria-label="Pending action confirmation"
                          style={{
                            marginTop: '10px',
                            padding: '10px 14px',
                            background: 'rgba(230, 81, 0, 0.08)',
                            border: '1px solid rgba(230, 81, 0, 0.35)',
                            borderRadius: '6px',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '8px',
                          }}
                        >
                          <div style={{ fontSize: '12px', fontWeight: '500', color: 'var(--text-primary)' }}>
                            {pendingKind === 'delete_task_disambiguation' ? 'Choose a task to delete:' : 'Confirm destructive action:'}
                          </div>
                          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                            {pendingKind !== 'delete_task_disambiguation' && (
                              <button
                                type="button"
                                id="btn-pending-confirm"
                                className="btn-primary"
                                style={{
                                  padding: '4px 14px',
                                  minHeight: '30px',
                                  fontSize: '12px',
                                  background: '#d32f2f',
                                  color: '#fff',
                                  border: 'none',
                                  borderRadius: '4px',
                                  cursor: 'pointer',
                                  fontWeight: '600',
                                }}
                                onClick={() => onSendMessage && onSendMessage("Confirm")}
                              >
                                Confirm
                              </button>
                            )}
                            <button
                              type="button"
                              id="btn-pending-cancel"
                              className="btn-secondary"
                              style={{
                                padding: '4px 14px',
                                minHeight: '30px',
                                fontSize: '12px',
                                borderRadius: '4px',
                                cursor: 'pointer',
                              }}
                              onClick={() => onSendMessage && onSendMessage("Cancel")}
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}
                      {(msg.data?.can_undo || msg.can_undo) && (
                        <div style={{ marginTop: '8px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                          <button
                            type="button"
                            id="btn-chat-undo"
                            title="Restore soft-deleted tasks within 10 minutes"
                            onClick={() => onSendMessage && onSendMessage("Undo")}
                            className="btn-secondary"
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '5px',
                              padding: '3px 10px',
                              minHeight: '26px',
                              fontSize: '11px',
                              borderRadius: '4px',
                              color: 'var(--text-secondary)',
                              cursor: 'pointer',
                              background: 'var(--bg-card-soft, rgba(255,255,255,0.03))',
                              border: '1px solid var(--border)',
                            }}
                          >
                            <span>↩️</span>
                            <span>Undo (10 min)</span>
                          </button>
                        </div>
                      )}
                      {isMessageEligibleForVerification(msg) && (
                        <div style={{ marginTop: '8px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                          <button
                            type="button"
                            title="Verify claims and deadlines using live web evidence from Tavily"
                            onClick={() => onSendMessage && onSendMessage({
                              text: "Verify this with Tavily",
                              targetMessageId: msg.id,
                              targetMessageContent: msg.text,
                            })}
                            className="btn-secondary"
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '5px',
                              padding: '3px 10px',
                              minHeight: '26px',
                              fontSize: '11px',
                              borderRadius: '4px',
                              color: 'var(--text-secondary)',
                              cursor: 'pointer',
                              background: 'var(--bg-card-soft, rgba(255,255,255,0.03))',
                              border: '1px solid var(--border)',
                            }}
                          >
                            <span style={{ color: 'var(--coursework, #1a73e8)' }}>🔍</span>
                            <span>Verify with Tavily</span>
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Contextual Follow-up Chips for Latest Assistant Response */}
                  {(() => {
                    if (!isLatest || msg.role !== 'assistant' || isStreaming || isTyping || msg.error) {
                      return null
                    }
                    if (userInput && userInput.trim().length > 0) {
                      return null
                    }
                    const suggestions = generateFollowUpSuggestions({
                      latestMessage: msg,
                      messages,
                      tasks,
                    })
                    if (!suggestions || suggestions.length === 0) return null

                    return (
                      <div
                        className="assistant-follow-up-group"
                        role="group"
                        aria-label="Suggested follow-up questions"
                      >
                        {suggestions.map((chip, cIdx) => (
                          <button
                            key={cIdx}
                            type="button"
                            disabled={isStreaming || isTyping}
                            onClick={() => onSendMessage && onSendMessage(chip)}
                            className="assistant-follow-up-chip"
                            title={chip}
                            aria-label={chip}
                          >
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
                              style={{ flexShrink: 0, opacity: 0.75 }}
                            >
                              <path d="M5 12h14" />
                              <path d="M12 5l7 7-7 7" />
                            </svg>
                            <span className="chip-label">{formatSuggestionText(chip, 60)}</span>
                          </button>
                        ))}
                      </div>
                    )
                  })()}

                  {showModes && (
                    <div style={{
                      display: 'flex',
                      gap: '8px',
                      marginLeft: '42px',
                      flexWrap: 'wrap',
                    }}>
                      <button
                        type="button"
                        className="btn-secondary"
                        style={{
                          padding: '0 14px',
                          minHeight: '44px',
                          borderRadius: 'var(--radius-btn, 6px)',
                          fontSize: '13px',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px',
                          cursor: 'pointer',
                        }}
                        onClick={() => onSelectMode ? onSelectMode('advice', 'Advice') : onSendMessage && onSendMessage('Advice')}
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--accent, #f5a623)' }}>
                          <path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5" />
                          <path d="M9 18h6" />
                          <path d="M10 22h4" />
                        </svg>
                        <span>Advice</span>
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        style={{
                          padding: '0 14px',
                          minHeight: '44px',
                          borderRadius: 'var(--radius-btn, 6px)',
                          fontSize: '13px',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px',
                          cursor: 'pointer',
                        }}
                        onClick={() => onSelectMode ? onSelectMode('sounding_board', 'Sounding board') : onSendMessage && onSendMessage('Sounding board')}
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--domain-coursework, #2f64c8)' }}>
                          <path d="M3 18v-6a9 9 0 0 1 18 0v6" />
                          <path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z" />
                        </svg>
                        <span>Sounding board</span>
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        style={{
                          padding: '0 14px',
                          minHeight: '44px',
                          borderRadius: 'var(--radius-btn, 6px)',
                          fontSize: '13px',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px',
                          cursor: 'pointer',
                        }}
                        onClick={() => onSelectMode ? onSelectMode('plan', 'Plan') : onSendMessage && onSendMessage('Plan')}
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--domain-code, #1c8a62)' }}>
                          <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
                          <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
                        </svg>
                        <span>Plan</span>
                      </button>
                    </div>
                  )}
                </div>
              )
            })}

            {/* Active Progressive Token Streaming Bubble */}
            {isStreaming && (
              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-start' }}>
                <div className="chat-msg-avatar" style={{
                  width: '32px', height: '32px', borderRadius: 'var(--radius-btn, 6px)', background: 'var(--bg-sidebar)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent, #f5a623)', flexShrink: 0
                }}>
                  <Logo size={20} alt="Compass logo" />
                </div>
                <div className="chat-msg-bubble" style={{
                  maxWidth: 'min(85%, 820px)',
                  padding: '13px 17px',
                  borderRadius: 'var(--radius-card, 8px)',
                  background: 'var(--bg-card)',
                  color: 'var(--text-primary)',
                  fontSize: '13.5px',
                  lineHeight: '1.5',
                  border: '1px solid var(--border)',
                }}>
                  {(streamingThought || !streamingText) && (
                    <ThinkingBlock thought={streamingThought} status={streamingStatus} isLive={true} />
                  )}
                  {streamingText ? (
                    <>
                      <MarkdownRenderer content={streamingText} />
                      <span className="streaming-caret" style={{ background: 'var(--coursework)' }} />
                    </>
                  ) : null}
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

