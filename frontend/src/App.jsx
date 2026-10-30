import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import Sidebar from './components/Sidebar'
import Dashboard from './components/Dashboard'
import MobileNavBar from './components/MobileNavBar'
import Timeline from './components/Timeline'
import CalendarView from './components/CalendarView'
import CompassPanel from './components/CompassPanel'
import AuthModal from './components/AuthModal'
import SharedChatView from './components/SharedChatView'
import DemoDataBanner from './components/DemoDataBanner'
import LegalView from './components/LegalView'
import NotFoundView from './components/NotFoundView'
import TabErrorBoundary from './components/TabErrorBoundary'
import StatusNotices from './components/StatusNotices'
import { fetchDemoStatusResult, clearDemoPersona, setChatIncludeDemo } from './api/chatApi'

import MigrationModal from './components/MigrationModal'
import NebiusTelemetryModal from './components/NebiusTelemetryModal'
import { getCustomDomains, removeCustomDomain, getDomainMeta } from './components/timeline/domainMeta'
import { parseLocation, buildUrl } from './router'
import {
  checkBackendHealth,
  fetchTasks,
  sendQueryToAssistant,
  fetchUsageSummary,
  fetchCurrentUserResult,
  initGuestSession,
  fetchMigrationStatus,
} from './api/client'
import { isDemoTask } from './utils/demoConstants'
import { haveTasksChanged } from './utils/taskDiff'
import {
  identityActionFor,
  isBackendOnline,
  parseOAuthReturn,
  stripOAuthParams,
} from './utils/firstRun'

const TASK_POLL_INTERVAL_MS = 8000
const NOTICE_AUTO_DISMISS_MS = 10000
const INITIAL_MESSAGES = [
  {
    role: 'assistant',
    text: "Hey! I'm Compass. I can track tasks, recall code context, synthesize cross-domain roadmaps, and search the web. What's on your mind?"
  }
]

export default function App() {
  const [tasks, setTasks] = useState([])
  const [allTasks, setAllTasks] = useState([])
  const [customDomains, setCustomDomains] = useState(() => getCustomDomains())
  const initialNav = useMemo(() => parseLocation(), [])
  const [activeTab, setActiveTab] = useState(() => initialNav.tab)
  const [selectedDomain, setSelectedDomain] = useState(() => initialNav.domain)
  const [shareToken, setShareToken] = useState(() => initialNav.shareToken || null)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [backendStatus, setBackendStatus] = useState('Waking up the server…')
  const [conversationId, setConversationId] = useState(null)
  const [usageStats, setUsageStats] = useState(null)
  const [showTelemetryModal, setShowTelemetryModal] = useState(false)
  const [showMigrationModal, setShowMigrationModal] = useState(false)
  const [guestConversationsCount, setGuestConversationsCount] = useState(0)
  const [currentUser, setCurrentUser] = useState(null)
  const [showAuthModal, setShowAuthModal] = useState(false)
  const [messages, setMessages] = useState(INITIAL_MESSAGES)
  const [isTyping, setIsTyping] = useState(false)
  const [pendingPrompt, setPendingPrompt] = useState(null)
  const [notice, setNotice] = useState(null) // { type: 'success' | 'error' | 'info', text }
  const [serviceBusy, setServiceBusy] = useState(false)
  const [careerAttempt, setCareerAttempt] = useState(0)
  // careerAttempt forces a fresh import() after a failed chunk load (React.lazy caches rejections)
  const CareerCopilot = useMemo(
    () => React.lazy(() => import('./components/CareerCopilot')),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [careerAttempt]
  )

  const [theme, setTheme] = useState(() => {
    try {
      const qTheme = import.meta.env.DEV && typeof window !== 'undefined'
        ? new URLSearchParams(window.location.search).get('theme')
        : null
      if (qTheme === 'dark' || qTheme === 'light') return qTheme
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
      } catch {
        /* ignore localStorage access error */
      }
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
      setShareToken(loc.shareToken || null)
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  // Keep a ref to the latest tasks state for stable diffing without triggering interval re-creations
  const tasksRef = useRef([])
  tasksRef.current = tasks

  // Latest selected domain, so long-lived polling intervals never use a stale closure value
  const selectedDomainRef = useRef(selectedDomain)
  selectedDomainRef.current = selectedDomain

  // Monotonic request counter so out-of-order task responses can be discarded
  const loadSeqRef = useRef(0)

  // In-flight guard to prevent overlapping task poll requests
  const pollInFlightRef = useRef(false)

  // Refresh usage stats from the backend (public endpoint, no auth required)
  const refreshUsage = useCallback(async () => {
    const stats = await fetchUsageSummary()
    if (stats) setUsageStats(stats)
  }, [])

  // Demo persona is visible while the account still holds Judge Persona data (checked on mount via /api/demo/status); Reset demo clears it
  const [isDemoActive, setIsDemoActive] = useState(false)
  const isDemoActiveRef = useRef(false)
  isDemoActiveRef.current = isDemoActive
  const [resettingDemo, setResettingDemo] = useState(false)

  // P0.1 FIX: Domain-aware task fetcher: fires a NEW server-side request with
  // ?domain=<X> query param every time selectedDomain changes, instead of
  // client-side array filtering on stale data.
  const loadTasks = useCallback(async (domain, overrideDemoActive) => {
    const requestSeq = ++loadSeqRef.current
    try {
      const demoActive = overrideDemoActive !== undefined ? overrideDemoActive : isDemoActiveRef.current
      const incomingTasks = await fetchTasks(domain, { include_demo: demoActive })
      // null signals a failed fetch: keep the current view. Stale responses are ignored.
      if (!Array.isArray(incomingTasks) || requestSeq !== loadSeqRef.current) return

      // Client-side filter to guarantee zero dummy data on reload even if backend delete is in flight
      const activeTasks = demoActive
        ? incomingTasks
        : incomingTasks.filter((t) => !isDemoTask(t))

      const currentTasks = tasksRef.current
      const hasChanged = haveTasksChanged(currentTasks, activeTasks)
      if (hasChanged) {
        setTasks(activeTasks)
      }
      if (!domain || domain === 'all') {
        setAllTasks(activeTasks)
      } else {
        fetchTasks('all', { include_demo: demoActive }).then((total) => {
          if (Array.isArray(total) && requestSeq === loadSeqRef.current) {
            const filteredTotal = demoActive ? total : total.filter((t) => !isDemoTask(t))
            setAllTasks(filteredTotal)
          }
        }).catch(() => {})
      }
    } catch {
      // Silently preserve current view during transient connection blips
    }
  }, [])

  const handleResetDemo = useCallback(async () => {
    setResettingDemo(true)
    try {
      await clearDemoPersona()
      isDemoActiveRef.current = false
      setIsDemoActive(false)
      loadTasks(selectedDomainRef.current, false)
    } finally {
      setResettingDemo(false)
    }
  }, [loadTasks])

  // Listen for explicit "Load Judge Persona" clicks
  useEffect(() => {
    const handleDemoLoaded = () => {
      isDemoActiveRef.current = true
      setIsDemoActive(true)
      loadTasks(selectedDomain, true)
    }
    window.addEventListener('compass:demo-persona-loaded', handleDemoLoaded)
    return () => window.removeEventListener('compass:demo-persona-loaded', handleDemoLoaded)
  }, [selectedDomain, loadTasks])

  // Mounted flag + "this check completed" flags so a check that failed while the backend
  // was asleep is re-run when the health poll flips to online.
  const mountedRef = useRef(true)
  const userCheckedRef = useRef(false)
  const demoCheckedRef = useRef(false)
  const migrationPendingRef = useRef(false)
  const demoSeqRef = useRef(0)
  const backendStatusRef = useRef('Waking up the server…')

  // Check whether the account holds Judge Persona demo data; a transient failure is retried later
  const checkDemoStatus = useCallback(async () => {
    const seq = ++demoSeqRef.current
    const result = await fetchDemoStatusResult()
    if (!mountedRef.current || seq !== demoSeqRef.current) return
    demoCheckedRef.current = result.ok
    if (result.ok && result.data && result.data.active === true) {
      isDemoActiveRef.current = true
      setIsDemoActive(true)
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    checkDemoStatus()
    return () => {
      mountedRef.current = false
    }
  }, [checkDemoStatus])

  // Surface the "service is busy" state from the guest-session mint backoff
  useEffect(() => {
    let timer = null
    const onBusy = (e) => {
      const retryAt = (e && e.detail && e.detail.retryAt) || Date.now() + 30000
      setServiceBusy(true)
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => { initGuestSession() }, Math.max(0, retryAt - Date.now()) + 500)
    }
    const onRecovered = () => {
      if (timer) clearTimeout(timer)
      timer = null
      setServiceBusy(false)
    }
    window.addEventListener('compass:service-busy', onBusy)
    window.addEventListener('compass:service-recovered', onRecovered)
    return () => {
      if (timer) clearTimeout(timer)
      window.removeEventListener('compass:service-busy', onBusy)
      window.removeEventListener('compass:service-recovered', onRecovered)
    }
  }, [])

  useEffect(() => {
    if (!notice) return undefined
    const t = setTimeout(() => setNotice(null), NOTICE_AUTO_DISMISS_MS)
    return () => clearTimeout(t)
  }, [notice])


  // Chat sees the demo workspace only while the dashboard shows it
  useEffect(() => {
    setChatIncludeDemo(isDemoActive)
  }, [isDemoActive])

  // Re-fetch tasks from server whenever the domain filter or demo active state changes
  useEffect(() => {
    loadTasks(selectedDomain)
  }, [selectedDomain, isDemoActive, loadTasks])

  const checkMigration = useCallback(async () => {
    try {
      if (typeof window !== 'undefined' && window.sessionStorage?.getItem('compass_migration_dismissed') === '1') {
        migrationPendingRef.current = false
        return
      }
      const status = await fetchMigrationStatus()
      // transient: the check did not complete (backend asleep); retried when it comes online
      migrationPendingRef.current = Boolean(status.transient)
      if (status.has_guest_data && status.guest_conversations_count > 0 && !status.skipped) {
        setGuestConversationsCount(status.guest_conversations_count)
        setShowMigrationModal(true)
      }
    } catch (e) {
      migrationPendingRef.current = true
      console.warn('Migration status check skipped:', e)
    }
  }, [])

  const clearStoredIdentity = useCallback(() => {
    try {
      localStorage.removeItem('compass_user_email')
      localStorage.removeItem('compass_user_id')
    } catch {
      /* ignore localStorage access error */
    }
  }, [])

  // Ask the server who we are. Only an explicit "not signed in" answer clears stored identity;
  // a network error / 5xx / timeout keeps it and the check is retried when the backend is online.
  const runUserCheck = useCallback(async () => {
    const { status, user } = await fetchCurrentUserResult()
    if (!mountedRef.current) return
    userCheckedRef.current = status !== 'transient'
    const action = identityActionFor(status)
    if (action === 'set') {
      setCurrentUser(user)
      checkMigration()
    } else if (action === 'clear') {
      clearStoredIdentity()
    }
  }, [checkMigration, clearStoredIdentity])

  const handleUserChanged = useCallback(async (newEmail) => {
    // Per-identity in-memory state must never leak across sign-in / sign-out
    setMessages(INITIAL_MESSAGES)
    setConversationId(null)
    setPendingPrompt(null)
    setTasks([])
    setAllTasks([])
    isDemoActiveRef.current = false
    setIsDemoActive(false)
    let outcome = { status: 'signed_out', user: null }
    if (newEmail) {
      const { status, user: u } = await fetchCurrentUserResult()
      userCheckedRef.current = status !== 'transient'
      outcome = { status, user: u }
      if (status === 'authenticated') {
        setCurrentUser(u)
        checkMigration()
      } else if (status === 'unauthenticated') {
        // The server did not confirm a session: never fabricate a signed-in user.
        clearStoredIdentity()
        setCurrentUser(null)
      }
      // transient: keep the stored identity; the health transition re-runs the check
    } else {
      setCurrentUser({ authenticated: false, email: '' })
      try {
        if (typeof window !== 'undefined' && window.sessionStorage) {
          window.sessionStorage.removeItem('compass_migration_dismissed')
        }
      } catch {
        /* ignore storage access error */
      }
    }
    checkDemoStatus()
    loadTasks(selectedDomain)
    refreshUsage()
    return outcome
  }, [loadTasks, selectedDomain, refreshUsage, checkMigration, checkDemoStatus, clearStoredIdentity])

  // Latest handleUserChanged for the one-shot OAuth-return effect below
  const handleUserChangedRef = useRef(handleUserChanged)
  handleUserChangedRef.current = handleUserChanged

  // Handle the OAuth redirect outcome once: show it, confirm with the server, strip the params
  useEffect(() => {
    const ret = parseOAuthReturn(window.location.search)
    if (ret.kind === 'none') return
    try {
      const cleaned = window.location.pathname + stripOAuthParams(window.location.search) + window.location.hash
      window.history.replaceState(window.history.state, '', cleaned)
    } catch {
      /* ignore history access error */
    }
    if (ret.kind === 'select_account') {
      setShowAuthModal(true)
      return
    }
    if (ret.kind === 'error') {
      setNotice({ type: 'error', text: ret.message })
      setShowAuthModal(true)
      return
    }
    handleUserChangedRef.current('oauth').then(({ status, user }) => {
      if (!mountedRef.current) return
      if (status === 'authenticated') {
        setNotice({ type: 'success', text: `Signed in as ${user?.email || user?.user_id || 'your Google account'}` })
      } else if (status === 'transient') {
        setNotice({ type: 'info', text: 'Google sign-in finished, but the server is slow to confirm it. Checking again shortly.' })
      } else {
        setNotice({ type: 'error', text: 'Google sign-in finished, but we could not confirm your session. Please try again.' })
      }
    })
  }, [])

  // Apply a health status; when the backend comes (back) online re-run every one-shot check
  // that could not complete while it was asleep.
  const applyBackendStatus = useCallback((status) => {
    const prev = backendStatusRef.current
    backendStatusRef.current = status
    setBackendStatus(status)
    if (!isBackendOnline(prev) && isBackendOnline(status)) {
      loadTasks(selectedDomainRef.current)
      refreshUsage()
      if (!userCheckedRef.current) runUserCheck()
      if (!demoCheckedRef.current) checkDemoStatus()
      if (migrationPendingRef.current) checkMigration()
    }
  }, [loadTasks, refreshUsage, runUserCheck, checkDemoStatus, checkMigration])

  const handleRetryConnection = useCallback(async () => {
    applyBackendStatus('Pinging backend…')
    try {
      const status = await checkBackendHealth(true)
      applyBackendStatus(status)
    } catch {
      applyBackendStatus('Waking up the server…')
    }
  }, [applyBackendStatus])

  useEffect(() => {
    let isMounted = true

    // Initialize anonymous guest session immediately so unauthenticated users can chat & persist context
    initGuestSession()

    // Health Polling (Every 10 seconds)
    const pollHealth = async () => {
      try {
        const status = await checkBackendHealth()
        if (isMounted) applyBackendStatus(status)
      } catch {
        if (isMounted) applyBackendStatus('Waking up the server…')
      }
    }

    // Task Polling (Every 8000ms with Clean State Merge): uses current domain filter
    const pollTasks = () => {
      if (!isMounted) return
      if (typeof document !== 'undefined' && document.hidden) return
      if (pollInFlightRef.current) return
      pollInFlightRef.current = true
      Promise.resolve(loadTasks(selectedDomainRef.current)).finally(() => {
        pollInFlightRef.current = false
      })
    }

    // Immediate initial sync
    pollHealth()
    refreshUsage()
    runUserCheck()

    // Re-fetch tasks immediately when tab returns to foreground
    const handleVisibilityChange = () => {
      if (isMounted && typeof document !== 'undefined' && !document.hidden) {
        loadTasks(selectedDomainRef.current)
      }
    }
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibilityChange)
    }

    // 1. Task polling interval: 8000ms
    const taskInterval = setInterval(pollTasks, TASK_POLL_INTERVAL_MS)

    // 2. Health check polling interval: 10,000ms (10 seconds)
    const healthInterval = setInterval(pollHealth, 10000)

    // Component Cleanup: clear all interval timers on unmount
    return () => {
      isMounted = false
      clearInterval(taskInterval)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
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
    if (tabKey === 'dashboard') {
      navigateTo('dashboard', 'all')
    } else if (tabKey === 'timeline') {
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

  const handleSendMessage = async (userText, tone = null) => {
    setIsTyping(true)

    const result = await sendQueryToAssistant(userText, conversationId, tone)

    setIsTyping(false)

    // Update conversation_id for multi-turn threading
    if (result.conversation_id && result.conversation_id !== conversationId) {
      setConversationId(result.conversation_id)
    }

    // P0.2 FIX: Refresh usage counter and task list after every chat turn
    refreshUsage()
    loadTasks(selectedDomain)

    return result.response
  }

  // P0.2: Build the live header badge text with micro-dollar precision and formatted numbers
  const usageBadge = usageStats
    ? `⚡ ${(usageStats.total_requests ?? 0).toLocaleString()} calls · $${(usageStats.total_estimated_cost_usd ?? 0).toFixed(5)}`
    : 'Nebius • Nemotron-3'

  if (activeTab === 'share' || shareToken) {
    return (
      <SharedChatView
        shareId={shareToken}
        onGoToApp={() => {
          const url = new URL(window.location.href)
          url.searchParams.delete('share')
          const nextUrl = (url.pathname === '/' || url.pathname.startsWith('/share')) ? '/' : `${url.pathname}${url.search}`
          window.history.pushState({ tab: 'dashboard', domain: 'all' }, '', nextUrl)
          setShareToken(null)
          setActiveTab('dashboard')
          setSelectedDomain('all')
        }}
      />
    )
  }

  return (
    <div className="app-shell" style={{ display: 'flex', width: '100%', background: 'var(--bg-app)', overflow: 'hidden', position: 'relative' }}>
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
        mobileOpen={mobileMenuOpen}
        onCloseMobile={() => setMobileMenuOpen(false)}
        onRetryConnection={handleRetryConnection}
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
              borderRadius: '6px',
              width: '44px',
              height: '44px',
              minWidth: '44px',
              minHeight: '44px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--text-primary)',
              cursor: 'pointer',
            }}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <line x1="4" x2="20" y1="12" y2="12" />
              <line x1="4" x2="20" y1="6" y2="6" />
              <line x1="4" x2="20" y1="18" y2="18" />
            </svg>
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
            <span style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {activeTab === 'dashboard'
                ? 'Dashboard'
                : activeTab === 'compass'
                ? 'Compass Assistant'
                : activeTab === 'calendar'
                ? 'Schedule'
                : (activeTab === 'career' || activeTab === 'radar')
                ? 'Career Copilot'
                : activeTab === 'terms'
                ? 'Terms of Service'
                : activeTab === 'privacy'
                ? 'Privacy Policy'
                : activeTab === '404'
                ? 'Page Not Found'
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
                  borderRadius: '6px',
                  width: '44px',
                  height: '44px',
                  minWidth: '44px',
                  minHeight: '44px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: 'var(--text-primary)',
                  cursor: 'pointer',
                }}
              >
                {theme === 'dark' ? (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="12" cy="12" r="4" />
                    <path d="M12 2v2" />
                    <path d="M12 20v2" />
                    <path d="m4.93 4.93 1.41 1.41" />
                    <path d="m17.66 17.66 1.41 1.41" />
                    <path d="M2 12h2" />
                    <path d="M20 12h2" />
                    <path d="m6.34 17.66-1.41 1.41" />
                    <path d="m19.07 4.93-1.41 1.41" />
                  </svg>
                ) : (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
                  </svg>
                )}
              </button>
            )}
          </div>
        </header>

        <TabErrorBoundary resetKey={activeTab}>
        {activeTab === 'terms' ? (
          <LegalView
            type="terms"
            onBack={() => navigateTo('dashboard')}
            onSelectTab={handleSelectTab}
            isDarkMode={theme === 'dark'}
            onToggleDarkMode={toggleTheme}
          />
        ) : activeTab === 'privacy' ? (
          <LegalView
            type="privacy"
            onBack={() => navigateTo('dashboard')}
            onSelectTab={handleSelectTab}
            isDarkMode={theme === 'dark'}
            onToggleDarkMode={toggleTheme}
          />
        ) : activeTab === '404' ? (
          <NotFoundView
            onBack={() => navigateTo('dashboard')}
            onSelectTab={handleSelectTab}
            isDarkMode={theme === 'dark'}
            onToggleDarkMode={toggleTheme}
          />
        ) : activeTab === 'dashboard' ? (
          <>
            {isDemoActive && <DemoDataBanner onReset={handleResetDemo} resetting={resettingDemo} />}
            <Dashboard
            tasks={allTasks.length > 0 ? allTasks : tasks}
            backendStatus={backendStatus}
            usageStats={usageStats}
            currentUser={currentUser}
            onSelectTab={handleSelectTab}
            onSelectDomain={handleSelectDomain}
            isDarkMode={theme === 'dark'}
            onToggleDarkMode={toggleTheme}
            onTasksUpdated={() => {
              loadTasks(selectedDomain)
              refreshUsage()
            }}
            onOpenCompass={(prompt) => {
              navigateTo('compass', 'all')
              setPendingPrompt(prompt)
            }}
            onOpenAuth={() => setShowAuthModal(true)}
            customDomains={customDomains}
          />
          </>
        ) : activeTab === 'timeline' ? (
          <Timeline
            tasks={tasks}
            allTasks={allTasks}
            activeDomain={selectedDomain}
            onSelectDomain={handleSelectDomain}
            customDomains={customDomains}
            theme={theme}
            onToggleTheme={toggleTheme}
            isDarkMode={theme === 'dark'}
            onToggleDarkMode={toggleTheme}
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
        ) : (activeTab === 'career' || activeTab === 'radar') ? (
          <TabErrorBoundary resetKey={activeTab} onRetry={() => setCareerAttempt((n) => n + 1)}>
            <React.Suspense fallback={<div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>Loading Career Copilot…</div>}>
              <CareerCopilot
                isDarkMode={theme === 'dark'}
                onToggleDarkMode={toggleTheme}
              />
            </React.Suspense>
          </TabErrorBoundary>
        ) : activeTab === 'calendar' ? (
          <CalendarView
            tasks={tasks}
            activeDomain={selectedDomain}
            onTasksUpdated={() => {
              loadTasks(selectedDomain)
              refreshUsage()
            }}
            onOpenAuthModal={() => setShowAuthModal(true)}
            isSignedIn={Boolean(currentUser?.authenticated)}
            isDarkMode={theme === 'dark'}
            onToggleDarkMode={toggleTheme}
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
            onChatComplete={() => {
              refreshUsage()
              loadTasks(selectedDomain)
            }}
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
            isDarkMode={theme === 'dark'}
            onToggleDarkMode={toggleTheme}
          />
        )}
        </TabErrorBoundary>
      </main>

      {/* Mobile Bottom Navigation Bar (< 768px) */}
      <MobileNavBar
        activeTab={activeTab}
        onSelectTab={handleSelectTab}
        onOpenMenu={() => setMobileMenuOpen(true)}
        activeDomain={selectedDomain}
      />

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
          try {
            if (typeof window !== 'undefined' && window.sessionStorage) {
              window.sessionStorage.removeItem('compass_migration_dismissed')
            }
          } catch {
            /* ignore storage access error */
          }
          loadTasks(selectedDomain)
          refreshUsage()
        }}
      />

      <StatusNotices notice={notice} onDismissNotice={() => setNotice(null)} serviceBusy={serviceBusy} />

      <NebiusTelemetryModal
        isOpen={showTelemetryModal}
        onClose={() => setShowTelemetryModal(false)}
        usageStats={usageStats}
        onRefresh={refreshUsage}
      />
    </div>
  )
}
