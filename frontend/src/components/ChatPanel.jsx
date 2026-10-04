import React, { useState, useEffect, useRef } from 'react'
import {
  streamQueryFromAssistant,
  fetchConversations,
  fetchConversationMessages,
  fetchMemoryOverview,
  fetchMigrationStatus,
  getCurrentUserId,
} from '../api/client'
import ShareModal from './ShareModal'
import ChatHistoryDrawer from './chat/ChatHistoryDrawer'
import ChatChatMessageList from './chat/ChatMessageList'
import ChatInputBar from './chat/ChatInputBar'

export default function ChatPanel({
  messages, setMessages, conversationId, setConversationId, onSendMessage, isTyping, onChatComplete,
  tasks = [], backendStatus = '', initialPrompt = null, onClearInitialPrompt = null,
  onOpenMigration = null,
}) {
  const [input, setInput] = useState('')
  const [streamingText, setStreamingText] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [showContext, setShowContext] = useState(false)
  const [showHistoryDrawer, setShowHistoryDrawer] = useState(false)
  const [pastConversations, setPastConversations] = useState([])
  const [pastPlans, setPastPlans] = useState([])
  const [memoryOverview, setMemoryOverview] = useState(null)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [guestMigrationCount, setGuestMigrationCount] = useState(0)
  const [toast, setToast] = useState(null)
  const [sharingConv, setSharingConv] = useState(null)

  const messagesEndRef = useRef(null)
  const streamTimerRef = useRef(null)
  const isSendingRef = useRef(false)

  // Load past conversations and memory overview on mount & drawer open
  const loadHistoryData = async () => {
    setLoadingHistory(true)
    try {
      const [convs, mem] = await Promise.all([
        fetchConversations(50, true),
        fetchMemoryOverview(),
      ])
      if (convs) {
        const sorted = [...convs].sort((a, b) => {
          if (Boolean(a.is_pinned) !== Boolean(b.is_pinned)) return a.is_pinned ? -1 : 1
          return new Date(b.last_active_at) - new Date(a.last_active_at)
        })
        setPastConversations(sorted)
      }
      if (mem) {
        setMemoryOverview(mem)
        if (mem.recent_plans) setPastPlans(mem.recent_plans)
      }
      const uid = getCurrentUserId()
      if (uid && uid.includes('@')) {
        const mig = await fetchMigrationStatus()
        if (mig && mig.has_guest_data && mig.guest_conversations_count > 0) {
          setGuestMigrationCount(mig.guest_conversations_count)
        } else {
          setGuestMigrationCount(0)
        }
      }
    } catch (e) {
      console.warn('Error loading history data:', e)
    } finally {
      setLoadingHistory(false)
    }
  }

  useEffect(() => {
    loadHistoryData()
  }, [])

  useEffect(() => {
    if (showHistoryDrawer) {
      loadHistoryData()
    }
  }, [showHistoryDrawer])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, streamingText, isTyping])

  useEffect(() => {
    return () => {
      if (streamTimerRef.current) {
        clearInterval(streamTimerRef.current)
      }
    }
  }, [])

  const streamAssistantResponse = (fullText) => {
    setIsStreaming(true)
    setStreamingText('')

    const chunks = []
    let cursor = 0
    while (cursor < fullText.length) {
      const nextSpace = fullText.indexOf(' ', cursor)
      let take = 4
      if (nextSpace !== -1 && nextSpace - cursor <= 6) {
        take = nextSpace - cursor + 1
      }
      chunks.push(fullText.slice(cursor, cursor + take))
      cursor += take
    }

    let chunkIndex = 0
    let accumulated = ''

    if (streamTimerRef.current) {
      clearInterval(streamTimerRef.current)
    }

    streamTimerRef.current = setInterval(() => {
      if (chunkIndex < chunks.length) {
        accumulated += chunks[chunkIndex]
        setStreamingText(accumulated)
        chunkIndex++
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
      } else {
        clearInterval(streamTimerRef.current)
        streamTimerRef.current = null
        setIsStreaming(false)
        setStreamingText('')
        isSendingRef.current = false
        setMessages(prev => [...prev, { role: 'assistant', text: fullText }])
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
      }
    }, 18)
  }

  const handleSend = async (textToSend) => {
    const text = (textToSend || input).trim()
    if (!text || isStreaming || isTyping || isSendingRef.current) return

    isSendingRef.current = true
    setInput('')

    setMessages(prev => [...prev, { role: 'user', text }])
    setIsStreaming(true)
    setStreamingText('')

    let receivedTokens = ''

    try {
      await streamQueryFromAssistant(text, conversationId, {
        onToken: (token, full) => {
          receivedTokens = full
          setStreamingText(full)
          messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
        },
        onComplete: async (doneData) => {
          setIsStreaming(false)
          setStreamingText('')
          isSendingRef.current = false
          if (receivedTokens && receivedTokens.trim()) {
            setMessages(prev => [...prev, { role: 'assistant', text: receivedTokens }])
          } else if (onSendMessage) {
            const reply = await onSendMessage(text)
            if (reply) {
              streamAssistantResponse(reply)
            }
          }
          if (doneData?.conversation_id && setConversationId) {
            setConversationId(doneData.conversation_id)
          }
          if (onChatComplete) {
            onChatComplete()
          }
          messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
        },
        onError: async (err) => {
          console.warn('[SSE Stream Error — falling back to non-streaming chat]', err)
          setIsStreaming(false)
          setStreamingText('')
          if (onSendMessage) {
            const reply = await onSendMessage(text)
            if (reply) {
              streamAssistantResponse(reply)
            } else {
              isSendingRef.current = false
            }
          } else {
            isSendingRef.current = false
          }
        }
      })
    } catch (err) {
      console.warn('[SSE Stream Failed — falling back to non-streaming chat]', err)
      setIsStreaming(false)
      setStreamingText('')
      if (onSendMessage) {
        const reply = await onSendMessage(text)
        if (reply) {
          streamAssistantResponse(reply)
        } else {
          isSendingRef.current = false
        }
      } else {
        isSendingRef.current = false
      }
    }
  }

  const handleSendRef = useRef(handleSend)
  useEffect(() => {
    handleSendRef.current = handleSend
  })

  useEffect(() => {
    if (initialPrompt && initialPrompt.trim()) {
      const promptToRun = initialPrompt.trim()
      if (onClearInitialPrompt) onClearInitialPrompt()
      handleSendRef.current(promptToRun)
    }
  }, [initialPrompt, onClearInitialPrompt])

  const handleNewChat = () => {
    if (isStreaming || isTyping) return
    setMessages([
      {
        role: 'assistant',
        text: "New conversation started! Long-term memory is active across sessions, so I remember your past decisions, tasks, and deadlines. How can I help you plan today?"
      }
    ])
    if (setConversationId) setConversationId(null)
    setShowHistoryDrawer(false)
  }

  const handleSelectPastChat = async (pastConvId) => {
    if (isStreaming || isTyping) return
    try {
      if (setConversationId) setConversationId(pastConvId)
      const msgs = await fetchConversationMessages(pastConvId)
      if (msgs && msgs.length > 0) {
        setMessages(msgs)
      } else {
        setMessages([
          { role: 'assistant', text: 'Resumed conversation. All memory from previous sessions is loaded. What would you like to discuss next?' }
        ])
      }
      setShowHistoryDrawer(false)
    } catch (e) {
      console.warn('Failed to load past conversation:', e)
    }
  }

  const showToast = (msg) => {
    setToast(msg)
    setTimeout(() => setToast(null), 2500)
  }

  const handleShareChat = async (conv) => {
    setSharingConv(conv)
    const shareUrl = `${window.location.origin}/?share=${conv.id}`
    try {
      await navigator.clipboard.writeText(shareUrl)
      showToast('Share link copied to clipboard! 🔗')
    } catch {
      showToast('Share link generated 🔗')
    }
  }

  const handleSelectPastPlan = (plan) => {
    setMessages(prev => [
      ...prev,
      {
        role: 'assistant',
        text: `📋 **Loaded Past Plan: "${plan.goal}"**\n- **Status:** ${plan.status.toUpperCase()}\n- **Executed on:** ${new Date(plan.created_at).toLocaleString()}\n\nI have this plan in active context. Would you like me to adjust deadlines, reschedule items, or check for conflicts?`
      }
    ])
    setShowHistoryDrawer(false)
  }

  const isInputDisabled = isStreaming || isTyping
  const isOnline = backendStatus.toLowerCase().includes('neon') || backendStatus.toLowerCase().includes('live')
  const overdueCount = tasks.filter(t => (t.countdown || '').toLowerCase().includes('overdue')).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, height: '100%', minWidth: 0, background: 'var(--bg-app)', position: 'relative' }}>
      {/* Sleek Context & Control Sub-bar */}
      <div style={{
        padding: '10px 20px', borderBottom: '1px solid var(--border)', background: 'var(--bg-card)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0, gap: '12px'
      }}>
        {/* Left: History drawer toggle & Live connection indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
          <button
            id="btn-toggle-history-drawer"
            onClick={() => setShowHistoryDrawer(v => !v)}
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
              <span style={{
                background: showHistoryDrawer ? 'rgba(255,255,255,0.25)' : 'var(--brand)',
                color: showHistoryDrawer ? '#fff' : '#2a1a00',
                fontSize: '10.5px',
                padding: '1px 6px',
                borderRadius: '10px',
                fontWeight: '800'
              }}>
                {pastConversations.length}
              </span>
            )}
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', color: 'var(--text-secondary)' }}>
            <span style={{
              width: '7px', height: '7px', borderRadius: '50%',
              background: isOnline ? '#10b981' : '#f5a623', display: 'inline-block'
            }} />
            <span style={{ whiteSpace: 'nowrap' }}>{isOnline ? 'Workspace connected' : 'Connecting…'}</span>
          </div>
        </div>

        {/* Right: Connected memory pill, Context toggle & New Chat */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: '6px', padding: '4px 10px', borderRadius: '12px',
            background: 'var(--code-bg)', border: '1px solid rgba(16, 185, 129, 0.3)',
            fontSize: '11px', color: 'var(--code-text)', fontWeight: '600'
          }} title="Compass long-term memory is active across sessions to prevent schedule clashes">
            <span>🧠</span>
            <span>Memory Active</span>
          </div>

          <button
            onClick={() => setShowContext(v => !v)}
            style={{
              padding: '5px 11px', borderRadius: '6px', border: '1px solid var(--border)',
              background: showContext ? 'var(--bg-card-soft)' : 'transparent',
              color: 'var(--text-secondary)', fontSize: '11.5px', fontWeight: '600', cursor: 'pointer'
            }}>
            {showContext ? 'Hide Context' : 'Show Context'}
          </button>

          <button
            id="btn-chat-new"
            onClick={handleNewChat}
            disabled={isInputDisabled}
            style={{
              padding: '5px 12px', borderRadius: '6px', border: '1px solid var(--border)',
              background: 'transparent', color: 'var(--text-secondary)',
              fontSize: '11.5px', fontWeight: '700', cursor: isInputDisabled ? 'not-allowed' : 'pointer',
              opacity: isInputDisabled ? 0.5 : 1
            }}>
            + New Chat
          </button>
        </div>
      </div>

      {/* Main Body: History Drawer + Chat View */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
        <ChatHistoryDrawer
          isOpen={showHistoryDrawer}
          onClose={() => setShowHistoryDrawer(false)}
          pastConversations={pastConversations}
          setPastConversations={setPastConversations}
          pastPlans={pastPlans}
          conversationId={conversationId}
          guestMigrationCount={guestMigrationCount}
          onOpenMigration={onOpenMigration}
          onSelectPastChat={handleSelectPastChat}
          onNewChat={handleNewChat}
          onSelectPastPlan={handleSelectPastPlan}
          onShareChat={handleShareChat}
          onCheckScheduleClashes={() => handleSend('Check for any schedule conflicts between my upcoming deadlines and past discussions')}
          showToast={showToast}
          tasks={tasks}
        />

        {/* Main Chat Feed & Input */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, height: '100%', overflow: 'hidden' }}>
          {showContext && (
            <div style={{
              display: 'flex', gap: '10px', padding: '12px 24px', borderBottom: '1px solid var(--border)',
              background: 'var(--bg-card)', flexShrink: 0, flexWrap: 'wrap'
            }}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 12px', borderRadius: '10px',
                background: overdueCount > 0 ? 'var(--danger-bg)' : 'var(--code-bg)', minWidth: '170px'
              }}>
                <span style={{ fontSize: '16px' }}>{overdueCount > 0 ? '⚠️' : '✅'}</span>
                <div>
                  <div style={{ fontSize: '12px', fontWeight: '700', color: overdueCount > 0 ? '#b23b3b' : 'var(--code-text)' }}>
                    {overdueCount > 0 ? `${overdueCount} overdue` : 'On schedule'}
                  </div>
                  <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>Across all domains</div>
                </div>
              </div>

              <div style={{
                display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 12px', borderRadius: '10px',
                background: 'var(--coursework-bg)', minWidth: '170px'
              }}>
                <span style={{ fontSize: '16px' }}>📋</span>
                <div>
                  <div style={{ fontSize: '12px', fontWeight: '700', color: 'var(--coursework-text)' }}>
                    {tasks.length} task{tasks.length === 1 ? '' : 's'} tracked
                  </div>
                  <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>Live in Neon</div>
                </div>
              </div>

              <div style={{
                display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 12px', borderRadius: '10px',
                background: isOnline ? 'var(--code-bg)' : 'var(--hackathon-bg)', minWidth: '170px'
              }}>
                <span style={{ fontSize: '16px' }}>{isOnline ? '🟢' : '🟡'}</span>
                <div>
                  <div style={{ fontSize: '12px', fontWeight: '700', color: isOnline ? 'var(--code-text)' : 'var(--hackathon-text)' }}>
                    {isOnline ? 'Backend live' : 'Backend offline'}
                  </div>
                  <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>{backendStatus}</div>
                </div>
              </div>
            </div>
          )}

          <ChatChatMessageList
            messages={messages}
            isStreaming={isStreaming}
            streamingText={streamingText}
            isTyping={isTyping}
            messagesEndRef={messagesEndRef}
          />

          <ChatInputBar
            input={input}
            setInput={setInput}
            onSend={handleSend}
            isInputDisabled={isInputDisabled}
            isStreaming={isStreaming}
          />
        </div>
      </div>

      {/* Global Action Toast Notification */}
      {toast && (
        <div style={{
          position: 'fixed',
          bottom: '28px',
          left: '50%',
          transform: 'translateX(-50%)',
          background: '#1f2937',
          color: '#ffffff',
          border: '1px solid rgba(255, 255, 255, 0.18)',
          padding: '9px 18px',
          borderRadius: '10px',
          fontSize: '12.5px',
          fontWeight: '600',
          boxShadow: '0 8px 24px rgba(0, 0, 0, 0.45)',
          zIndex: 2000,
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          pointerEvents: 'none',
        }}>
          {toast}
        </div>
      )}

      {/* Share Link Modal */}
      <ShareModal
        isOpen={Boolean(sharingConv)}
        onClose={() => setSharingConv(null)}
        conversation={sharingConv}
      />
    </div>
  )
}