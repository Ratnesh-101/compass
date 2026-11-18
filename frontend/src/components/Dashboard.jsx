import React, { useState, useMemo, useCallback, useEffect } from 'react'
import { X, BookOpen } from 'lucide-react'
import DarkModeToggle from './DarkModeToggle'
import { getDomainMeta } from './timeline/domainMeta'
import AddDeadlineModal from './timeline/AddDeadlineModal'
import AboutJudgesModal from './AboutJudgesModal'
import TourCard from './TourCard'
import { updateTask } from '../api/client'
import { DEMO_VIDEO_URL } from '../utils/tourSample'
import Logo from './Logo'
import TimelineFilterBar from './timeline/TimelineFilterBar'
import {
  classifyDeadline,
  filterTasksByStatusAndDue,
  calculateFilterCounts,
  sortOverdueDeadlines,
  sortUpcomingDeadlines,
} from '../utils/deadlineClassifier'

function getUrgencyBadgeStyle(urgency) {
  if (!urgency) {
    return {
      label: 'Scheduled',
      bg: 'var(--bg-card-soft)',
      color: 'var(--text-muted)',
      border: 'var(--border)',
    }
  }
  if (urgency.isOverdue) {
    return {
      label: urgency.label || 'Overdue',
      bg: 'rgba(230, 81, 0, 0.12)',
      color: '#e65100',
      border: 'rgba(230, 81, 0, 0.35)',
    }
  }
  if (urgency.timing === 'due_today') {
    return {
      label: urgency.label || 'Due Today',
      bg: 'rgba(217, 119, 6, 0.12)',
      color: '#d97706',
      border: 'rgba(217, 119, 6, 0.35)',
    }
  }
  if (urgency.timing === 'urgent') {
    return {
      label: urgency.label || 'Urgent (<24h)',
      bg: 'rgba(239, 68, 68, 0.12)',
      color: '#ef4444',
      border: 'rgba(239, 68, 68, 0.35)',
    }
  }
  if (urgency.timing === 'due_soon') {
    return {
      label: urgency.label || 'Due Soon',
      bg: 'rgba(14, 165, 233, 0.12)',
      color: '#0284c7',
      border: 'rgba(14, 165, 233, 0.35)',
    }
  }
  return {
    label: urgency.label || 'Upcoming',
    bg: 'rgba(16, 185, 129, 0.10)',
    color: '#059669',
    border: 'rgba(16, 185, 129, 0.30)',
  }
}

function formatActivityTimestamp(ts) {
  if (!ts) return 'Recently'
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return ts
    const now = new Date()
    const diffMs = now.getTime() - d.getTime()
    if (diffMs >= 0 && diffMs < 60000) return 'Just now'
    if (diffMs >= 0 && diffMs < 3600000) return `${Math.floor(diffMs / 60000)}m ago`
    return d.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
    }) + ', ' + d.toLocaleTimeString(undefined, {
      hour: 'numeric',
      minute: '2-digit',
    })
  } catch {
    return ts
  }
}

export default function Dashboard({

  tasks = [],
  backendStatus = 'Waking up the server…',
  usageStats = null,
  currentUser = null,
  onSelectTab,
  onSelectDomain,
  isDarkMode = false,
  onToggleDarkMode,
  onTasksUpdated,
  onOpenCompass,
  onOpenAuth,
  customDomains = [],
}) {
  const [selectedDomainFilter, setSelectedDomainFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all') // 'all' | 'pending' | 'in_progress' | 'completed'
  const [dueFilter, setDueFilter] = useState('all') // 'all' | 'overdue' | 'due_today' | 'urgent' | 'due_soon' | 'upcoming'
  const [priorityFilter, setPriorityFilter] = useState('all') // 'all' | 'overdue' | 'today' | 'upcoming'
  const [optimisticOverrides, setOptimisticOverrides] = useState({})
  const [showAddModal, setShowAddModal] = useState(false)
  const [showAboutModal, setShowAboutModal] = useState(false)
  const [savedToast, setSavedToast] = useState(false)
  const [completedInSession, setCompletedInSession] = useState(() => new Set())
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [lastRefreshedAt, setLastRefreshedAt] = useState(() => new Date())

  const handleClearFilters = useCallback(() => {
    setStatusFilter('all')
    setDueFilter('all')
  }, [])

  const today = useMemo(() => {
    return new Date().toLocaleDateString('en-US', {
      weekday: 'long',
      month: 'short',
      day: 'numeric',
    })
  }, [])

  const isOnline = useMemo(() => {
    const s = (backendStatus || '').toLowerCase()
    return s.includes('neon') || s.includes('live') || s.includes('connected') || s.includes('ready')
  }, [backendStatus])

  const hasFallbackTasks = useMemo(() => {
    return Array.isArray(tasks) && tasks.some((t) => t && t.is_fallback)
  }, [tasks])

  // Defensive sanitization and optimistic state merging
  const cleanTasks = useMemo(() => {
    if (!Array.isArray(tasks)) return []
    return tasks
      .filter((t) => t && typeof t === 'object' && t.id !== undefined && t.id !== null)
      .map((t) => {
        const override = optimisticOverrides[t.id]
        if (override) {
          return { ...t, status: override }
        }
        return t
      })
  }, [tasks, optimisticOverrides])

  // Apply domain filter
  const domainFilteredTasks = useMemo(() => {
    if (!selectedDomainFilter || selectedDomainFilter === 'all') {
      return cleanTasks
    }
    return cleanTasks.filter((t) => (t.domain || 'general').toLowerCase().trim() === selectedDomainFilter)
  }, [cleanTasks, selectedDomainFilter])

  // Exact view counts matching the 8 contextual categories
  const viewCounts = useMemo(() => {
    const now = new Date()
    const counts = {
      all: domainFilteredTasks.length,
      overdue: 0,
      due_today: 0,
      urgent: 0,
      due_soon: 0,
      upcoming: 0,
      pending: 0,
      in_progress: 0,
      completed: 0,
    }

    domainFilteredTasks.forEach((t) => {
      const c = classifyDeadline(t, now)
      if (c.lifecycle === 'completed') {
        counts.completed++
      } else if (c.lifecycle === 'cancelled') {
        // cancelled tasks excluded from active counts
      } else {
        if (c.timing === 'overdue' && c.isActiveDeadline) counts.overdue++
        if (c.timing === 'due_today' && c.isActiveDeadline) counts.due_today++
        if ((c.timing === 'urgent' || c.timing === 'due_today') && c.isActiveDeadline) counts.urgent++
        if (c.timing === 'due_soon' && c.isActiveDeadline) counts.due_soon++
        if (c.timing === 'upcoming' && c.isActiveDeadline) counts.upcoming++
        if (c.lifecycle === 'pending') counts.pending++
        if (c.lifecycle === 'in_progress') counts.in_progress++
      }
    })

    return counts
  }, [domainFilteredTasks])

  // Accurate dynamic filter counts for Status and Due groups
  const filterCounts = useMemo(() => {
    const now = new Date()
    return calculateFilterCounts(domainFilteredTasks, statusFilter, dueFilter, now)
  }, [domainFilteredTasks, statusFilter, dueFilter])

  // Apply combined status and due filter
  const displayedTasks = useMemo(() => {
    const now = new Date()
    return filterTasksByStatusAndDue(domainFilteredTasks, statusFilter, dueFilter, now)
  }, [domainFilteredTasks, statusFilter, dueFilter])

  const isFiltered = statusFilter !== 'all' || dueFilter !== 'all'

  // Metric calculations
  const metrics = useMemo(() => {
    const total = domainFilteredTasks.length
    const completedCount = viewCounts.completed
    const overdueCount = viewCounts.overdue
    let completedTodayCount = 0
    const now = new Date()
    const todayStr = now.toDateString()
    const todayShort = now.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toLowerCase()
    const todayIsoDate = now.toISOString().slice(0, 10)

    domainFilteredTasks.forEach((t) => {
      const s = (t.status || '').toLowerCase()
      const c = (t.countdown || '').toLowerCase()
      const isCompleted = s === 'completed' || s === 'done' || c === 'completed'

      if (isCompleted) {
        let isToday = false
        const candidateDate = t.completed_at || t.updated_at || t.timestamp
        if (candidateDate) {
          const d = new Date(candidateDate)
          if (!isNaN(d.getTime()) && d.toDateString() === todayStr) {
            isToday = true
          }
          const ts = String(candidateDate).toLowerCase()
          if (
            ts.includes('just now') ||
            ts.includes('min') ||
            ts.includes('hour') ||
            ts.includes('today') ||
            ts.includes(todayShort) ||
            ts.startsWith(todayIsoDate)
          ) {
            isToday = true
          }
        }
        if (completedInSession.has(t.id)) {
          isToday = true
        }
        if (isToday) {
          completedTodayCount++
        }
      }
    })
    completedTodayCount = Math.min(completedTodayCount, completedCount)

    const completionRate = total > 0 ? Math.round((completedCount / total) * 100) : 0

    return {
      total,
      completedCount,
      completionRate,
      overdueCount,
      completedTodayCount,
    }
  }, [domainFilteredTasks, viewCounts, completedInSession])


  // Tasks by Domain breakdown
  const domainBreakdown = useMemo(() => {
    const baseKeys = ['hackathon', 'coursework', 'code', 'general', 'other']
    const discoveredKeys = new Set(baseKeys)

    cleanTasks.forEach((t) => {
      if (t.domain) {
        discoveredKeys.add(String(t.domain).toLowerCase().trim())
      }
    })

    const counts = {}
    discoveredKeys.forEach((k) => {
      counts[k] = 0
    })

    cleanTasks.forEach((t) => {
      const d = (t.domain || 'general').toLowerCase().trim()
      counts[d] = (counts[d] || 0) + 1
    })

    const list = Array.from(discoveredKeys).map((key) => {
      const meta = getDomainMeta(key)
      const count = counts[key] || 0
      const pct = cleanTasks.length > 0 ? Math.round((count / cleanTasks.length) * 100) : 0
      return {
        key,
        label: meta.label || key,
        icon: meta.icon || '',
        color: meta.color || 'var(--brand)',
        count,
        pct: Math.min(100, Math.max(0, pct)),
      }
    })

    list.sort((a, b) => b.count - a.count)
    return list
  }, [cleanTasks])

  // "Today's Focus" analysis
  const todayFocus = useMemo(() => {
    const now = new Date()
    const openTasks = domainFilteredTasks.filter((t) => {
      const s = (t.status || '').toLowerCase()
      const c = (t.countdown || '').toLowerCase()
      return s !== 'completed' && s !== 'done' && c !== 'completed'
    })

    const attentionItems = openTasks
      .map((t) => ({ task: t, urgency: classifyDeadline(t, now) }))
      .filter(({ urgency }) => urgency.isOverdue || urgency.timing === 'due_today' || urgency.timing === 'urgent')

    const nextUpcoming = sortUpcomingDeadlines(domainFilteredTasks, now)[0] || null

    return {
      urgentItems: attentionItems.map((u) => u.task),
      count: attentionItems.length,
      nextItem: nextUpcoming ? nextUpcoming : null,
      nextUrgency: nextUpcoming ? nextUpcoming.urgency : null,
    }
  }, [domainFilteredTasks])


  // Varied Priority Deadlines: balanced cross-section across ALL urgency tiers
  // (Overdue + Due Today + Urgent + Due Soon + Upcoming) so all varieties are visible at a glance
  const priorityDeadlines = useMemo(() => {
    const now = new Date()
    const overdue = sortOverdueDeadlines(domainFilteredTasks, now)
    const upcoming = sortUpcomingDeadlines(domainFilteredTasks, now)

    if (priorityFilter === 'overdue') {
      return overdue.slice(0, 8)
    }
    if (priorityFilter === 'today') {
      return upcoming.filter((t) => t.urgency?.timing === 'due_today' || t.urgency?.timing === 'urgent').slice(0, 8)
    }
    if (priorityFilter === 'due_soon') {
      return upcoming.filter((t) => t.urgency?.timing === 'due_soon').slice(0, 8)
    }
    if (priorityFilter === 'upcoming') {
      return upcoming.filter((t) => t.urgency?.timing === 'upcoming' || t.urgency?.timing === 'due_soon').slice(0, 8)
    }

    // Default 'all': balanced selection across all 5 urgency categories:
    // (Overdue, Due Today, Urgent <24h, Due Soon 2-7d, Upcoming >7d)
    const dueToday = upcoming.filter((t) => t.urgency?.timing === 'due_today')
    const urgent = upcoming.filter((t) => t.urgency?.timing === 'urgent')
    const dueSoon = upcoming.filter((t) => t.urgency?.timing === 'due_soon')
    const laterUpcoming = upcoming.filter((t) => t.urgency?.timing === 'upcoming')

    const selected = []
    const addedIds = new Set()
    const addUnique = (task) => {
      if (!task || addedIds.has(task.id)) return false
      addedIds.add(task.id)
      selected.push(task)
      return true
    }

    // Diverse cross-section across all tiers: 1 Overdue, 1 Due Today, 1 Urgent (<24h), 2 Due Soon (2-4d), 2 Upcoming (>7d)
    overdue.slice(0, 1).forEach(addUnique)
    dueToday.slice(0, 1).forEach(addUnique)
    urgent.slice(0, 1).forEach(addUnique)
    dueSoon.slice(0, 2).forEach(addUnique)
    laterUpcoming.slice(0, 2).forEach(addUnique)

    // Backfill across remaining tasks up to 8 so all tiers have presence
    overdue.slice(1).forEach((t) => { if (selected.length < 8) addUnique(t) })
    dueToday.slice(1).forEach((t) => { if (selected.length < 8) addUnique(t) })
    dueSoon.slice(2).forEach((t) => { if (selected.length < 8) addUnique(t) })
    laterUpcoming.slice(2).forEach((t) => { if (selected.length < 8) addUnique(t) })
    urgent.slice(1).forEach((t) => { if (selected.length < 8) addUnique(t) })

    return selected.slice(0, 8)
  }, [domainFilteredTasks, priorityFilter])



  // Recent Activity Feed
  const recentActivity = useMemo(() => {
    return displayedTasks.slice(0, 5)
  }, [displayedTasks])

  // Task Completion Checkbox Handler
  const handleToggleTaskStatus = useCallback(
    async (taskId, currentlyCompleted) => {
      const newStatus = currentlyCompleted ? 'open' : 'completed'
      // Optimistic update
      setOptimisticOverrides((prev) => ({ ...prev, [taskId]: newStatus }))
      if (!currentlyCompleted) {
        setCompletedInSession((prev) => new Set([...prev, taskId]))
      } else {
        setCompletedInSession((prev) => {
          const next = new Set(prev)
          next.delete(taskId)
          return next
        })
      }

      try {
        await updateTask(taskId, { status: newStatus })
        // Server now holds the new status; drop the override so it cannot mask later server data
        setOptimisticOverrides((prev) => {
          const next = { ...prev }
          delete next[taskId]
          return next
        })
        if (onTasksUpdated) {
          onTasksUpdated()
        }
      } catch (err) {
        console.warn('Failed to update task status from dashboard:', err)
        // Rollback on error
        setOptimisticOverrides((prev) => {
          const next = { ...prev }
          delete next[taskId]
          return next
        })
      }
    },
    [onTasksUpdated]
  )

  // Navigate to task in Timeline and highlight
  const handleNavigateToTask = useCallback(
    (task) => {
      if (!task) return
      try {
        window.sessionStorage.setItem('compass_highlight_task_id', String(task.id))
        window.dispatchEvent(
          new window.CustomEvent('compass:highlight-task', { detail: { taskId: String(task.id) } })
        )
      } catch {
        /* ignore storage access error */
      }
      if (onSelectTab) {
        onSelectTab('timeline')
      }
    },
    [onSelectTab]
  )

  // Manual Refresh Handler
  const handleManualRefresh = useCallback(() => {
    setIsRefreshing(true)
    if (onTasksUpdated) {
      onTasksUpdated()
    }
    setLastRefreshedAt(new Date())
    setTimeout(() => setIsRefreshing(false), 600)
  }, [onTasksUpdated])

  // Last updated human text
  const [timeSinceUpdate, setTimeSinceUpdate] = useState('just now')
  useEffect(() => {
    const timer = setInterval(() => {
      const sec = Math.floor((Date.now() - lastRefreshedAt.getTime()) / 1000)
      if (sec < 60) {
        setTimeSinceUpdate('just now')
      } else if (sec < 3600) {
        setTimeSinceUpdate(`${Math.floor(sec / 60)}m ago`)
      } else {
        setTimeSinceUpdate(`${Math.floor(sec / 3600)}h ago`)
      }
    }, 15000)
    return () => clearInterval(timer)
  }, [lastRefreshedAt])

  return (
    <div className="dashboard-container" style={{ background: 'var(--bg-app)' }} role="main" aria-label="Compass Dashboard">
      {/* Offline / Demo Warning Banner */}
      {hasFallbackTasks && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 16px',
            background: 'var(--bg-card-soft)',
            border: '1px solid var(--border)',
            borderRadius: '6px',
            marginBottom: '18px',
            fontSize: '13px',
            color: 'var(--text-primary)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
            </svg>
            <span>
              <strong>Demo / Offline Mode:</strong> Backend server is connecting. Displaying cached demo tasks. Your changes will sync once connected.
            </span>
          </div>
          <button
            type="button"
            onClick={handleManualRefresh}
            className="btn-secondary"
            style={{
              minHeight: '36px',
              padding: '0 12px',
              fontSize: '12px',
              fontWeight: '600',
            }}
          >
            Retry Sync
          </button>
        </div>
      )}

      {/* Page Header */}
      <div style={{ marginBottom: '22px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <h2
                style={{
                  fontSize: '26px',
                  fontWeight: '600',
                  color: 'var(--text-primary)',
                  letterSpacing: '-0.3px',
                  margin: 0,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  flexWrap: 'wrap',
                  lineHeight: 1.2,
                }}
              >
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <rect width="7" height="9" x="3" y="3" rx="1" />
                  <rect width="7" height="5" x="14" y="3" rx="1" />
                  <rect width="7" height="9" x="14" y="12" rx="1" />
                  <rect width="7" height="5" x="3" y="16" rx="1" />
                </svg>
                <span>Dashboard,</span>
                <span style={{ color: 'var(--text-muted)', fontWeight: '400', fontSize: '15px' }}>
                  {today}
                </span>
              </h2>
            </div>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px', marginBottom: 0 }}>
              Your student workspace for internships, deadlines, and weekly planning
            </p>
          </div>

          {/* Header Action Buttons & Dark Mode Toggle: 1 primary amber, rest secondary */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <button
              type="button"
              id="dashboard-btn-new-task"
              onClick={() => setShowAddModal(true)}
              className="btn-primary-amber"
              aria-label="Add new task or deadline"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M5 12h14" />
                <path d="M12 5v14" />
              </svg>
              <span>New Deadline</span>
            </button>

            <button
              type="button"
              id="dashboard-btn-about-judges"
              onClick={() => setShowAboutModal(true)}
              className="btn-secondary"
              title="Architecture, AI telemetry, and evaluation guide for hackathon judges"
              style={{
                minHeight: '44px',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '0 12px',
                borderRadius: 'var(--radius-btn, 6px)',
                fontSize: '13px',
                fontWeight: '500',
              }}
            >
              <BookOpen size={14} strokeWidth={1.8} style={{ color: 'var(--accent)' }} />
              <span>About / for judges</span>
            </button>

            <button
              type="button"
              id="dashboard-btn-refresh"
              onClick={handleManualRefresh}
              className="btn-secondary"
              aria-label="Refresh dashboard data"
              title={`Last synced: ${timeSinceUpdate}`}
              style={{
                minHeight: '44px',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                padding: '0 12px',
                borderRadius: 'var(--radius-btn, 6px)',
              }}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
                style={{
                  flexShrink: 0,
                  animation: isRefreshing ? 'spin 0.6s linear infinite' : 'none',
                }}
              >
                <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
                <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
                <path d="M16 21h5v-5" />
              </svg>
              <span style={{ fontSize: '12px', whiteSpace: 'nowrap' }}>{timeSinceUpdate}</span>
            </button>

            <div style={{ flexShrink: 0 }}>
              <DarkModeToggle
                isDarkMode={Boolean(isDarkMode)}
                onToggleDarkMode={onToggleDarkMode}
                id="dashboard-theme-toggle"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Welcome Card for Students with 3 Big Buttons (N-005) */}
      <div
        className="dashboard-welcome-card"
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-card, 8px)',
          padding: '20px 22px',
          marginBottom: '20px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
          <div>
            <h3 style={{ fontSize: '18px', fontWeight: '600', color: 'var(--text-primary)', margin: '0 0 4px 0', lineHeight: 1.35 }}>
              Compass keeps your deadlines, coursework and internship hunt in one place, and asks before it changes anything.
            </h3>
            <p style={{ fontSize: '13.5px', color: 'var(--text-secondary)', margin: 0 }}>
              You are in a private guest workspace. No signup. Nothing you add is shared.
            </p>
            <p id="welcome-sponsor-line" style={{ fontSize: '12.5px', color: 'var(--text-muted)', margin: '6px 0 0 0' }}>
              Runs on NVIDIA Nemotron models through Nebius Token Factory, with Tavily web search.{' '}
              <button
                type="button"
                id="welcome-link-how-it-works"
                onClick={() => setShowAboutModal(true)}
                style={{ background: 'none', border: 'none', padding: 0, font: 'inherit', color: 'var(--accent)', textDecoration: 'underline', cursor: 'pointer' }}
              >
                How it works
              </button>
            </p>
          </div>
          <button
            type="button"
            id="welcome-link-about-judges"
            onClick={() => setShowAboutModal(true)}
            style={{
              background: 'transparent',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              padding: '6px 12px',
              fontSize: '12px',
              fontWeight: '500',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
            }}
            title="Architecture, AI telemetry, and evaluation guide"
          >
            <span>About / for judges</span>
            <span style={{ fontSize: '12px', background: 'var(--bg-card-soft)', padding: '1px 5px', borderRadius: '4px', border: '1px solid var(--border)' }}>Guide</span>
          </button>
        </div>

        {/* 3 Big Buttons */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '12px',
          }}
        >
          <button
            type="button"
            id="welcome-btn-internships"
            onClick={() => onSelectTab && onSelectTab('career')}
            className="btn-touch-target"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              padding: '14px 16px',
              background: 'var(--bg-card-soft)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              cursor: 'pointer',
              textAlign: 'left',
              color: 'var(--text-primary)',
              transition: 'all 0.15s ease',
            }}
          >
            <div
              style={{
                width: '40px',
                height: '40px',
                borderRadius: '8px',
                background: 'rgba(28, 138, 98, 0.12)',
                color: 'var(--domain-code, #1c8a62)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <rect width="20" height="14" x="2" y="7" rx="2" ry="2" />
                <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
              </svg>
            </div>
            <div>
              <div style={{ fontSize: '14px', fontWeight: '600' }}>Find internships</div>
              <div style={{ fontSize: '12.5px', color: 'var(--text-secondary)', marginTop: '2px' }}>Explore matched roles</div>
            </div>
          </button>

          <button
            type="button"
            id="welcome-btn-plan-week"
            onClick={() => {
              if (onOpenCompass) {
                onOpenCompass('Plan my week: help me organize my deadlines and study schedule')
              }
            }}
            className="btn-touch-target"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              padding: '14px 16px',
              background: 'var(--bg-card-soft)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              cursor: 'pointer',
              textAlign: 'left',
              color: 'var(--text-primary)',
              transition: 'all 0.15s ease',
            }}
          >
            <div
              style={{
                width: '40px',
                height: '40px',
                borderRadius: '8px',
                background: 'rgba(245, 166, 35, 0.12)',
                color: 'var(--accent, #f5a623)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <rect width="18" height="18" x="3" y="4" rx="2" ry="2" />
                <line x1="16" y1="2" x2="16" y2="6" />
                <line x1="8" y1="2" x2="8" y2="6" />
                <line x1="3" y1="10" x2="21" y2="10" />
              </svg>
            </div>
            <div>
              <div style={{ fontSize: '14px', fontWeight: '600' }}>Plan my week</div>
              <div style={{ fontSize: '12.5px', color: 'var(--text-secondary)', marginTop: '2px' }}>Organize deadlines & schedule</div>
            </div>
          </button>

          <button
            type="button"
            id="welcome-btn-ask-question"
            onClick={() => {
              if (onOpenCompass) {
                onOpenCompass('')
              }
            }}
            className="btn-touch-target"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              padding: '14px 16px',
              background: 'var(--bg-card-soft)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              cursor: 'pointer',
              textAlign: 'left',
              color: 'var(--text-primary)',
              transition: 'all 0.15s ease',
            }}
          >
            <div
              style={{
                width: '40px',
                height: '40px',
                borderRadius: '8px',
                background: 'rgba(59, 130, 246, 0.12)',
                color: '#2563eb',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <div>
              <div style={{ fontSize: '14px', fontWeight: '600' }}>Ask a question</div>
              <div style={{ fontSize: '12.5px', color: 'var(--text-secondary)', marginTop: '2px' }}>Chat with Compass AI</div>
            </div>
          </button>
        </div>

        <TourCard onRun={(prompt) => onOpenCompass && onOpenCompass(prompt)} />
      </div>

      {/* SECTION: Waking backend state (N-012) */}
      {!isOnline && cleanTasks.length === 0 && (
        <div
          className="dashboard-waking-card"
          role="status"
          aria-live="polite"
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '44px 24px',
            textAlign: 'center',
            background: 'var(--bg-card)',
            borderRadius: 'var(--radius-card, 8px)',
            border: '1px solid var(--border)',
            marginBottom: '20px',
          }}
        >
          <div style={{ marginBottom: '16px' }}>
            <Logo size={42} alt="Compass Logo" />
          </div>
          <h3 style={{ fontSize: '18px', fontWeight: '600', color: 'var(--text-primary)', margin: '0 0 8px 0' }}>
            Starting the server. This takes about 30 seconds and only happens after a quiet period.
          </h3>
          <p style={{ fontSize: '13.5px', color: 'var(--text-secondary)', maxWidth: '480px', margin: '0 0 20px 0', lineHeight: 1.5 }}>
            While you wait:{' '}
            <a href={DEMO_VIDEO_URL} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)', fontWeight: 600 }}>
              watch the 3-minute demo
            </a>
          </p>
          <div
            style={{
              width: '100%',
              maxWidth: '320px',
              height: '6px',
              background: 'var(--bg-card-soft)',
              borderRadius: '3px',
              overflow: 'hidden',
              border: '1px solid var(--border)',
            }}
          >
            <div
              className="waking-progress-bar"
              style={{
                height: '100%',
                background: 'var(--accent, #f5a623)',
                borderRadius: '3px',
              }}
            />
          </div>
        </div>
      )}

      {/* SECTION: Today's Focus Banner (Shown only when user has tasks and none are overdue or due today) */}
      {cleanTasks.length > 0 && viewCounts.overdue === 0 && viewCounts.due_today === 0 && (
        <div className="dashboard-focus-card" role="region" aria-label="Today's focus area" style={{ borderRadius: '8px', border: '1px solid var(--border)', marginBottom: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0, flex: 1 }}>
            <div
              style={{
                width: '38px',
                height: '38px',
                borderRadius: '6px',
                background: 'var(--bg-card-soft)',
                border: '1px solid var(--border)',
                color: 'var(--text-primary)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="12" cy="12" r="10" />
                <circle cx="12" cy="12" r="6" />
                <circle cx="12" cy="12" r="2" />
              </svg>
            </div>

            <div style={{ minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <span style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)' }}>
                  {todayFocus.nextItem ? 'No deadlines due today' : "You're all caught up for today!"}
                </span>
                {todayFocus.nextUrgency && (
                  <span
                    style={{
                      fontSize: '12px',
                      fontWeight: '600',
                      padding: '2px 8px',
                      borderRadius: '4px',
                      background: 'var(--bg-card-soft)',
                      color: 'var(--text-primary)',
                      border: '1px solid var(--border)',
                    }}
                  >
                    {todayFocus.nextUrgency.label}
                  </span>
                )}
              </div>

              <div
                style={{
                  fontSize: '13px',
                  color: 'var(--text-muted)',
                  marginTop: '2px',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
                title={todayFocus.nextItem ? todayFocus.nextItem.title : ''}
              >
                {todayFocus.nextItem ? (
                  <>
                    Next up: <strong style={{ color: 'var(--text-primary)' }}>{todayFocus.nextItem.title}</strong>{' '}
                    <span style={{ color: 'var(--text-muted)' }}>({todayFocus.nextItem.project || todayFocus.nextItem.domain})</span>
                  </>
                ) : (
                  'No deadlines scheduled for today. Enjoy your focused time or plan your upcoming schedule.'
                )}
              </div>
            </div>
          </div>

          {/* Focus Actions: min 44px tap target */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
            {onOpenCompass && (
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  const prompt = 'Please review my upcoming tasks and projects and propose a focus schedule for this week.'
                  onOpenCompass(prompt)
                }}
              >
                <Logo size={14} alt="" />
                <span>Ask Compass to Plan</span>
              </button>
            )}
          </div>
        </div>
      )}

      {/* DOMAIN FILTER BAR AND STATS (Only render once connected or when tasks exist - N-012) */}
      {(isOnline || cleanTasks.length > 0) && (
      <>
      {/* DOMAIN FILTER BAR */}
      <div className="dashboard-filter-bar" role="tablist" aria-label="Filter dashboard by context domain">
        <button
          type="button"
          onClick={() => setSelectedDomainFilter('all')}
          className={`filter-pill ${selectedDomainFilter === 'all' ? 'active' : ''}`}
          role="tab"
          aria-selected={selectedDomainFilter === 'all'}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect width="7" height="7" x="3" y="3" rx="1" />
            <rect width="7" height="7" x="14" y="3" rx="1" />
            <rect width="7" height="7" x="14" y="14" rx="1" />
            <rect width="7" height="7" x="3" y="14" rx="1" />
          </svg>
          <span>All Domains ({cleanTasks.length})</span>
        </button>

        {domainBreakdown.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setSelectedDomainFilter(item.key)}
            className={`filter-pill ${selectedDomainFilter === item.key ? 'active' : ''}`}
            role="tab"
            aria-selected={selectedDomainFilter === item.key}
          >
            <span className="domain-swatch" style={{ background: item.color }} />
            <span>
              {item.label} ({item.count})
            </span>
          </button>
        ))}

        {selectedDomainFilter !== 'all' && (
          <button
            type="button"
            onClick={() => setSelectedDomainFilter('all')}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              fontSize: '12px',
              fontWeight: '500',
              cursor: 'pointer',
              padding: '0 8px',
              minHeight: '44px',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            <span>Reset filter</span>
            <X size={13} strokeWidth={2} />
          </button>
        )}
      </div>

      {/* SECTION 1: Quick Stat Cards (Interactive Filtering) */}
      <div className="dashboard-stat-grid" role="region" aria-label="Quick statistics">
        {/* Total Tasks */}
        <div
          className={`dashboard-stat-card ${!isFiltered ? 'active-filter' : ''}`}
          onClick={handleClearFilters}
          tabIndex={0}
          role="button"
          aria-pressed={!isFiltered}
          aria-label={`Total tasks: ${metrics.total}. Click to show all tasks.`}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              handleClearFilters()
            }
          }}
          title="Click to view all tasks"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Total Tasks
            </span>
            <span style={{ color: 'var(--text-muted)', display: 'inline-flex' }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <rect width="8" height="4" x="8" y="2" rx="1" ry="1" />
                <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
                <path d="M12 11h4" />
                <path d="M12 16h4" />
                <path d="M8 11h.01" />
                <path d="M8 16h.01" />
              </svg>
            </span>
          </div>
          <div style={{ fontSize: '26px', fontWeight: '600', color: 'var(--text-primary)', letterSpacing: '-0.3px', lineHeight: 1.2 }}>
            {metrics.total}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
            {selectedDomainFilter === 'all' ? 'Across all domains' : `In ${selectedDomainFilter}`}
          </div>
        </div>

        {/* Completion Rate */}
        <div
          className={`dashboard-stat-card ${statusFilter === 'completed' ? 'active-filter' : ''}`}
          onClick={() => {
            setStatusFilter((prev) => (prev === 'completed' ? 'all' : 'completed'))
            if (dueFilter !== 'all') setDueFilter('all')
          }}
          tabIndex={0}
          role="button"
          aria-pressed={statusFilter === 'completed'}
          aria-label={`Completion rate: ${metrics.completionRate} percent. Click to filter completed tasks.`}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              setStatusFilter((prev) => (prev === 'completed' ? 'all' : 'completed'))
              if (dueFilter !== 'all') setDueFilter('all')
            }
          }}
          title="Click to filter completed tasks"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Completion Rate
            </span>
            <span style={{ color: 'var(--text-muted)', display: 'inline-flex' }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
                <polyline points="16 7 22 7 22 13" />
              </svg>
            </span>
          </div>
          <div style={{ fontSize: '26px', fontWeight: '600', color: 'var(--text-primary)', letterSpacing: '-0.3px', lineHeight: 1.2 }}>
            {metrics.total === 0 ? '0%' : `${metrics.completionRate}%`}
          </div>
          <div style={{ width: '100%', height: '4px', background: 'var(--border)', borderRadius: '2px', marginTop: '8px', overflow: 'hidden' }}>
            <div
              style={{
                width: `${metrics.completionRate}%`,
                height: '100%',
                background: 'var(--domain-code)',
                borderRadius: '2px',
                transition: 'width 0.3s ease',
              }}
            />
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px' }}>
            {metrics.completedCount} of {metrics.total} tasks completed
          </div>
        </div>

        {/* Overdue Tasks */}
        <div
          className={`dashboard-stat-card ${dueFilter === 'overdue' ? 'active-filter' : ''}`}
          onClick={() => {
            setDueFilter((prev) => (prev === 'overdue' ? 'all' : 'overdue'))
            if (statusFilter !== 'all') setStatusFilter('all')
          }}
          tabIndex={0}
          role="button"
          aria-pressed={dueFilter === 'overdue'}
          aria-label={`Overdue tasks: ${metrics.overdueCount}. Click to filter overdue tasks.`}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              setDueFilter((prev) => (prev === 'overdue' ? 'all' : 'overdue'))
              if (statusFilter !== 'all') setStatusFilter('all')
            }
          }}
          title="Click to filter overdue tasks"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Overdue
            </span>
            <span style={{ color: metrics.overdueCount > 0 ? 'var(--danger-text)' : 'var(--text-muted)', display: 'inline-flex' }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
            </span>
          </div>
          <div
            style={{
              fontSize: '26px',
              fontWeight: '600',
              color: metrics.overdueCount > 0 ? 'var(--danger-text)' : 'var(--text-primary)',
              letterSpacing: '-0.3px',
              lineHeight: 1.2,
            }}
          >
            {metrics.overdueCount}
          </div>
          <div style={{ fontSize: '12px', color: metrics.overdueCount > 0 ? 'var(--danger-text)' : 'var(--text-muted)', marginTop: '4px' }}>
            {metrics.overdueCount > 0 ? 'Requires attention' : 'No overdue items'}
          </div>
        </div>

        {/* Completed Today */}
        <div
          className={`dashboard-stat-card ${dueFilter === 'due_today' && statusFilter === 'completed' ? 'active-filter' : ''}`}
          onClick={() => {
            setDueFilter((prev) => (prev === 'due_today' ? 'all' : 'due_today'))
            setStatusFilter('completed')
          }}
          tabIndex={0}
          role="button"
          aria-pressed={dueFilter === 'due_today' && statusFilter === 'completed'}
          aria-label={`Completed today: ${metrics.completedTodayCount}. Click to filter today's tasks.`}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              setDueFilter((prev) => (prev === 'due_today' ? 'all' : 'due_today'))
              setStatusFilter('completed')
            }
          }}
          title="Click to filter completed today's tasks"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Completed Today
            </span>
            <span style={{ color: 'var(--text-muted)', display: 'inline-flex' }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
            </span>
          </div>
          <div style={{ fontSize: '26px', fontWeight: '600', color: 'var(--text-primary)', letterSpacing: '-0.3px', lineHeight: 1.2 }}>
            {metrics.completedTodayCount}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Checked off today
          </div>
        </div>
      </div>

      {/* SECTION 1.5: Status & Due Timeline Filters */}
      <TimelineFilterBar
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
        dueFilter={dueFilter}
        onDueChange={setDueFilter}
        statusCounts={filterCounts.statusCounts}
        dueCounts={filterCounts.dueCounts}
        baseOverdueCount={filterCounts.baseOverdueCount}
        totalCount={domainFilteredTasks.length}
        filteredCount={displayedTasks.length}
        onClearFilters={handleClearFilters}
      />

      {/* FILTERED TASKS EXPANDED CARD (Shown when any status or due filter is active) */}
      {isFiltered && (
        <div
          className="dashboard-section-card"
          role="region"
          aria-label={`Filtered view: status ${statusFilter}, due ${dueFilter}`}
          style={{ marginBottom: '20px' }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span>Filtered Tasks ({displayedTasks.length})</span>
            </h3>
            <button
              type="button"
              id="dashboard-btn-clear-expanded-filter"
              onClick={handleClearFilters}
              className="btn-secondary"
              style={{ minHeight: '32px', padding: '0 10px', fontSize: '12px', display: 'inline-flex', alignItems: 'center', gap: '4px' }}
            >
              <span>Clear filters</span>
              <X size={13} strokeWidth={2} />
            </button>
          </div>

          {displayedTasks.length === 0 ? (
            <div className="dashboard-empty-state">
              <p style={{ margin: 0, fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)' }}>
                No tasks match the selected filters
              </p>
              <p style={{ margin: '4px 0 16px 0', fontSize: '13px', color: 'var(--text-muted)' }}>
                Try adjusting your status or due date filters to see more tasks.
              </p>
              <button
                type="button"
                id="dashboard-btn-empty-clear-filters"
                onClick={handleClearFilters}
                className="btn-secondary btn-touch-target"
                style={{
                  minHeight: '44px',
                  padding: '0 16px',
                  fontSize: '13px',
                  fontWeight: '600',
                  borderRadius: 'var(--radius-btn, 6px)',
                  cursor: 'pointer',
                }}
              >
                Clear filters
              </button>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {displayedTasks.map((task) => {
                const meta = getDomainMeta(task.domain)
                const c = classifyDeadline(task)
                const isCompleted = c.lifecycle === 'completed'

                return (
                  <div
                    key={task.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: '12px',
                      padding: '10px 12px',
                      borderRadius: '6px',
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      opacity: isCompleted ? 0.85 : 1,
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => handleToggleTaskStatus(task.id, isCompleted)}
                      className="btn-touch-target"
                      style={{
                        width: '32px',
                        height: '32px',
                        minWidth: '32px',
                        minHeight: '32px',
                        borderRadius: '6px',
                        border: '1px solid var(--border)',
                        background: isCompleted ? 'var(--domain-code)' : 'var(--bg-card-soft)',
                        color: isCompleted ? '#ffffff' : 'var(--text-muted)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        padding: 0,
                        flexShrink: 0,
                      }}
                      title={isCompleted ? 'Mark as open' : 'Mark as completed'}
                      aria-label={`Toggle task completion for ${task.title}`}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    </button>

                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px', flexWrap: 'wrap' }}>
                        <span className="domain-swatch" style={{ background: meta.color }} />
                        <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: '500' }}>
                          {task.project || meta.label}
                        </span>
                        <span
                          style={{
                            fontSize: '12px',
                            fontWeight: '600',
                            padding: '1px 6px',
                            borderRadius: '4px',
                            background: 'var(--bg-card-soft)',
                            color: 'var(--text-secondary)',
                            border: '1px solid var(--border)',
                            textTransform: 'uppercase',
                          }}
                        >
                          {c.priority}
                        </span>
                        {c.lifecycle !== 'pending' && (
                          <span
                            style={{
                              fontSize: '12px',
                              fontWeight: '600',
                              padding: '1px 6px',
                              borderRadius: '4px',
                              background: 'var(--bg-card-soft)',
                              color: 'var(--text-muted)',
                              border: '1px solid var(--border)',
                            }}
                          >
                            {c.lifecycle}
                          </span>
                        )}
                      </div>
                      <div
                        style={{
                          fontSize: '13.5px',
                          fontWeight: '500',
                          color: isCompleted ? 'var(--text-muted)' : 'var(--text-primary)',
                          textDecoration: isCompleted ? 'line-through' : 'none',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {task.title}
                      </div>
                    </div>

                    <div style={{ flexShrink: 0 }}>
                      <span
                        style={{
                          fontSize: '12px',
                          fontWeight: '600',
                          padding: '3px 8px',
                          borderRadius: '6px',
                          background: c.isOverdue
                            ? 'var(--danger-bg)'
                            : c.isUrgent
                            ? 'rgba(230, 81, 0, 0.12)'
                            : 'var(--bg-card-soft)',
                          color: c.isOverdue
                            ? 'var(--danger-text)'
                            : c.isUrgent
                            ? '#e65100'
                            : 'var(--text-secondary)',
                          border: '1px solid var(--border)',
                        }}
                      >
                        {c.label}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}


      {/* SECTION 2 & 3: Main Two-Column Row or Single Page Empty State */}
      {cleanTasks.length === 0 ? (
        <div
          className="dashboard-section-card dashboard-page-empty-state"
          role="region"
          aria-label="Dashboard empty state"
          style={{
            padding: '48px 24px',
            textAlign: 'center',
            background: 'var(--bg-card)',
            borderRadius: 'var(--radius-card, 8px)',
            border: '1px solid var(--border)',
            marginBottom: '20px',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '14px' }}>
            <Logo size={36} alt="Compass logo" />
          </div>
          <h3 style={{ fontSize: '16px', fontWeight: '600', color: 'var(--text-primary)', margin: '0 0 8px 0' }}>
            No tasks or deadlines tracked yet
          </h3>
          <p style={{ fontSize: '13.5px', color: 'var(--text-secondary)', maxWidth: '520px', margin: '0 auto 16px auto', lineHeight: 1.5 }}>
            Use the <strong>New Deadline</strong> button above to track your first milestone, or take the 60-second tour above to see Compass work on a sample week.
          </p>
          <div style={{ display: 'flex', justifyContent: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <button
              type="button"
              id="empty-state-btn-new-task"
              onClick={() => setShowAddModal(true)}
              className="btn-primary-amber"
              style={{ minHeight: '38px', padding: '0 16px', fontSize: '13px', fontWeight: '600', borderRadius: 'var(--radius-btn, 6px)', cursor: 'pointer' }}
            >
              + New Deadline
            </button>
          </div>
        </div>
      ) : (
        <div className="dashboard-main-grid">
          {/* Tasks by Domain */}
          <div className="dashboard-section-card" role="region" aria-label="Tasks distributed by domain">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M12 2H2v10l9.29 9.29c.94.94 2.48.94 3.42 0l6.58-6.58c.94-.94.94-2.48 0-3.42L12 2Z" />
                  <circle cx="7" cy="7" r=".5" fill="currentColor" />
                </svg>
                <span>Tasks by Domain</span>
              </h3>
              {onSelectTab && selectedDomainFilter !== 'all' && (
                <button
                  type="button"
                  onClick={() => {
                    if (onSelectDomain) {
                      onSelectDomain(selectedDomainFilter)
                    }
                    onSelectTab('timeline')
                  }}
                  className="btn-secondary"
                  style={{
                    minHeight: '36px',
                    padding: '0 10px',
                    fontSize: '12px',
                  }}
                >
                  Timeline view →
                </button>
              )}
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {domainBreakdown.map((item) => (
                <div
                  key={item.key}
                  tabIndex={0}
                  role="button"
                  aria-label={`${item.label}: ${item.count} tasks, ${item.pct} percent. Click to filter.`}
                  style={{
                    padding: '10px 12px',
                    borderRadius: '6px',
                    background: selectedDomainFilter === item.key ? 'var(--bg-card-soft)' : 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                  onClick={() => {
                    setSelectedDomainFilter((prev) => (prev === item.key ? 'all' : item.key))
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      setSelectedDomainFilter((prev) => (prev === item.key ? 'all' : item.key))
                    }
                  }}
                  title={`Filter by ${item.label}`}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span className="domain-swatch" style={{ background: item.color }} />
                      <span style={{ fontSize: '13.5px', fontWeight: '500', color: 'var(--text-primary)' }}>
                        {item.label}
                      </span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontSize: '12px', fontWeight: '500', color: 'var(--text-secondary)' }}>
                        {item.count} {item.count === 1 ? 'task' : 'tasks'}
                      </span>
                      <span style={{ fontSize: '12px', color: 'var(--text-muted)', minWidth: '34px', textAlign: 'right' }}>
                        {item.pct}%
                      </span>
                    </div>
                  </div>
                  <div style={{ width: '100%', height: '4px', background: 'var(--border)', borderRadius: '2px', overflow: 'hidden' }}>
                    <div
                      style={{
                        width: `${item.pct}%`,
                        height: '100%',
                        background: item.color,
                        borderRadius: '2px',
                        transition: 'width 0.3s ease',
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Deadlines & Milestones: Varied Urgency Spotlight */}
          <div className="dashboard-section-card" role="region" aria-label="Upcoming deadlines list">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                <h3 style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="12" cy="12" r="10" />
                    <polyline points="12 6 12 12 16 14" />
                  </svg>
                  <span>Deadlines & Milestones</span>
                </h3>

                {/* Quick interactive filter pills on the card */}
                {(viewCounts.overdue > 0 || viewCounts.due_today > 0 || viewCounts.due_soon > 0 || viewCounts.upcoming > 0) && (
                  <div style={{ display: 'flex', gap: '4px', background: 'var(--bg-card-soft)', padding: '2px', borderRadius: '6px', border: '1px solid var(--border)', flexWrap: 'wrap' }}>
                    <button
                      type="button"
                      onClick={() => setPriorityFilter('all')}
                      style={{
                        padding: '3px 8px',
                        fontSize: '12px',
                        fontWeight: priorityFilter === 'all' ? '600' : '400',
                        borderRadius: '4px',
                        border: 'none',
                        background: priorityFilter === 'all' ? 'var(--bg-card)' : 'transparent',
                        color: priorityFilter === 'all' ? 'var(--text-primary)' : 'var(--text-muted)',
                        cursor: 'pointer',
                      }}
                    >
                      All ({viewCounts.overdue + viewCounts.due_today + viewCounts.due_soon + viewCounts.upcoming})
                    </button>
                    {viewCounts.overdue > 0 && (
                      <button
                        type="button"
                        onClick={() => setPriorityFilter('overdue')}
                        style={{
                          padding: '3px 8px',
                          fontSize: '12px',
                          fontWeight: priorityFilter === 'overdue' ? '600' : '400',
                          borderRadius: '4px',
                          border: 'none',
                          background: priorityFilter === 'overdue' ? 'rgba(230, 81, 0, 0.15)' : 'transparent',
                          color: priorityFilter === 'overdue' ? '#e65100' : 'var(--text-muted)',
                          cursor: 'pointer',
                        }}
                      >
                        Overdue ({viewCounts.overdue})
                      </button>
                    )}
                    {viewCounts.due_today > 0 && (
                      <button
                        type="button"
                        onClick={() => setPriorityFilter('today')}
                        style={{
                          padding: '3px 8px',
                          fontSize: '12px',
                          fontWeight: priorityFilter === 'today' ? '600' : '400',
                          borderRadius: '4px',
                          border: 'none',
                          background: priorityFilter === 'today' ? 'rgba(217, 119, 6, 0.15)' : 'transparent',
                          color: priorityFilter === 'today' ? '#d97706' : 'var(--text-muted)',
                          cursor: 'pointer',
                        }}
                      >
                        Today ({viewCounts.due_today})
                      </button>
                    )}
                    {viewCounts.due_soon > 0 && (
                      <button
                        type="button"
                        onClick={() => setPriorityFilter('due_soon')}
                        style={{
                          padding: '3px 8px',
                          fontSize: '12px',
                          fontWeight: priorityFilter === 'due_soon' ? '600' : '400',
                          borderRadius: '4px',
                          border: 'none',
                          background: priorityFilter === 'due_soon' ? 'rgba(14, 165, 233, 0.15)' : 'transparent',
                          color: priorityFilter === 'due_soon' ? '#0284c7' : 'var(--text-muted)',
                          cursor: 'pointer',
                        }}
                      >
                        Due Soon ({viewCounts.due_soon})
                      </button>
                    )}
                    {viewCounts.upcoming > 0 && (
                      <button
                        type="button"
                        onClick={() => setPriorityFilter('upcoming')}
                        style={{
                          padding: '3px 8px',
                          fontSize: '12px',
                          fontWeight: priorityFilter === 'upcoming' ? '600' : '400',
                          borderRadius: '4px',
                          border: 'none',
                          background: priorityFilter === 'upcoming' ? 'rgba(16, 185, 129, 0.15)' : 'transparent',
                          color: priorityFilter === 'upcoming' ? '#059669' : 'var(--text-muted)',
                          cursor: 'pointer',
                        }}
                      >
                        Upcoming ({viewCounts.upcoming})
                      </button>
                    )}
                  </div>
                )}
              </div>

              <button
                type="button"
                onClick={() => {
                  if (onSelectTab) onSelectTab('timeline')
                }}
                className="btn-secondary"
                style={{
                  minHeight: '32px',
                  padding: '0 10px',
                  fontSize: '12px',
                }}
              >
                View all in Timeline →
              </button>
            </div>

            {priorityDeadlines.length === 0 ? (
              <div className="dashboard-empty-state">
                <p style={{ margin: 0, fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)' }}>
                  No pending deadlines in this view
                </p>
                <p style={{ margin: '4px 0 0 0', fontSize: '13px', color: 'var(--text-muted)' }}>
                  You have cleared all scheduled deadlines in this category.
                </p>
              </div>
            ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {priorityDeadlines.map((task) => {
                const meta = getDomainMeta(task.domain)
                const badge = getUrgencyBadgeStyle(task.urgency)

                return (
                  <div
                    key={task.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: '12px',
                      padding: '10px 12px',
                      borderRadius: '6px',
                      background: task.urgency?.isOverdue ? 'rgba(230, 81, 0, 0.04)' : 'var(--bg-card)',
                      border: task.urgency?.isOverdue ? '1px solid rgba(230, 81, 0, 0.25)' : '1px solid var(--border)',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => handleToggleTaskStatus(task.id, false)}
                      className="btn-touch-target"
                      style={{
                        width: '32px',
                        height: '32px',
                        minWidth: '32px',
                        minHeight: '32px',
                        borderRadius: '6px',
                        border: '1px solid var(--border)',
                        background: 'var(--bg-card-soft)',
                        color: 'var(--text-muted)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        padding: 0,
                        flexShrink: 0,
                        transition: 'all 0.15s ease',
                      }}
                      title="Mark as completed"
                      aria-label={`Mark task ${task.title} as completed`}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    </button>

                    <div
                      style={{ minWidth: 0, flex: 1, cursor: onSelectTab ? 'pointer' : 'default' }}
                      onClick={() => {
                        if (onSelectTab) onSelectTab('timeline')
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }}>
                        <span className="domain-swatch" style={{ background: meta.color }} />
                        <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: '500' }}>
                          {task.project || meta.label}
                        </span>
                      </div>
                      <div
                        style={{
                          fontSize: '13.5px',
                          fontWeight: '500',
                          color: 'var(--text-primary)',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}
                        title={task.title}
                      >
                        {task.title || 'Untitled Task'}
                      </div>
                    </div>

                    <div style={{ flexShrink: 0 }}>
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          background: badge.bg,
                          color: badge.color,
                          border: `1px solid ${badge.border}`,
                          padding: '3px 8px',
                          borderRadius: '6px',
                          fontSize: '12px',
                          fontWeight: '600',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {badge.label}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    )}

      {/* SECTION 4 & 5: Recent Activity & System Status */}
      <div className="dashboard-main-grid">
        {/* Recent Activity */}
        {cleanTasks.length > 0 && (
          <div className="dashboard-section-card" role="region" aria-label="Recent activity feed">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
              </svg>
              <span>Recent Activity</span>
            </h3>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: '500' }}>
              Latest milestones
            </span>
          </div>

          {recentActivity.length === 0 ? (
            <div className="dashboard-empty-state">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ marginBottom: '8px', color: 'var(--text-muted)' }}>
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
              <p style={{ margin: 0, fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)' }}>
                No activity to display
              </p>
              <p style={{ margin: '4px 0 0 0', fontSize: '13px', color: 'var(--text-muted)' }}>
                Completed and created tasks will appear here.
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {recentActivity.map((task) => {
                const meta = getDomainMeta(task.domain)
                const isCompleted =
                  (task.status || '').toLowerCase() === 'completed' ||
                  (task.status || '').toLowerCase() === 'done' ||
                  (task.countdown || '').toLowerCase() === 'completed'

                return (
                  <div
                    key={task.id}
                    id={`recent-activity-task-${task.id}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => handleNavigateToTask(task)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        handleNavigateToTask(task)
                      }
                    }}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: '12px',
                      padding: '10px 12px',
                      borderRadius: '6px',
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      opacity: isCompleted ? 0.85 : 1,
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                    }}
                    aria-label={`Navigate to task: ${task.title || 'Untitled task'}`}
                  >
                    {/* Toggle button */}
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleToggleTaskStatus(task.id, isCompleted)
                      }}
                      className="btn-touch-target"
                      style={{
                        width: '32px',
                        height: '32px',
                        minWidth: '32px',
                        minHeight: '32px',
                        borderRadius: '6px',
                        border: '1px solid var(--border)',
                        background: isCompleted ? 'var(--domain-code)' : 'var(--bg-card-soft)',
                        color: isCompleted ? '#ffffff' : 'var(--text-muted)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        padding: 0,
                        flexShrink: 0,
                        transition: 'all 0.15s ease',
                      }}
                      title={isCompleted ? 'Mark as open' : 'Mark as completed'}
                      aria-label={`Toggle task completion for ${task.title}`}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    </button>

                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px', flexWrap: 'wrap' }}>
                        <span
                          style={{
                            fontSize: '12px',
                            padding: '2px 8px',
                            borderRadius: '4px',
                            fontWeight: '500',
                            background: 'var(--bg-card-soft)',
                            color: 'var(--text-primary)',
                            border: '1px solid var(--border)',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '6px',
                          }}
                        >
                          <span className="domain-swatch" style={{ background: meta.color }} />
                          <span>{meta.label}</span>
                        </span>
                        <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                          {formatActivityTimestamp(task.timestamp || task.created_at)}
                        </span>
                      </div>
                      <div
                        style={{
                          fontSize: '13.5px',
                          fontWeight: '500',
                          color: isCompleted ? 'var(--text-muted)' : 'var(--text-primary)',
                          textDecoration: isCompleted ? 'line-through' : 'none',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}
                        aria-label={task.title || 'Untitled task'}
                      >
                        {task.title || 'Untitled task'}
                      </div>
                    </div>

                    {/* Non-button status chip */}
                    <div style={{ flexShrink: 0, pointerEvents: 'none' }}>
                      <span
                        style={{
                          fontSize: '12px',
                          fontWeight: '500',
                          padding: '3px 9px',
                          borderRadius: '12px',
                          background: isCompleted ? 'rgba(16, 185, 129, 0.12)' : 'var(--bg-card-soft)',
                          color: isCompleted ? '#059669' : 'var(--text-secondary)',
                          border: isCompleted ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid var(--border)',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '5px',
                          userSelect: 'none',
                        }}
                        aria-label={`Status: ${isCompleted ? 'Completed' : 'Open'}`}
                      >
                        <span
                          style={{
                            width: '6px',
                            height: '6px',
                            borderRadius: '50%',
                            background: isCompleted ? '#059669' : 'var(--text-muted)',
                          }}
                          aria-hidden="true"
                        />
                        <span>{isCompleted ? 'Completed' : 'Open'}</span>
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

        {/* Workspace & Privacy Status (Clean student view, N-005) */}
        <div className="dashboard-section-card" role="region" aria-label="Workspace and account status">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <rect width="20" height="8" x="2" y="2" rx="2" ry="2" />
                <rect width="20" height="8" x="2" y="14" rx="2" ry="2" />
                <line x1="6" y1="6" x2="6.01" y2="6" />
                <line x1="6" y1="18" x2="6.01" y2="18" />
              </svg>
              <span>Workspace Status</span>
            </h3>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: '12px',
                fontWeight: '500',
                padding: '3px 8px',
                borderRadius: '6px',
                background: 'var(--bg-card-soft)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border)',
              }}
            >
              <span
                style={{
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  background: isOnline ? '#1c8a62' : '#f5a623',
                }}
              />
              {isOnline ? 'Synced & Online' : 'Connecting'}
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {/* Workspace & Google Calendar Connection */}
            <div
              style={{
                padding: '10px 12px',
                borderRadius: '6px',
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: '600', textTransform: 'uppercase' }}>
                  Workspace & Calendar
                </div>
                <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)', marginTop: '2px' }}>
                  {currentUser?.calendar?.connected
                    ? `Google Calendar (${currentUser.calendar.mode === 'live' ? 'Live' : 'Demo'})`
                    : 'Private Guest Workspace'}
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '1px' }}>
                  {currentUser?.email || 'Saved locally in this browser'}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                {onOpenAuth && (
                  <button
                    type="button"
                    onClick={onOpenAuth}
                    className="btn-secondary"
                    style={{
                      minHeight: '36px',
                      padding: '0 10px',
                      fontSize: '12px',
                    }}
                  >
                    {currentUser?.authenticated ? 'Account' : 'Sign in'}
                  </button>
                )}
              </div>
            </div>

            {/* Link to About & Telemetry for judges */}
            <div
              style={{
                padding: '12px',
                borderRadius: '6px',
                background: 'var(--bg-card-soft)',
                border: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: '8px',
              }}
            >
              <div>
                <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>
                  System Architecture & Telemetry
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '1px' }}>
                  Model metrics, token usage, and evaluation resources for hackathon judges
                </div>
              </div>
              <button
                type="button"
                id="dashboard-btn-open-about-footer"
                onClick={() => setShowAboutModal(true)}
                className="btn-secondary"
                style={{
                  minHeight: '34px',
                  padding: '0 12px',
                  fontSize: '12px',
                  fontWeight: '600',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                }}
              >
                <BookOpen size={13} style={{ color: 'var(--accent)' }} />
                <span>View About / Judges →</span>
              </button>
            </div>
          </div>
        </div>
      </div>
      </>
      )}

      {/* Task Creation Modal */}
      {showAddModal && (
        <AddDeadlineModal
          isOpen={showAddModal}
          onClose={() => setShowAddModal(false)}
          onCreated={() => {
            setShowAddModal(false)
            setSavedToast(true)
            setTimeout(() => setSavedToast(false), 3000)
            if (onTasksUpdated) {
              onTasksUpdated()
            }
          }}
          defaultDomain={selectedDomainFilter !== 'all' ? selectedDomainFilter : 'general'}
          tasks={cleanTasks}
          customDomains={customDomains}
          onOpenCompass={onOpenCompass}
        />
      )}

      {/* About & Judges Guide Modal (N-005, N-026, N-027) */}
      <AboutJudgesModal
        isOpen={showAboutModal}
        onClose={() => setShowAboutModal(false)}
        usageStats={usageStats}
        backendStatus={backendStatus}
        isOnline={isOnline}
      />

      {/* Saved Toast Notification (N-033) */}
      {savedToast && (
        <div
          role="status"
          aria-live="polite"
          style={{
            position: 'fixed',
            bottom: '24px',
            right: '24px',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            boxShadow: 'var(--shadow-lg)',
            padding: '10px 16px',
            borderRadius: '8px',
            color: 'var(--text-primary)',
            fontSize: '13px',
            fontWeight: '600',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            zIndex: 1200,
          }}
        >
          <span style={{ color: '#10b981', fontWeight: 'bold' }}>✓</span>
          <span>Deadline saved</span>
        </div>
      )}
    </div>
  )
}
