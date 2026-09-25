import React, { useState, useEffect, useRef } from 'react'
import {
  streamQueryFromAssistant,
  fetchConversations,
  fetchConversationMessages,
  updateConversation,
  deleteConversation,
  fetchMemoryOverview,
} from '../api/client'
import ShareModal from './ShareModal'

function getTimeGreeting() {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

export default function ChatPanel({
  messages, setMessages, conversationId, setConversationId, onSendMessage, isTyping, onChatComplete,
  tasks = [], backendStatus = '', initialPrompt = null, onClearInitialPrompt = null
}) {
  const [input, setInput] = useState('')
  const [streamingText, setStreamingText] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [showContext, setShowContext] = useState(false)
  const [showHistoryDrawer, setShowHistoryDrawer] = useState(false)
  const [historyTab, setHistoryTab] = useState('chats') // 'chats' | 'plans' | 'memory'
  const [pastConversations, setPastConversations] = useState([])
  const [pastPlans, setPastPlans] = useState([])
  const [memoryOverview, setMemoryOverview] = useState(null)
  const [loadingHistory, setLoadingHistory] = useState(false)

  // Options menu, renaming, archiving, and delete modal state
  const [openMenuConvId, setOpenMenuConvId] = useState(null)
  const [editingConvId, setEditingConvId] = useState(null)
  const [editingTitle, setEditingTitle] = useState('')
  const [confirmDeleteConv, setConfirmDeleteConv] = useState(null)
  const [showArchived, setShowArchived] = useState(false)
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
        // Sort: pinned first, then last_active_at desc
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

  // Close context menu when clicking anywhere outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (!e.target.closest('.chat-item-menu-container') && !e.target.closest('.chat-item-menu-btn')) {
        setOpenMenuConvId(null)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  // Auto-scroll whenever messages, streaming tokens, or typing status changes
  useEffect(() => {
    scrollToBottom()
  }, [messages, streamingText, isTyping])

  // Cleanup timer if component unmounts mid-stream
  useEffect(() => {
    return () => {
      if (streamTimerRef.current) {
        clearInterval(streamTimerRef.current)
      }
    }
  }, [])

  /**
   * Token Streaming & Typewriter Mechanism (Fallback)
   * Chunks 3–5 characters or 1 token every 18ms for progressive delivery when SSE is unavailable.
   */
  const streamAssistantResponse = (fullText) => {
    setIsStreaming(true)
    setStreamingText('')

    // Divide text into token-like chunks (3 to 6 characters or word chunks)
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

    // 1. Add user message to conversation
    setMessages(prev => [...prev, { role: 'user', text }])
    setIsStreaming(true)
    setStreamingText('')

    let receivedTokens = ''

    try {
      // 2. Attempt real Server-Sent Events streaming from Nebius endpoint
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

  useEffect(() => {
    if (initialPrompt && initialPrompt.trim()) {
      const promptToRun = initialPrompt.trim()
      if (onClearInitialPrompt) onClearInitialPrompt()
      handleSend(promptToRun)
    }
  }, [initialPrompt])

  const handleSubmit = (e) => {
    e.preventDefault()
    handleSend()
  }

  const handleQuickPrompt = () => {
    if (isStreaming || isTyping || isSendingRef.current) return
    const prompt = 'What tasks do I have coming up?'
    handleSend(prompt)
  }

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
    setOpenMenuConvId(null)
    setSharingConv(conv)
    const shareUrl = `${window.location.origin}/?share=${conv.id}`
    try {
      await navigator.clipboard.writeText(shareUrl)
      showToast('Share link copied to clipboard! 🔗')
    } catch {
      showToast('Share link generated 🔗')
    }
  }

  const handleStartRename = (conv) => {
    setOpenMenuConvId(null)
    setEditingConvId(conv.id)
    setEditingTitle(conv.title || '')
  }

  const handleSaveRename = async (convId) => {
    const clean = editingTitle.trim()
    if (!clean) {
      setEditingConvId(null)
      return
    }
    setPastConversations(prev => prev.map(c => c.id === convId ? { ...c, title: clean } : c))
    setEditingConvId(null)
    await updateConversation(convId, { title: clean })
    showToast('Chat renamed ✏️')
  }

  const handleCancelRename = () => {
    setEditingConvId(null)
  }

  const handleTogglePin = async (conv) => {
    setOpenMenuConvId(null)
    const nextPinned = !conv.is_pinned
    setPastConversations(prev => {
      const updated = prev.map(c => c.id === conv.id ? { ...c, is_pinned: nextPinned } : c)
      return [...updated].sort((a, b) => {
        if (Boolean(a.is_pinned) !== Boolean(b.is_pinned)) return a.is_pinned ? -1 : 1
        return new Date(b.last_active_at) - new Date(a.last_active_at)
      })
    })
    await updateConversation(conv.id, { is_pinned: nextPinned })
    showToast(nextPinned ? 'Chat pinned to top 📌' : 'Chat unpinned')
  }

  const handleToggleArchive = async (conv) => {
    setOpenMenuConvId(null)
    const nextArchived = !conv.is_archived
    setPastConversations(prev => prev.map(c => c.id === conv.id ? { ...c, is_archived: nextArchived } : c))
    await updateConversation(conv.id, { is_archived: nextArchived })
    showToast(nextArchived ? 'Chat moved to Archive 🗃️' : 'Chat unarchived')
  }

  const handleOpenDeleteConfirm = (conv) => {
    setOpenMenuConvId(null)
    setConfirmDeleteConv(conv)
  }

  const handleExecuteDelete = async () => {
    if (!confirmDeleteConv) return
    const convId = confirmDeleteConv.id
    setConfirmDeleteConv(null)
    const ok = await deleteConversation(convId)
    if (ok) {
      setPastConversations(prev => prev.filter(c => c.id !== convId))
      if (conversationId === convId) {
        handleNewChat()
      }
      showToast('Chat deleted 🗑️')
    } else {
      showToast('Failed to delete chat')
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

  /**
   * Preserves formatting, line breaks, bullet points, and router latency chips
   */
  const renderFormattedMessage = (text) => {
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
                <span style={{ lineHeight: '1.5' }}>{trimmed.replace(/^[•\-]\s*/, '')}</span>
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
        {/* Claude-style History & Memory Drawer */}
        {showHistoryDrawer && (
          <aside style={{
            width: '320px',
            minWidth: '280px',
            maxWidth: '360px',
            background: 'var(--bg-card)',
            borderRight: '1px solid var(--border)',
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
            overflow: 'hidden',
            boxShadow: 'var(--shadow-md)',
            zIndex: 10,
          }}>
            {/* Drawer Header */}
            <div style={{
              padding: '14px 16px',
              borderBottom: '1px solid var(--border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              background: 'var(--bg-card-soft)'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '16px' }}>📜</span>
                <span style={{ fontSize: '13px', fontWeight: '800', color: 'var(--text-primary)' }}>
                  History & Memory
                </span>
              </div>
              <button
                onClick={() => setShowHistoryDrawer(false)}
                style={{
                  background: 'none', border: 'none', color: 'var(--text-muted)',
                  fontSize: '16px', cursor: 'pointer', padding: '2px 6px'
                }}
                title="Close drawer"
              >
                ✕
              </button>
            </div>

            {/* New Chat Primary Action */}
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
              <button
                onClick={handleNewChat}
                style={{
                  width: '100%',
                  padding: '9px 14px',
                  borderRadius: '8px',
                  background: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
                  color: '#ffffff',
                  border: 'none',
                  fontSize: '12.5px',
                  fontWeight: '700',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '6px',
                  boxShadow: '0 3px 10px rgba(37, 99, 235, 0.3)'
                }}
              >
                <span>+</span> Start New Chat
              </button>
            </div>

            {/* Drawer Sub-tab selector */}
            <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', padding: '6px 12px', gap: '6px', background: 'var(--bg-app)' }}>
              {[
                { key: 'chats', label: `Chats (${pastConversations.length})`, icon: '💬' },
                { key: 'plans', label: `Plans (${pastPlans.length})`, icon: '📋' },
                { key: 'memory', label: 'Memory Bank', icon: '🧠' },
              ].map(tab => (
                <button
                  key={tab.key}
                  onClick={() => setHistoryTab(tab.key)}
                  style={{
                    flex: 1,
                    padding: '6px 4px',
                    borderRadius: '6px',
                    border: 'none',
                    background: historyTab === tab.key ? 'var(--bg-card)' : 'transparent',
                    color: historyTab === tab.key ? 'var(--text-primary)' : 'var(--text-secondary)',
                    fontWeight: historyTab === tab.key ? '700' : '500',
                    fontSize: '11px',
                    cursor: 'pointer',
                    boxShadow: historyTab === tab.key ? 'var(--shadow-sm)' : 'none',
                    textAlign: 'center',
                    whiteSpace: 'nowrap'
                  }}
                >
                  {tab.icon} {tab.label}
                </button>
              ))}
            </div>

            {/* Drawer Body Items */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px' }}>
              {historyTab === 'chats' && (() => {
                const visibleConversations = pastConversations.filter(c => showArchived ? Boolean(c.is_archived) : !c.is_archived)
                const archivedCount = pastConversations.filter(c => c.is_archived).length

                return (
                  <div>
                    {/* Active vs Archived Sub-header */}
                    <div style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      marginBottom: '8px',
                      padding: '0 4px',
                      fontSize: '11px',
                      color: 'var(--text-muted)'
                    }}>
                      <span style={{ fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                        {showArchived ? `Archived (${archivedCount})` : 'Recent Chats'}
                      </span>
                      {archivedCount > 0 && (
                        <button
                          onClick={() => setShowArchived(v => !v)}
                          style={{
                            background: 'none',
                            border: 'none',
                            color: 'var(--brand)',
                            cursor: 'pointer',
                            fontSize: '11px',
                            fontWeight: '700',
                            padding: '2px 4px'
                          }}
                        >
                          {showArchived ? '← Active Chats' : `Archived (${archivedCount})`}
                        </button>
                      )}
                    </div>

                    {visibleConversations.length === 0 ? (
                      <div style={{ textAlign: 'center', padding: '30px 12px', color: 'var(--text-muted)', fontSize: '12px' }}>
                        <div style={{ fontSize: '24px', marginBottom: '8px' }}>{showArchived ? '🗃️' : '💬'}</div>
                        <div>{showArchived ? 'No archived chats.' : 'No previous chats yet.'}</div>
                        <div style={{ fontSize: '11px', marginTop: '4px' }}>
                          {showArchived ? 'Chats you archive will be stored here.' : 'Chats are automatically stored and remembered across sessions.'}
                        </div>
                      </div>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        {visibleConversations.map(conv => {
                          const isCurrent = conversationId === conv.id
                          const isMenuOpen = openMenuConvId === conv.id
                          const isEditing = editingConvId === conv.id

                          return (
                            <div
                              key={conv.id}
                              onClick={() => {
                                if (!isEditing) handleSelectPastChat(conv.id)
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
                                      handleSaveRename(conv.id)
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
                                          handleCancelRename()
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
                                      onClick={handleCancelRename}
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

                                    {/* Three dots options button */}
                                    <button
                                      className="chat-item-menu-btn"
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        setOpenMenuConvId(isMenuOpen ? null : conv.id)
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

                              {/* Floating Context Options Menu matching ChatGPT/Claude design */}
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
                                  {/* Share */}
                                  <button
                                    onClick={() => handleShareChat(conv)}
                                    style={{
                                      display: 'flex', alignItems: 'center', gap: '10px', width: '100%',
                                      padding: '8px 12px', borderRadius: '8px', border: 'none', background: 'transparent',
                                      color: '#ececed', fontSize: '12.5px', fontWeight: '500', cursor: 'pointer', textAlign: 'left'
                                    }}
                                    onMouseEnter={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.08)'}
                                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                                  >
                                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                      <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/>
                                      <polyline points="16 6 12 2 8 6"/>
                                      <line x1="12" y1="2" x2="12" y2="15"/>
                                    </svg>
                                    <span>Share</span>
                                  </button>

                                  {/* Rename */}
                                  <button
                                    onClick={() => handleStartRename(conv)}
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

                                  {/* Pin chat */}
                                  <button
                                    onClick={() => handleTogglePin(conv)}
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

                                  {/* Archive */}
                                  <button
                                    onClick={() => handleToggleArchive(conv)}
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

                                  {/* Delete */}
                                  <button
                                    onClick={() => handleOpenDeleteConfirm(conv)}
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
                        })}
                      </div>
                    )}
                  </div>
                )
              })()}

              {historyTab === 'plans' && (
                pastPlans.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: '30px 12px', color: 'var(--text-muted)', fontSize: '12px' }}>
                    <div style={{ fontSize: '24px', marginBottom: '8px' }}>📋</div>
                    <div>No previous plans yet.</div>
                    <div style={{ fontSize: '11px', marginTop: '4px' }}>Goals decomposed by the Planner will be recorded here.</div>
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {pastPlans.map(plan => (
                      <div
                        key={plan.id}
                        onClick={() => handleSelectPastPlan(plan)}
                        style={{
                          padding: '10px 12px',
                          borderRadius: '8px',
                          border: '1px solid var(--border)',
                          background: 'var(--bg-card)',
                          cursor: 'pointer',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '6px',
                          transition: 'all 0.15s ease',
                        }}
                        onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--brand)'}
                        onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--border)'}
                        title="Click to reference this plan in chat"
                      >
                        <div style={{ fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', lineHeight: 1.3 }}>
                          {plan.goal}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '11px' }}>
                          <span style={{
                            padding: '2px 7px',
                            borderRadius: '6px',
                            fontSize: '10px',
                            fontWeight: '700',
                            background: plan.status === 'completed' ? 'var(--code-bg)' : 'var(--hackathon-bg)',
                            color: plan.status === 'completed' ? 'var(--code-text)' : 'var(--hackathon-text)',
                            textTransform: 'uppercase'
                          }}>
                            {plan.status}
                          </span>
                          <span style={{ color: 'var(--text-muted)', fontSize: '10.5px' }}>
                            {new Date(plan.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )
              )}

              {historyTab === 'memory' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <div style={{ padding: '12px', borderRadius: '8px', background: 'var(--code-bg)', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12.5px', fontWeight: '700', color: 'var(--code-text)', marginBottom: '4px' }}>
                      <span>🟢</span> Cross-Session Recall Active
                    </div>
                    <p style={{ margin: 0, fontSize: '11.5px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                      Compass automatically recalls your past chats, deadlines, and schedule commitments in new chats so schedules never clash.
                    </p>
                  </div>

                  <div style={{ padding: '12px', borderRadius: '8px', background: 'var(--bg-card)', border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: '12px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '8px' }}>
                      Memory Metrics
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11.5px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                      <span>Active Tasks & Deadlines:</span>
                      <strong style={{ color: 'var(--text-primary)' }}>{tasks.length}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11.5px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                      <span>Recorded Conversations:</span>
                      <strong style={{ color: 'var(--text-primary)' }}>{pastConversations.length}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11.5px', color: 'var(--text-secondary)' }}>
                      <span>Executed Agent Plans:</span>
                      <strong style={{ color: 'var(--text-primary)' }}>{pastPlans.length}</strong>
                    </div>
                  </div>

                  <button
                    onClick={() => {
                      setShowHistoryDrawer(false)
                      handleSend('Check for any schedule conflicts between my upcoming deadlines and past discussions')
                    }}
                    style={{
                      padding: '9px 12px',
                      borderRadius: '8px',
                      background: 'var(--bg-card-soft)',
                      border: '1px solid var(--border)',
                      color: 'var(--text-primary)',
                      fontSize: '12px',
                      fontWeight: '600',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '6px'
                    }}
                  >
                    <span>🔍</span> Check for Schedule Clashes Now
                  </button>
                </div>
              )}
            </div>
          </aside>
        )}

          {/* Main Chat Feed & Input */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, height: '100%', overflow: 'hidden' }}>
            {/* Context chips — only real, wired data */}
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

      {/* Message Feed Container */}
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', padding: '24px 28px', minWidth: 0 }}>
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
      </div>

      {/* Footer: quick prompt + input bar */}
      <div style={{ padding: '16px 28px 22px', background: 'var(--bg-app)', flexShrink: 0 }}>
        {/* Quick prompt suggestions */}
        <div style={{ display: 'flex', gap: '8px', marginBottom: '12px', overflowX: 'auto', paddingBottom: '4px' }}>
          {[
            { icon: '📋', text: 'What tasks do I have coming up?' },
            { icon: '⚡', text: 'Prioritize my deadlines for today' },
            { icon: '📅', text: 'Check for schedule conflicts' },
            { icon: '➕', text: 'Add task: Finish project slides' },
          ].map((item, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => handleSend(item.text)}
              disabled={isInputDisabled}
              style={{
                padding: '7px 13px',
                borderRadius: '20px',
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                color: 'var(--text-secondary)',
                fontSize: '12px',
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

        <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '10px' }}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={isStreaming ? 'Streaming response...' : 'Ask me anything, or say "add a task"...'}
            disabled={isInputDisabled}
            style={{
              flex: 1,
              padding: '13px 17px',
              borderRadius: '10px',
              background: isInputDisabled ? 'var(--bg-card-soft)' : 'var(--bg-card)',
              border: '1px solid var(--border)',
              color: isInputDisabled ? 'var(--text-muted)' : 'var(--text-primary)',
              fontSize: '13.5px',
              outline: 'none',
              cursor: isInputDisabled ? 'not-allowed' : 'text'
            }}
          />
          <button
            type="submit"
            disabled={isInputDisabled || !input.trim()}
            style={{
              padding: '0 24px',
              borderRadius: '10px',
              background: 'var(--brand)',
              border: 'none',
              color: '#2a1a00',
              fontWeight: '700',
              fontSize: '13px',
              cursor: (isInputDisabled || !input.trim()) ? 'not-allowed' : 'pointer',
              opacity: (!input.trim() || isInputDisabled) ? 0.5 : 1,
              transition: 'opacity 0.15s ease'
            }}>
            Send
          </button>
        </form>
      </div>
          </div>
        </div>

        {/* Delete Confirmation Modal */}
        {confirmDeleteConv && (
          <div
            onClick={() => setConfirmDeleteConv(null)}
            style={{
              position: 'fixed',
              inset: 0,
              background: 'rgba(0, 0, 0, 0.65)',
              backdropFilter: 'blur(3px)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 1000,
              padding: '16px',
            }}
          >
            <div
              onClick={e => e.stopPropagation()}
              style={{
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                borderRadius: '14px',
                padding: '22px',
                maxWidth: '400px',
                width: '100%',
                boxShadow: 'var(--shadow-lg)',
                display: 'flex',
                flexDirection: 'column',
                gap: '14px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{
                  width: '38px', height: '38px', borderRadius: '10px',
                  background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px', flexShrink: 0
                }}>
                  🗑️
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '800', color: 'var(--text-primary)' }}>
                    Delete chat?
                  </h3>
                  <p style={{ margin: '2px 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
                    This action cannot be undone.
                  </p>
                </div>
              </div>

              <p style={{ margin: 0, fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                This will permanently delete <strong>"{confirmDeleteConv.title || 'Chat Session'}"</strong> and all associated messages from your workspace memory.
              </p>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '6px' }}>
                <button
                  onClick={() => setConfirmDeleteConv(null)}
                  style={{
                    padding: '8px 15px', borderRadius: '8px', border: '1px solid var(--border)',
                    background: 'transparent', color: 'var(--text-primary)', fontSize: '12.5px',
                    fontWeight: '600', cursor: 'pointer'
                  }}
                >
                  Cancel
                </button>
                <button
                  onClick={handleExecuteDelete}
                  style={{
                    padding: '8px 18px', borderRadius: '8px', border: 'none',
                    background: '#ef4444', color: '#ffffff', fontSize: '12.5px',
                    fontWeight: '700', cursor: 'pointer', boxShadow: '0 2px 8px rgba(239, 68, 68, 0.35)'
                  }}
                >
                  Delete
                </button>
              </div>
            </div>
          </div>
        )}

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