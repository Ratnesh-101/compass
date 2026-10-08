import React, { useState, useEffect, useRef } from 'react'
import {
  streamQueryFromAssistant,
  fetchConversations,
  fetchConversationMessages,
  fetchMemoryOverview,
  fetchMigrationStatus,
  fetchProfileFacts,
  deleteProfileFact,
  deleteAllProfileFacts,
  fetchParkedThoughts,
  resolveParkedThought,
  fetchChatRecap,
  getCurrentUserId,
} from '../api/client'
import ChatHistoryDrawer from './chat/ChatHistoryDrawer'
import ChatChatMessageList from './chat/ChatMessageList'
import ChatInputBar from './chat/ChatInputBar'
import ChatContextBar from './chat/ChatContextBar'
import ChatHeaderToolbar from './chat/ChatHeaderToolbar'
import ParkedThoughtsShelf from './chat/ParkedThoughtsShelf'
import ProfileFactsShelf from './chat/ProfileFactsShelf'

export default function ChatPanel({
  messages, setMessages, conversationId, setConversationId, onSendMessage, isTyping, onChatComplete,
  tasks = [], backendStatus = '', initialPrompt = null, onClearInitialPrompt = null,
  onOpenMigration = null,
}) {
  const [input, setInput] = useState('')
  const [activeSpecialist, setActiveSpecialist] = useState(null)
  const [streamingText, setStreamingText] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [showContext, setShowContext] = useState(false)
  const [showHistoryDrawer, setShowHistoryDrawer] = useState(false)
  const [pastConversations, setPastConversations] = useState([])
  const [pastPlans, setPastPlans] = useState([])
  const [memoryOverview, setMemoryOverview] = useState(null)
  const [profileFacts, setProfileFacts] = useState({})
  const [parkedThoughts, setParkedThoughts] = useState([])
  const [showParkedShelf, setShowParkedShelf] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [guestMigrationCount, setGuestMigrationCount] = useState(0)
  const [toast, setToast] = useState(null)
  const [tone, setTone] = useState(() => {
    try {
      return localStorage.getItem('compass_chat_tone') || 'balanced'
    } catch {
      return 'balanced'
    }
  })
  const [convMode, setConvMode] = useState(null)

  const handleToneChange = (newTone) => {
    setTone(newTone)
    try {
      localStorage.setItem('compass_chat_tone', newTone)
    } catch {}
  }

  const handleResolveParked = async (thoughtId) => {
    try {
      const ok = await resolveParkedThought(thoughtId)
      if (ok) {
        setParkedThoughts((prev) => prev.filter((p) => p.id !== thoughtId))
        if (showToast) showToast('Parked thought resolved!')
      }
    } catch (e) {
      console.warn('Failed to resolve parked thought:', e)
    }
  }

  const messagesEndRef = useRef(null)
  const streamTimerRef = useRef(null)
  const isSendingRef = useRef(false)

  // Load past conversations and memory overview on mount & drawer open
  const loadHistoryData = async () => {
    setLoadingHistory(true)
    try {
      const [convs, mem, facts, parked] = await Promise.all([
        fetchConversations(50, true),
        fetchMemoryOverview(),
        fetchProfileFacts(),
        fetchParkedThoughts(),
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
      if (facts && typeof facts === 'object') {
        setProfileFacts(facts)
      }
      if (Array.isArray(parked)) {
        setParkedThoughts(parked)
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

  const handleRecap = async () => {
    if (isStreaming || isTyping || isSendingRef.current) return
    if (!conversationId || messages.length === 0) {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', text: "This conversation is empty right now — there are no messages to recap." }
      ])
      return
    }

    setMessages(prev => [...prev, { role: 'user', text: "Recap where I left off" }])
    setIsStreaming(true)
    setStreamingText('Generating recap of decisions, open questions, and next steps…')

    try {
      const data = await fetchChatRecap(conversationId)
      setIsStreaming(false)
      setStreamingText('')
      setMessages(prev => [
        ...prev,
        { role: 'assistant', text: data.recap || "Unable to generate recap right now." }
      ])
    } catch (err) {
      console.warn('Recap error:', err)
      setIsStreaming(false)
      setStreamingText('')
      setMessages(prev => [
        ...prev,
        { role: 'assistant', text: "Unable to generate recap right now." }
      ])
    }
  }

  const handleSelectMode = (selectedMode, label) => {
    setConvMode(selectedMode)
    handleSend(label, selectedMode)
  }

  const handleSend = async (textToSend, overrideMode = null, explicitSpecialistId = null) => {
    const text = (textToSend || input).trim()
    if (!text || isStreaming || isTyping || isSendingRef.current) return

    if (text.toLowerCase() === 'recap where i left off') {
      return handleRecap()
    }

    const activeMode = overrideMode !== null ? overrideMode : convMode
    const specialistIdToUse = explicitSpecialistId || (activeSpecialist ? activeSpecialist.id : null)

    isSendingRef.current = true
    setInput('')
    setActiveSpecialist(null)

    const userMsgText = activeSpecialist
      ? `[${activeSpecialist.icon} ${activeSpecialist.name}] ${text}`
      : text

    setMessages(prev => [...prev, { role: 'user', text: userMsgText }])
    setIsStreaming(true)
    setStreamingText('')

    let receivedTokens = ''

    try {
      await streamQueryFromAssistant(text, conversationId, {
        tone,
        mode: activeMode,
        specialistId: specialistIdToUse,
        onToken: (token, full) => {
          receivedTokens = full
          setStreamingText(full)
          messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
        },
        onComplete: async (doneData) => {
          setIsStreaming(false)
          setStreamingText('')
          isSendingRef.current = false
          const finalText = doneData?.response || receivedTokens
          if (finalText && finalText.trim()) {
            setMessages(prev => [...prev, { role: 'assistant', text: finalText }])
          } else if (onSendMessage) {
            const reply = await onSendMessage(text, tone, specialistIdToUse)
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
          try {
            if (onSendMessage) {
              const reply = await onSendMessage(text, tone, specialistIdToUse)
              if (reply) {
                streamAssistantResponse(reply)
                return
              }
            }
            setMessages(prev => [
              ...prev,
              {
                role: 'assistant',
                text: "I encountered an issue connecting to Compass. Please verify the service is running and try again.",
              },
            ])
          } catch (fallbackErr) {
            console.error('[Chat Fallback Error]', fallbackErr)
            setMessages(prev => [
              ...prev,
              {
                role: 'assistant',
                text: "I encountered an issue connecting to Compass. Please verify the service is running and try again.",
              },
            ])
          } finally {
            isSendingRef.current = false
            setIsStreaming(false)
            setStreamingText('')
          }
        }
      })
    } catch (err) {
      console.warn('[SSE Stream Failed — falling back to non-streaming chat]', err)
      setIsStreaming(false)
      setStreamingText('')
      try {
        if (onSendMessage) {
          const reply = await onSendMessage(text, tone, specialistIdToUse)
          if (reply) {
            streamAssistantResponse(reply)
            return
          }
        }
      } catch (fallbackErr) {
        console.error('[Chat Fallback Error]', fallbackErr)
        setMessages(prev => [
          ...prev,
          {
            role: 'assistant',
            text: "I encountered an issue connecting to Compass. Please verify the service is running and try again.",
          },
        ])
      } finally {
        isSendingRef.current = false
        setIsStreaming(false)
        setStreamingText('')
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
    setConvMode(null)
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
    setConvMode(null)
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

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(null), 2500) }
  const handleDeleteFact = async (k) => {
    if (await deleteProfileFact(k)) {
      setProfileFacts(prev => { const n = { ...prev }; delete n[k]; return n })
      showToast(`Forgotten: ${k}`)
    }
  }
  const handleForgetAllFacts = async () => {
    if (await deleteAllProfileFacts()) { setProfileFacts({}); showToast('All personal facts forgotten') }
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
      <ChatHeaderToolbar
        showHistoryDrawer={showHistoryDrawer}
        setShowHistoryDrawer={setShowHistoryDrawer}
        pastConversations={pastConversations}
        isOnline={isOnline}
        tone={tone}
        handleToneChange={handleToneChange}
        showParkedShelf={showParkedShelf}
        setShowParkedShelf={setShowParkedShelf}
        parkedThoughts={parkedThoughts}
        showContext={showContext}
        setShowContext={setShowContext}
        handleRecap={handleRecap}
        handleNewChat={handleNewChat}
        isInputDisabled={isInputDisabled}
      />

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
          onCheckScheduleClashes={() => handleSend('Check for any schedule conflicts between my upcoming deadlines and past discussions')}
          showToast={showToast}
          tasks={tasks}
        />

        {/* Main Chat Feed & Input */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, height: '100%', overflow: 'hidden' }}>
          {showContext && (
            <ChatContextBar
              overdueCount={overdueCount}
              taskCount={tasks.length}
              isOnline={isOnline}
              backendStatus={backendStatus}
            />
          )}

          {/* Collapsible Parked Thoughts Shelf */}
          {showParkedShelf && (
            <ParkedThoughtsShelf
              parkedThoughts={parkedThoughts}
              onResolveParked={handleResolveParked}
            />
          )}

          {/* Collapsible Profile Facts Shelf */}
          {showContext && (
            <ProfileFactsShelf
              facts={profileFacts}
              onDeleteFact={handleDeleteFact}
              onForgetAll={handleForgetAllFacts}
            />
          )}


          <ChatChatMessageList
            messages={messages}
            isStreaming={isStreaming}
            streamingText={streamingText}
            isTyping={isTyping}
            messagesEndRef={messagesEndRef}
            profileFacts={profileFacts}
            pastConversations={pastConversations}
            onSendMessage={handleSend}
            onSelectMode={handleSelectMode}
          />

          <ChatInputBar
            input={input}
            setInput={setInput}
            onSend={handleSend}
            isInputDisabled={isInputDisabled}
            isStreaming={isStreaming}
            activeSpecialist={activeSpecialist}
            setActiveSpecialist={setActiveSpecialist}
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
    </div>
  )
}