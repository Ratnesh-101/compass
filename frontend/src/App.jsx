import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import Sidebar from './components/Sidebar'
import Timeline from './components/Timeline'
import CalendarView from './components/CalendarView'
import CompassPanel from './components/CompassPanel'
import AuthModal from './components/AuthModal'
import MigrationModal from './components/MigrationModal'
import NebiusTelemetryModal from './components/NebiusTelemetryModal'
import { getCustomDomains, removeCustomDomain, getDomainMeta } from './components/timeline/domainMeta'
import { parseLocation, buildUrl } from './router'
import {
  checkBackendHealth,
  fetchTasks,
  sendQueryToAssistant,
  fetchUsageSummary,
  fetchCurrentUser,
  seedJudgeDemoPersona,
  initGuestSession,
  fetchMigrationStatus,
} from './api/client'

export default function App() {
  const [tasks, setTasks] = useState([])
  const [allTasks, setAllTasks] = useState([])
  const [customDomains, setCustomDomains] = useState(() => getCustomDomains())
  const initialNav = useMemo(() => parseLocation(), [])
  const [activeTab, setActiveTab] = useState(() => initialNav.tab)
  const [selectedDomain, setSelectedDomain] = useState(() => initialNav.domain)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [backendStatus, setBackendStatus] = useState('Connecting...')
  const [conversationId, setConversationId] = useState(null)
  const [usageStats, setUsageStats] = useState(null)
  const [showTelemetryModal, setShowTelemetryModal] = useState(false)
  const [showMigrationModal, setShowMigrationModal] = useState(false)
  const [guestConversationsCount, setGuestConversationsCount] = useState(0)
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
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      text: "Hey! I'm Compass. I can track tasks, recall code context, synthesize cross-domain roadmaps, and search the web. What's on your mind?"
    }
  ])
  const [isTyping, setIsTyping] = useState(false)
  const [pendingPrompt, setPendingPrompt] = useState(null)

  const [theme, setTheme] = useState(() => {
    try {
      const saved = localStorage.getItem('compass.theme')
      if (saved === 'dark' || saved === 'light') return saved
      if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        return 'dark'
      }
    } catch {
      /* ignore storage access error */
    }
    return 'light'
  })

  // Synchronize theme to document root and persist preference
  useEffect(() => {
    try {
      localStorage.setItem('compass.theme', theme)
    } catch {
      /* ignore storage access error */
    }
    document.documentElement.setAttribute('data-theme', theme)
    document.documentElement.classList.toggle('dark', theme === 'dark')
  }, [theme])

  // Listen for system color-scheme changes only if user hasn't set an explicit preference
  useEffect(() => {
    const handler = (e) => {
      try {
        const saved = localStorage.getItem('compass.theme')
        if (!saved) {
          setTheme(e.matches ? 'dark' : 'light')
        }
      } catch {}
    }
    const mediaQuery = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null
    if (mediaQuery?.addEventListener) {
      mediaQuery.addEventListener('change', handler)
      return () => mediaQuery.removeEventListener('change', handler)
    }
  }, [])

  const toggleTheme = useCallback(() => {
    setTheme(prev => (prev === 'dark' ? 'light' : 'dark'))
  }, [])

  const navigateTo = useCallback((tab, domain = 'all', replace = false) => {
    setActiveTab(tab)
    setSelectedDomain(domain)
    const targetUrl = buildUrl(tab, domain)
    const currentUrl = window.location.pathname + window.location.search
    if (currentUrl !== targetUrl) {
      if (replace) {
        window.history.replaceState({ tab, domain }, '', targetUrl)
      } else {
        window.history.pushState({ tab, domain }, '', targetUrl)
      }
    }
  }, [])

  // Synchronize browser Back/Forward navigation
  useEffect(() => {
    const handlePopState = () => {
      const loc = parseLocation()
      setActiveTab(loc.tab)
      setSelectedDomain(loc.domain)
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

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
      const wasFallback = currentTasks.some(t => t.is_fallback)
      const isIncomingFallback = incomingTasks.some(t => t.is_fallback)
      const hasLengthChanged = incomingTasks.length !== currentTasks.length
      const hasContentChanged = incomingTasks.some((task, i) => {
        const cur = currentTasks[i]
        return !cur || cur.id !== task.id || cur.title !== task.title || cur.countdown !== task.countdown || Boolean(cur.is_fallback) !== Boolean(task.is_fallback)
      })
      if (wasFallback !== isIncomingFallback || hasLengthChanged || hasContentChanged) {
        setTasks(incomingTasks)
      }
      if (!domain || domain === 'all') {
        setAllTasks(incomingTasks)
      } else {
        fetchTasks('all').then(total => {
          if (Array.isArray(total)) setAllTasks(total)
        }).catch(() => {})
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

  // Auto-seed demo data on first visit so judges never see an empty workspace
  useEffect(() => {
    const alreadySeeded = localStorage.getItem('compass_demo_seeded')
    if (alreadySeeded) return

    let cancelled = false
    const doSeed = async () => {
      try {
        await seedJudgeDemoPersona()
        if (!cancelled) {
          localStorage.setItem('compass_demo_seeded', '1')
          // Refresh tasks so the timeline populates immediately
          loadTasks(selectedDomain)
        }
      } catch (err) {
        console.warn('[Compass] Auto-seed skipped:', err.message)
      }
    }

    // Small delay to let the health check and initial task fetch settle first
    const timer = setTimeout(doSeed, 1500)
    return () => { cancelled = true; clearTimeout(timer) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const checkMigration = useCallback(async () => {
    try {
      const status = await fetchMigrationStatus()
      if (status.has_guest_data && status.guest_conversations_count > 0) {
        setGuestConversationsCount(status.guest_conversations_count)
        setShowMigrationModal(true)
      }
    } catch (e) {
      console.warn('Migration status check skipped:', e)
    }
  }, [])

  const handleUserChanged = useCallback(async (newEmail) => {
    if (newEmail) {
      const u = await fetchCurrentUser()
      setCurrentUser(u)
      checkMigration()
    } else {
      setCurrentUser({ authenticated: false, email: '' })
    }
    loadTasks(selectedDomain)
    refreshUsage()
  }, [loadTasks, selectedDomain, refreshUsage, checkMigration])

  useEffect(() => {
    let isMounted = true

    // Initialize anonymous guest session immediately so unauthenticated users can chat & persist context
    initGuestSession()

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
        checkMigration()
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

  const domainCounts = useMemo(() => {
    const counts = {
      hackathon: 0,
      coursework: 0,
      code: 0,
      general: 0,
      other: 0,
    }
    customDomains.forEach(d => {
      counts[d.key] = 0
    })
    const source = allTasks.length > 0 ? allTasks : tasks
    source.forEach(t => {
      const dom = (t.domain || 'general').toLowerCase().trim()
      counts[dom] = (counts[dom] || 0) + 1
    })
    return counts
  }, [allTasks, tasks, customDomains])

  const handleSelectTab = useCallback((tabKey) => {
    if (tabKey === 'timeline') {
      navigateTo('timeline', 'all')
    } else if (tabKey === 'compass' || tabKey === 'assistant' || tabKey === 'planner') {
      navigateTo('compass', 'all')
    } else if (tabKey === 'calendar' || tabKey === 'schedule') {
      navigateTo('calendar', 'all')
    } else {
      navigateTo(tabKey, 'all')
    }
    setMobileMenuOpen(false)
  }, [navigateTo])

  const handleSelectDomain = useCallback((domainKey) => {
    navigateTo('timeline', domainKey || 'all')
    setMobileMenuOpen(false)
  }, [navigateTo])

  const handleDomainCreated = useCallback((newDomain) => {
    setCustomDomains(prev => {
      const filtered = prev.filter(d => d.key !== newDomain.key)
      return [...filtered, newDomain]
    })
    navigateTo('timeline', newDomain.key)
    setMobileMenuOpen(false)
  }, [navigateTo])

  const handleDomainDeleted = useCallback((domainKey) => {
    removeCustomDomain(domainKey)
    setCustomDomains(prev => prev.filter(d => d.key !== domainKey))
    if (selectedDomain === domainKey) {
      navigateTo('timeline', 'all')
    }
  }, [selectedDomain, navigateTo])

  const currentDomainMeta = useMemo(() => {
    if (!selectedDomain || selectedDomain === 'all') {
      return { label: 'All Domains', icon: '▦' }
    }
    return getDomainMeta(selectedDomain)
  }, [selectedDomain])

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

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100%', background: 'var(--bg-app)', overflow: 'hidden', position: 'relative' }}>
      {/* Mobile Drawer Backdrop */}
      {mobileMenuOpen && (
        <div
          id="mobile-drawer-backdrop"
          className="mobile-drawer-backdrop"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      <Sidebar
        activeDomain={selectedDomain}
        onSelectDomain={handleSelectDomain}
        domainCounts={domainCounts}
        backendStatus={backendStatus}
        activeTab={activeTab}
        onSelectTab={handleSelectTab}
        usageBadge={usageBadge}
        currentUser={currentUser}
        onOpenAuth={() => setShowAuthModal(true)}
        onOpenTelemetry={() => setShowTelemetryModal(true)}
        customDomains={customDomains}
        onDomainCreated={handleDomainCreated}
        onDomainDeleted={handleDomainDeleted}
        theme={theme}
        onToggleTheme={toggleTheme}
        mobileOpen={mobileMenuOpen}
        onCloseMobile={() => setMobileMenuOpen(false)}
      />

      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', background: 'var(--bg-app)', minWidth: 0, overflow: 'hidden' }}>
        {/* Mobile Header Bar */}
        <header className="mobile-header">
          <button
            id="mobile-menu-button"
            type="button"
            onClick={() => setMobileMenuOpen(true)}
            aria-label="Open Navigation Menu"
            title="Open navigation menu"
            style={{
              background: 'var(--bg-card-soft)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              width: '40px',
              height: '40px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--text-primary)',
              cursor: 'pointer',
              fontSize: '18px',
            }}
          >
            ☰
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
            <span style={{ fontSize: '18px' }}>
              {activeTab === 'compass' ? '🧭' : activeTab === 'calendar' ? '🗓️' : currentDomainMeta.icon}
            </span>
            <span style={{ fontSize: '14px', fontWeight: '800', color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {activeTab === 'compass'
                ? 'Compass Assistant'
                : activeTab === 'calendar'
                ? 'Schedule'
                : selectedDomain === 'all'
                ? 'Timeline Feed'
                : `${currentDomainMeta.label} Domain`}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {toggleTheme && (
              <button
                id="mobile-theme-toggle"
                type="button"
                onClick={toggleTheme}
                aria-label="Toggle Theme"
                style={{
                  background: 'var(--bg-card-soft)',
                  border: '1px solid var(--border)',
                  borderRadius: '8px',
                  width: '40px',
                  height: '40px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: 'var(--text-primary)',
                  cursor: 'pointer',
                  fontSize: '16px',
                }}
              >
                {theme === 'dark' ? '🌙' : '☀️'}
              </button>
            )}
          </div>
        </header>

        {activeTab === 'timeline' ? (
          <Timeline
            tasks={tasks}
            allTasks={allTasks}
            activeDomain={selectedDomain}
            onSelectDomain={handleSelectDomain}
            customDomains={customDomains}
            theme={theme}
            onToggleTheme={toggleTheme}
            onTasksUpdated={() => {
              loadTasks(selectedDomain)
              refreshUsage()
            }}
            onOpenCompass={(prompt) => {
              navigateTo('compass', 'all')
              setPendingPrompt(prompt)
            }}
            onOpenTelemetry={() => setShowTelemetryModal(true)}
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
          <CompassPanel
            initialSubTab={
              activeTab === 'agent' || activeTab === 'planner'
                ? 'planner'
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
            onSelectTab={handleSelectTab}
            pendingPrompt={pendingPrompt}
            onClearPendingPrompt={() => setPendingPrompt(null)}
            onOpenMigration={() => setShowMigrationModal(true)}
          />
        )}
      </main>

      <AuthModal
        isOpen={showAuthModal}
        onClose={() => setShowAuthModal(false)}
        currentUser={currentUser}
        onUserChanged={handleUserChanged}
      />

      <MigrationModal
        isOpen={showMigrationModal}
        onClose={() => setShowMigrationModal(false)}
        guestConversationsCount={guestConversationsCount}
        onMigrationComplete={() => {
          setShowMigrationModal(false)
          loadTasks(selectedDomain)
          refreshUsage()
        }}
      />

      <NebiusTelemetryModal
        isOpen={showTelemetryModal}
        onClose={() => setShowTelemetryModal(false)}
        usageStats={usageStats}
        onRefresh={refreshUsage}
      />
    </div>
  )
}