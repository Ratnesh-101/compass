import React, { useState, useEffect, useRef, useCallback } from 'react'
import Sidebar from './components/Sidebar'
import Timeline from './components/Timeline'
import CalendarView from './components/CalendarView'
import NorthstarPanel from './components/NorthstarPanel'
import AuthModal from './components/AuthModal'
import SharedChatView from './components/SharedChatView'
import {
  checkBackendHealth,
  fetchTasks,
  sendQueryToAssistant,
  fetchUsageSummary,
  fetchCurrentUser,
  getGoogleOAuthConnectUrl,
  disconnectCalendar,
} from './api/client'

export default function App() {
  const [tasks, setTasks] = useState([])
  const [activeTab, setActiveTab] = useState('timeline')
  const [selectedDomain, setSelectedDomain] = useState('all')
  const [backendStatus, setBackendStatus] = useState('Connecting...')
  const [conversationId, setConversationId] = useState(null)
  const [usageStats, setUsageStats] = useState(null)
  const [currentUser, setCurrentUser] = useState(() => {
    try {
      const savedEmail = localStorage.getItem('compass_user_email') || localStorage.getItem('compass_user_id')
      if (savedEmail && savedEmail.includes('@')) {
        const clean = savedEmail.trim().toLowerCase()
        return {
          authenticated: true,
          user_id: clean,
          email: clean,
          name: clean.split('@')[0].replace('.', ' ').replace(/\b\w/g, c => c.toUpperCase()),
          calendar: { connected: false, mode: 'demo', is_simulated: true },
        }
      }
    } catch {}
    return null
  })
  const [showAuthModal, setShowAuthModal] = useState(false)
  const [shareId, setShareId] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('share') || (window.location.pathname.startsWith('/share/') ? window.location.pathname.replace('/share/', '') : null)
  })
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      text: "Hey! I'm Compass, your productivity copilot. I can track tasks, recall code context, synthesize cross-domain roadmaps, and search the web. What's on your mind?"
    }
  ])
  const [isTyping, setIsTyping] = useState(false)
  const [pendingPrompt, setPendingPrompt] = useState(null)

  // Keep a ref to the latest tasks state for stable diffing without triggering interval re-creations
  const tasksRef = useRef([])
  tasksRef.current = tasks

  // Refresh usage stats from the backend (public endpoint, no auth required)
  const refreshUsage = useCallback(async () => {
    const stats = await fetchUsageSummary()
    if (stats) setUsageStats(stats)
  }, [])

  // P0.1 FIX: Domain-aware task fetcher — fires a NEW server-side request with
  // ?domain=<X> query param every time selectedDomain changes, instead of
  // client-side array filtering on stale data.
  const loadTasks = useCallback(async (domain) => {
    try {
      const incomingTasks = await fetchTasks(domain)
      if (!Array.isArray(incomingTasks)) return

      const currentTasks = tasksRef.current
      const hasLengthChanged = incomingTasks.length !== currentTasks.length
      const hasContentChanged = incomingTasks.some((task, i) => {
        const cur = currentTasks[i]
        return !cur || cur.id !== task.id || cur.title !== task.title || cur.countdown !== task.countdown
      })
      if (hasLengthChanged || hasContentChanged) {
        setTasks(incomingTasks)
      }
    } catch {
      // Silently preserve current view during transient connection blips
    }
  }, [])

  // Re-fetch tasks from server whenever the domain filter changes
  useEffect(() => {
    loadTasks(selectedDomain)
  }, [selectedDomain, loadTasks])

  // Check URL query parameters on mount to prompt account selection or show OAuth errors
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('oauth_error') || params.get('select_account')) {
      setShowAuthModal(true)
    }
  }, [])

  const handleUserChanged = useCallback(async (newEmail) => {
    if (newEmail) {
      const u = await fetchCurrentUser()
      setCurrentUser(u)
    } else {
      setCurrentUser({ authenticated: false, email: '' })
    }
    loadTasks(selectedDomain)
    refreshUsage()
  }, [loadTasks, selectedDomain, refreshUsage])

  useEffect(() => {
    let isMounted = true

    // Health Polling (Every 10 seconds)
    const pollHealth = async () => {
      try {
        const status = await checkBackendHealth()
        if (isMounted) setBackendStatus(status)
      } catch {
        if (isMounted) setBackendStatus('Demo Mode • Mock Memory')
      }
    }

    // Task Polling (Every 3000ms with Clean State Merge) — uses current domain filter
    const pollTasks = () => {
      if (isMounted) loadTasks(selectedDomain)
    }

    // Immediate initial sync
    pollHealth()
    refreshUsage()
    fetchCurrentUser().then(u => {
      if (isMounted && u && (u.authenticated || (u.email && u.email.includes('@')))) {
        setCurrentUser(u)
      }
    })

    // 1. Task polling interval: 3000ms
    const taskInterval = setInterval(pollTasks, 3000)

    // 2. Health check polling interval: 10,000ms (10 seconds)
    const healthInterval = setInterval(pollHealth, 10000)

    // Component Cleanup: clear all interval timers on unmount
    return () => {
      isMounted = false
      clearInterval(taskInterval)
      clearInterval(healthInterval)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const domainCounts = tasks.reduce((acc, t) => {
    const dom = (t.domain || 'general').toLowerCase().trim()
    acc[dom] = (acc[dom] || 0) + 1
    return acc
  }, {
    hackathon: 0,
    coursework: 0,
    code: 0,
    general: 0,
    other: 0,
  })

  const handleSendMessage = async (userText) => {
    setIsTyping(true)

    const result = await sendQueryToAssistant(userText, conversationId)

    setIsTyping(false)

    // Update conversation_id for multi-turn threading
    if (result.conversation_id && result.conversation_id !== conversationId) {
      setConversationId(result.conversation_id)
    }

    // P0.2 FIX: Refresh usage counter after every chat turn so the header
    // reflects real token consumption instead of showing a static string.
    refreshUsage()

    return result.response
  }

  // P0.2: Build the live header badge text with micro-dollar precision
  const usageBadge = usageStats
    ? `⚡ ${usageStats.total_requests ?? 0} calls · $${(usageStats.total_estimated_cost_usd ?? 0).toFixed(5)}`
    : 'Nebius • Nemotron-3'

  if (shareId) {
    return (
      <SharedChatView
        shareId={shareId}
        onGoToApp={() => {
          const url = new URL(window.location.href)
          url.searchParams.delete('share')
          window.history.pushState({}, '', url.pathname + (url.search ? url.search : ''))
          setShareId(null)
          setActiveTab('northstar')
        }}
      />
    )
  }

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100vw', background: 'var(--bg-app)', overflow: 'hidden' }}>
      <Sidebar
        activeDomain={selectedDomain}
        onSelectDomain={setSelectedDomain}
        domainCounts={domainCounts}
        backendStatus={backendStatus}
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        usageBadge={usageBadge}
        currentUser={currentUser}
        onOpenAuth={() => setShowAuthModal(true)}
      />

      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', background: 'var(--bg-app)', minWidth: 0, overflow: 'hidden' }}>
        {activeTab === 'timeline' ? (
          <Timeline
            tasks={tasks}
            activeDomain={selectedDomain}
            onSelectDomain={setSelectedDomain}
            onTasksUpdated={() => {
              loadTasks(selectedDomain)
              refreshUsage()
            }}
            onOpenNorthstar={(prompt) => {
              setActiveTab('northstar')
              setPendingPrompt(prompt)
            }}
          />
        ) : activeTab === 'calendar' ? (
          <CalendarView
            tasks={tasks}
            activeDomain={selectedDomain}
            onTasksUpdated={() => {
              loadTasks(selectedDomain)
              refreshUsage()
            }}
            onOpenAuthModal={() => setShowAuthModal(true)}
          />
        ) : (
          <NorthstarPanel
            initialSubTab={
              activeTab === 'agent' || activeTab === 'planner'
                ? 'planner'
                : activeTab === 'specialist'
                ? 'specialist'
                : 'assistant'
            }
            messages={messages}
            setMessages={setMessages}
            conversationId={conversationId}
            setConversationId={setConversationId}
            onSendMessage={handleSendMessage}
            isTyping={isTyping}
            onChatComplete={refreshUsage}
            tasks={tasks}
            backendStatus={backendStatus}
            onTaskMutated={() => {
              loadTasks(selectedDomain)
              refreshUsage()
            }}
            onSelectTab={setActiveTab}
            pendingPrompt={pendingPrompt}
            onClearPendingPrompt={() => setPendingPrompt(null)}
          />
        )}
      </main>

      <AuthModal
        isOpen={showAuthModal}
        onClose={() => setShowAuthModal(false)}
        currentUser={currentUser}
        onUserChanged={handleUserChanged}
      />
    </div>
  )
}