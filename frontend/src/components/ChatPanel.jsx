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
import ShareModal from './ShareModal'
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
  const [_memoryOverview, setMemoryOverview] = useState(null)
  const [profileFacts, setProfileFacts] = useState({})
  const [parkedThoughts, setParkedThoughts] = useState([])
  const [showParkedShelf, setShowParkedShelf] = useState(false)
  const [_loadingHistory, setLoadingHistory] = useState(false)
  const [guestMigrationCount, setGuestMigrationCount] = useState(0)
  const [toast, setToast] = useState(null)
  const [sharingConv, setSharingConv] = useState(null)
  const [tone, setTone] = useState(() => {
    try {
      return localStorage.getItem('compass_chat_tone') || 'balanced'
    } catch {
      return 'balanced'
    }
  })
  const [memoryActive, setMemoryActive] = useState(() => {
    try {
      const stored = localStorage.getItem('compass_memory_active')
      return stored !== 'false'
    } catch {
      return true
    }
  })

  const handleToggleMemoryActive = () => {
    setMemoryActive((prev) => {
      const next = !prev
      try {
        localStorage.setItem('compass_memory_active', String(next))
      } catch {
        /* ignore storage access error */
      }
      return next
    })
  }
  const [convMode, setConvMode] = useState(null)
  const [streamingThought, setStreamingThought] = useState('')
  const [streamingStatus, setStreamingStatus] = useState(null)

  const handleToneChange = (newTone) => {
    setTone(newTone)
    try {
      localStorage.setItem('compass_chat_tone', newTone)
    } catch {
      /* ignore storage access error */
    }
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
  const activeAbortControllerRef = useRef(null)
  const activeRequestIdRef = useRef(0)

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
      if (activeAbortControllerRef.current) {
        activeAbortControllerRef.current.abort()
      }
      if (streamTimerRef.current) {
        clearInterval(streamTimerRef.current)
      }
    }
  }, [])

  const clearStreamTimer = () => {
    if (streamTimerRef.current) {
      clearInterval(streamTimerRef.current)
      streamTimerRef.current = null
    }
  }

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
        { role: 'assistant', text: "This conversation is empty right now, there are no messages to recap." }
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

  const handleSend = async (textToSend, overrideMode = null, explicitSpecialistId = null, isRetry = false, extraMeta = {}) => {
    let text = ''
    let targetMessageId = extraMeta?.targetMessageId || null
    let targetMessageContent = extraMeta?.targetMessageContent || null

    if (textToSend && typeof textToSend === 'object') {
      text = (textToSend.text || '').trim()
      targetMessageId = textToSend.targetMessageId || targetMessageId
      targetMessageContent = textToSend.targetMessageContent || targetMessageContent
    } else {
      text = (textToSend || input).trim()
    }
    if (!text || isStreaming || isTyping || isSendingRef.current) return

    if (text.toLowerCase() === 'recap where i left off') {
      return handleRecap()
    }

    const activeMode = overrideMode !== null ? overrideMode : convMode
    const specialistIdToUse = explicitSpecialistId || (activeSpecialist ? activeSpecialist.id : null)

    // Abort previous in-flight stream if active
    if (activeAbortControllerRef.current) {
      activeAbortControllerRef.current.abort()
    }
    const abortController = new AbortController()
    activeAbortControllerRef.current = abortController
    const requestId = ++activeRequestIdRef.current

    isSendingRef.current = true
    setInput('')
    setActiveSpecialist(null)

    const specPrefix = activeSpecialist
      ? `[${activeSpecialist.icon === 'compass' ? activeSpecialist.name : `${activeSpecialist.icon} ${activeSpecialist.name}`}] `
      : ''
    const userMsgText = `${specPrefix}${text}`

    if (!isRetry) {
      setMessages(prev => [...prev, { role: 'user', text: userMsgText }])
    }
    setIsStreaming(true)
    setStreamingText('')
    setStreamingThought('')
    setStreamingStatus({ stage: 'thinking', label: 'Understanding your request…' })

    let receivedTokens = ''
    let receivedThought = ''

    try {
      await streamQueryFromAssistant(text, conversationId, {
        tone,
        mode: activeMode,
        specialistId: specialistIdToUse,
        targetMessageId,
        targetMessageContent,
        signal: abortController.signal,
        onStatus: (statusEvt) => {
          if (requestId !== activeRequestIdRef.current) return
          setStreamingStatus(statusEvt)
          messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
        },
        onThought: (thoughtChunk) => {
          if (requestId !== activeRequestIdRef.current) return
          receivedThought = receivedThought ? (receivedThought + '\n' + thoughtChunk) : thoughtChunk
          setStreamingThought(receivedThought)
          messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
        },
        onToken: (token, full) => {
          if (requestId !== activeRequestIdRef.current) return
          receivedTokens = full
          setStreamingText(full)
          messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
        },
        onComplete: async (doneData) => {
          if (requestId !== activeRequestIdRef.current) return
          const finalText = (doneData?.response || receivedTokens || '').trim()
          setIsStreaming(false)
          setStreamingText('')
          setStreamingThought('')
          setStreamingStatus(null)
          isSendingRef.current = false
          if (finalText) {
            setMessages(prev => [...prev, {
              role: 'assistant',
              text: finalText,
              thought: receivedThought || null,
              tasks: Array.isArray(doneData?.tasks) ? doneData.tasks : null,
              evidence: doneData?.evidence || null,
              isTruncated: Boolean(doneData?.is_truncated),
              verifiable: doneData?.verifiable,
              pending_action: doneData?.pending_action || doneData?.data?.pending_action,
              can_undo: Boolean(doneData?.can_undo || doneData?.data?.can_undo),
              data: doneData?.data || {
                pending_action: doneData?.pending_action,
                can_undo: doneData?.can_undo,
              },
            }])
          }
          // A completed stream with an empty reply is a normal outcome: never re-send the prompt
          if (doneData?.conversation_id && setConversationId) {
            setConversationId(doneData.conversation_id)
          }
          if (onChatComplete) {
            onChatComplete()
          }
          messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
        },
        onError: async (err) => {
          if (requestId !== activeRequestIdRef.current) return
          if (err?.name === 'AbortError' || abortController.signal.aborted) {
            setIsStreaming(false)
            setStreamingText('')
            setStreamingThought('')
            isSendingRef.current = false
            return
          }
          console.warn('[SSE Stream Error]', err)
          setIsStreaming(false)
          setStreamingText('')
          setStreamingThought('')
          setStreamingStatus(null)
          isSendingRef.current = false
          const errMsg = err?.message || "I encountered an issue connecting to Compass. Please verify the service is running and try again."
          const partialText = (err?.partialResponse || receivedTokens || '').trim()
          setMessages(prev => [
            ...prev,
            {
              role: 'assistant',
              text: partialText,
              error: errMsg,
              canRetry: true,
              retryPrompt: text,
              thought: receivedThought || null,
            },
          ])
        }
      })
    } catch (err) {
      if (requestId !== activeRequestIdRef.current) return
      if (err?.name === 'AbortError' || abortController.signal.aborted) {
        setIsStreaming(false)
        setStreamingText('')
        setStreamingThought('')
        isSendingRef.current = false
        return
      }
      console.warn('[SSE Stream Failed]', err)
      setIsStreaming(false)
      setStreamingText('')
      setStreamingThought('')
      isSendingRef.current = false
      const partialText = (err?.partialResponse || receivedTokens || '').trim()
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          text: partialText,
          error: err?.message || "I encountered an issue connecting to Compass. Please verify the service is running and try again.",
          canRetry: true,
          retryPrompt: text,
          thought: receivedThought || null,
        },
      ])
    }
  }

  const handleRetry = (msgIndex, retryPrompt) => {
    // Remove the failed assistant message at msgIndex, preserving original user prompt
    setMessages(prev => prev.filter((_, idx) => idx !== msgIndex))
    handleSend(retryPrompt, null, null, true)
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
    if (activeAbortControllerRef.current) {
      activeAbortControllerRef.current.abort()
      activeAbortControllerRef.current = null
    }
    clearStreamTimer()
    setIsStreaming(false)
    setStreamingText('')
    setStreamingThought('')
    setStreamingStatus(null)
    isSendingRef.current = false
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
    if (activeAbortControllerRef.current) {
      activeAbortControllerRef.current.abort()
      activeAbortControllerRef.current = null
    }
    clearStreamTimer()
    setIsStreaming(false)
    setStreamingText('')
    setStreamingThought('')
    setStreamingStatus(null)
    isSendingRef.current = false
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

  const handleShareChat = (conv) => {
    setSharingConv(conv)
  }

  const isInputDisabled = isStreaming || isTyping
  const isOnline = backendStatus.toLowerCase().includes('neon') ||
    backendStatus.toLowerCase().includes('live') ||
    backendStatus.toLowerCase().includes('connected') ||
    backendStatus.toLowerCase().includes('ready')
  const overdueCount = tasks.filter(t => (t.countdown || '').toLowerCase().includes('overdue')).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, height: '100%', minWidth: 0, background: 'var(--bg-app)', position: 'relative' }}>
      <ChatHeaderToolbar
        showHistoryDrawer={showHistoryDrawer}
        setShowHistoryDrawer={setShowHistoryDrawer}
        pastConversations={pastConversations}
        isOnline={isOnline}
        memoryActive={memoryActive}
        onToggleMemoryActive={handleToggleMemoryActive}
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
        tasks={tasks}
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
          onShareChat={handleShareChat}
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
            streamingThought={streamingThought}
            streamingStatus={streamingStatus}
            isTyping={isTyping}
            messagesEndRef={messagesEndRef}
            profileFacts={profileFacts}
            pastConversations={pastConversations}
            onSendMessage={handleSend}
            onSelectMode={handleSelectMode}
            onRetry={handleRetry}
            tasks={tasks}
            userInput={input}
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

      {/* Share Link Modal */}
      <ShareModal
        isOpen={Boolean(sharingConv)}
        onClose={() => setSharingConv(null)}
        conversation={sharingConv}
        onConversationUpdated={(updatedConv) => {
          setSharingConv(updatedConv)
          setPastConversations(prev => prev.map(c => c.id === updatedConv.id ? updatedConv : c))
        }}
      />
    </div>
  )
}