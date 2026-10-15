import React, { useState, useMemo, useCallback, useEffect } from 'react'
import DarkModeToggle from './DarkModeToggle'
import { getDomainMeta } from './timeline/domainMeta'
import AddDeadlineModal from './timeline/AddDeadlineModal'
import { updateTask } from '../api/client'

/**
 * Robust timezone-safe local date parser.
 * Converts YYYY-MM-DD into a local Date at 23:59:59 so western hemisphere
 * users don't see their due dates shift backward by a full day.
 */
function parseTaskDueDate(dueDateStr) {
  if (!dueDateStr || typeof dueDateStr !== 'string') return null
  const trimmed = dueDateStr.trim()
  if (!trimmed) return null
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
    const [y, m, d] = trimmed.split('-').map(Number)
    if (isNaN(y) || isNaN(m) || isNaN(d)) return null
    return new Date(y, m - 1, d, 23, 59, 59, 999)
  }
  const parsed = new Date(trimmed)
  return isNaN(parsed.getTime()) ? null : parsed
}

/**
 * Classifies deadline urgency with real mathematical time differences.
 */
function classifyDeadline(task, now = new Date()) {
  if (!task || typeof task !== 'object') {
    return { type: 'none', label: 'Active', diffHours: 9999, diffDays: 9999, isUrgent: false, isOverdue: false }
  }

  const status = (task.status || '').toLowerCase()
  const countdown = (task.countdown || '').toLowerCase()
  const isCompleted = status === 'completed' || status === 'done' || countdown === 'completed'
  if (isCompleted) {
    return { type: 'completed', label: 'Completed', diffHours: 9999, diffDays: 9999, isUrgent: false, isOverdue: false }
  }

  const dueDate = parseTaskDueDate(task.due_date)
  const nowMs = now.getTime()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const todayEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999).getTime()

  if (dueDate) {
    const dueMs = dueDate.getTime()
    const diffHours = (dueMs - nowMs) / (1000 * 60 * 60)
    const diffDays = Math.ceil((dueMs - nowMs) / (1000 * 60 * 60 * 24))

    if (dueMs < todayStart) {
      return {
        type: 'overdue',
        label: `⚠️ Overdue (${Math.max(1, Math.abs(diffDays))}d ago)`,
        diffHours,
        diffDays,
        isUrgent: true,
        isOverdue: true,
      }
    }
    if (diffHours <= 1 && diffHours > 0) {
      return {
        type: 'hour',
        label: '🚨 Due in <1h',
        diffHours,
        diffDays: 0,
        isUrgent: true,
        isOverdue: false,
      }
    }
    if (dueMs <= todayEnd || diffHours <= 24) {
      return {
        type: 'today',
        label: '⚠️ Due today',
        diffHours,
        diffDays: 0,
        isUrgent: true,
        isOverdue: false,
      }
    }
    if (diffDays === 1) {
      const dayName = dueDate.toLocaleDateString('en-US', { weekday: 'short' })
      return {
        type: 'tomorrow',
        label: `1d left (${dayName})`,
        diffHours,
        diffDays: 1,
        isUrgent: false,
        isOverdue: false,
      }
    }
    if (diffDays <= 7) {
      const dayName = dueDate.toLocaleDateString('en-US', { weekday: 'short' })
      return {
        type: 'week',
        label: `${diffDays}d left (${dayName})`,
        diffHours,
        diffDays,
        isUrgent: false,
        isOverdue: false,
      }
    }
    return {
      type: 'future',
      label: `${diffDays}d left`,
      diffHours,
      diffDays,
      isUrgent: false,
      isOverdue: false,
    }
  }

  // Fallback to countdown string interpretation
  if (countdown.includes('overdue')) {
    return {
      type: 'overdue',
      label: task.countdown || '⚠️ Overdue',
      diffHours: -1,
      diffDays: -1,
      isUrgent: true,
      isOverdue: true,
    }
  }
  if (countdown.includes('today')) {
    return {
      type: 'today',
      label: task.countdown || '⚠️ Due today',
      diffHours: 8,
      diffDays: 0,
      isUrgent: true,
      isOverdue: false,
    }
  }
  if (countdown.includes('1d')) {
    return {
      type: 'tomorrow',
      label: task.countdown || '1d left',
      diffHours: 24,
      diffDays: 1,
      isUrgent: false,
      isOverdue: false,
    }
  }
  if (countdown.includes('left')) {
    return {
      type: 'week',
      label: task.countdown || 'Soon',
      diffHours: 72,
      diffDays: 3,
      isUrgent: false,
      isOverdue: false,
    }
  }

  return {
    type: 'none',
    label: task.countdown || 'Active',
    diffHours: 9999,
    diffDays: 9999,
    isUrgent: false,
    isOverdue: false,
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
  const [timeFilter, setTimeFilter] = useState('all') // 'all' | 'focus' | 'today' | 'week' | 'overdue' | 'completed'
  const [optimisticOverrides, setOptimisticOverrides] = useState({})
  const [showAddModal, setShowAddModal] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [lastRefreshedAt, setLastRefreshedAt] = useState(() => new Date())

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

  // Apply time / status filter
  const displayedTasks = useMemo(() => {
    if (timeFilter === 'all') return domainFilteredTasks
    const now = new Date()

    if (timeFilter === 'completed') {
      return domainFilteredTasks.filter((t) => {
        const s = (t.status || '').toLowerCase()
        const c = (t.countdown || '').toLowerCase()
        return s === 'completed' || s === 'done' || c === 'completed'
      })
    }

    if (timeFilter === 'overdue') {
      return domainFilteredTasks.filter((t) => {
        const info = classifyDeadline(t, now)
        return info.isOverdue
      })
    }

    if (timeFilter === 'today') {
      return domainFilteredTasks.filter((t) => {
        const info = classifyDeadline(t, now)
        return info.type === 'today' || info.type === 'hour' || info.isOverdue
      })
    }

    if (timeFilter === 'week') {
      return domainFilteredTasks.filter((t) => {
        const info = classifyDeadline(t, now)
        return info.type === 'today' || info.type === 'hour' || info.type === 'tomorrow' || info.type === 'week' || info.isOverdue
      })
    }

    return domainFilteredTasks
  }, [domainFilteredTasks, timeFilter])

  // Metric calculations
  const metrics = useMemo(() => {
    const total = domainFilteredTasks.length
    let completedCount = 0
    let overdueCount = 0
    let completedTodayCount = 0
    const now = new Date()
    const todayStr = now.toDateString()
    const todayShort = now.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toLowerCase()

    domainFilteredTasks.forEach((t) => {
      const s = (t.status || '').toLowerCase()
      const c = (t.countdown || '').toLowerCase()
      const isCompleted = s === 'completed' || s === 'done' || c === 'completed'

      if (isCompleted) {
        completedCount++
        if (t.updated_at) {
          const d = new Date(t.updated_at)
          if (!isNaN(d.getTime()) && d.toDateString() === todayStr) {
            completedTodayCount++
          }
        } else if (t.timestamp) {
          const ts = String(t.timestamp).toLowerCase()
          if (
            ts.includes('just now') ||
            ts.includes('min') ||
            ts.includes('hour') ||
            ts.includes('today') ||
            ts.includes(todayShort)
          ) {
            completedTodayCount++
          }
        }
      } else {
        const info = classifyDeadline(t, now)
        if (info.isOverdue) {
          overdueCount++
        }
      }
    })

    const completionRate = total > 0 ? Math.round((completedCount / total) * 100) : 0

    return {
      total,
      completedCount,
      completionRate,
      overdueCount,
      completedTodayCount,
    }
  }, [domainFilteredTasks])

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
        icon: meta.icon || '🏷️',
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

    const urgentItems = openTasks
      .map((t) => ({ task: t, urgency: classifyDeadline(t, now) }))
      .filter(({ urgency }) => urgency.isOverdue || urgency.type === 'hour' || urgency.type === 'today' || urgency.diffHours <= 24)
      .sort((a, b) => a.urgency.diffHours - b.urgency.diffHours)

    return {
      urgentItems: urgentItems.map((u) => u.task),
      count: urgentItems.length,
      nextItem: urgentItems.length > 0 ? urgentItems[0].task : null,
      nextUrgency: urgentItems.length > 0 ? urgentItems[0].urgency : null,
    }
  }, [domainFilteredTasks])

  // Upcoming Deadlines (Next 5 open tasks due)
  const upcomingDeadlines = useMemo(() => {
    const now = new Date()
    const openTasks = domainFilteredTasks.filter((t) => {
      const s = (t.status || '').toLowerCase()
      const c = (t.countdown || '').toLowerCase()
      return s !== 'completed' && s !== 'done' && c !== 'completed'
    })

    const annotated = openTasks.map((t) => ({
      ...t,
      urgency: classifyDeadline(t, now),
    }))

    annotated.sort((a, b) => a.urgency.diffHours - b.urgency.diffHours)
    return annotated.slice(0, 5)
  }, [domainFilteredTasks])

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

      try {
        await updateTask(taskId, { status: newStatus })
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
            background: 'rgba(245, 158, 11, 0.1)',
            border: '1px solid rgba(245, 158, 11, 0.3)',
            borderRadius: '10px',
            marginBottom: '18px',
            fontSize: '12.5px',
            color: '#fbbf24',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '15px' }}>⚡</span>
            <span>
              <strong>Demo / Offline Mode:</strong> Backend server is connecting. Displaying cached demo tasks. Your changes will sync once connected.
            </span>
          </div>
          <button
            type="button"
            onClick={handleManualRefresh}
            style={{
              background: 'rgba(245, 158, 11, 0.2)',
              border: 'none',
              color: '#fbbf24',
              padding: '4px 10px',
              borderRadius: '6px',
              fontWeight: '700',
              fontSize: '11px',
              cursor: 'pointer',
            }}
          >
            Retry Sync
          </button>
        </div>
      )}

      {/* Page Header */}
      <div style={{ marginBottom: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <h2
                style={{
                  fontSize: '22px',
                  fontWeight: '800',
                  color: 'var(--text-primary)',
                  letterSpacing: '-0.4px',
                  margin: 0,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  flexWrap: 'wrap',
                }}
              >
                <span>📊</span>
                <span>Dashboard</span>
                <span className="serif-accent" style={{ color: 'var(--text-secondary)', fontWeight: '600', fontSize: '16px' }}>
                  — {today}
                </span>
              </h2>
            </div>
            <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginTop: '4px', marginBottom: 0 }}>
              Live workspace telemetry, task distribution, upcoming deadlines, and system telemetry
            </p>
          </div>

          {/* Header Action Buttons & Dark Mode Toggle */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <button
              type="button"
              id="dashboard-btn-new-task"
              onClick={() => setShowAddModal(true)}
              className="btn-touch-target"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 12px',
                borderRadius: '8px',
                background: 'var(--brand)',
                color: '#1a162b',
                fontWeight: '700',
                fontSize: '12.5px',
                border: 'none',
                cursor: 'pointer',
                transition: 'opacity 0.15s ease',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.9')}
              onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
              aria-label="Add new task or deadline"
            >
              <span>+</span>
              <span>New Deadline</span>
            </button>

            {onSelectTab && (
              <>
                <button
                  type="button"
                  id="dashboard-btn-open-schedule"
                  onClick={() => onSelectTab('calendar')}
                  className="btn-touch-target"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 12px',
                    borderRadius: '8px',
                    background: 'var(--bg-card)',
                    color: 'var(--text-primary)',
                    fontWeight: '600',
                    fontSize: '12.5px',
                    border: '1px solid var(--border)',
                    cursor: 'pointer',
                  }}
                  title="Open Schedule & Google Calendar sync"
                >
                  <span>🗓️</span>
                  <span>Schedule</span>
                </button>

                <button
                  type="button"
                  id="dashboard-btn-open-compass"
                  onClick={() => onSelectTab('compass')}
                  className="btn-touch-target"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 12px',
                    borderRadius: '8px',
                    background: 'var(--bg-card)',
                    color: 'var(--text-primary)',
                    fontWeight: '600',
                    fontSize: '12.5px',
                    border: '1px solid var(--border)',
                    cursor: 'pointer',
                  }}
                  title="Open Compass AI Assistant & Planner"
                >
                  <span>🧭</span>
                  <span>Compass</span>
                </button>
              </>
            )}

            <button
              type="button"
              id="dashboard-btn-refresh"
              onClick={handleManualRefresh}
              className="btn-touch-target"
              aria-label="Refresh dashboard data"
              title={`Last synced: ${timeSinceUpdate}`}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px',
                padding: '6px 10px',
                borderRadius: '8px',
                background: 'var(--bg-card)',
                color: 'var(--text-secondary)',
                fontWeight: '600',
                fontSize: '12px',
                border: '1px solid var(--border)',
                cursor: 'pointer',
              }}
            >
              <span
                style={{
                  display: 'inline-block',
                  animation: isRefreshing ? 'spin 0.6s linear infinite' : 'none',
                  fontSize: '14px',
                }}
              >
                🔄
              </span>
              <span style={{ fontSize: '11px', opacity: 0.8 }}>{timeSinceUpdate}</span>
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

      {/* SECTION: Today's Focus Card */}
      <div className="dashboard-focus-card" role="region" aria-label="Today's focus area">
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0, flex: 1 }}>
          <div
            style={{
              width: '40px',
              height: '40px',
              borderRadius: '10px',
              background: todayFocus.count > 0 ? 'rgba(239, 68, 68, 0.12)' : 'rgba(16, 185, 129, 0.12)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '20px',
              flexShrink: 0,
            }}
          >
            {todayFocus.count > 0 ? '🎯' : '🎉'}
          </div>

          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '14px', fontWeight: '800', color: 'var(--text-primary)' }}>
                {todayFocus.count > 0
                  ? `${todayFocus.count} ${todayFocus.count === 1 ? 'task needs' : 'tasks need'} attention today`
                  : "You're all caught up for today!"}
              </span>
              {todayFocus.nextUrgency && (
                <span
                  style={{
                    fontSize: '11px',
                    fontWeight: '700',
                    padding: '2px 8px',
                    borderRadius: '12px',
                    background: todayFocus.nextUrgency.isOverdue
                      ? 'var(--danger-bg)'
                      : 'rgba(245, 158, 11, 0.15)',
                    color: todayFocus.nextUrgency.isOverdue ? '#ef4444' : 'var(--brand)',
                  }}
                >
                  {todayFocus.nextUrgency.label}
                </span>
              )}
            </div>

            <div
              style={{
                fontSize: '12.5px',
                color: 'var(--text-secondary)',
                marginTop: '2px',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
              title={todayFocus.nextItem ? todayFocus.nextItem.title : ''}
            >
              {todayFocus.nextItem ? (
                <>
                  Next up: <strong>{todayFocus.nextItem.title}</strong>{' '}
                  <span style={{ color: 'var(--text-muted)' }}>({todayFocus.nextItem.project || todayFocus.nextItem.domain})</span>
                </>
              ) : (
                'Enjoy your focused time or plan your upcoming schedule with Compass.'
              )}
            </div>
          </div>
        </div>

        {/* Focus Actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
          {todayFocus.nextItem && (
            <button
              type="button"
              className="btn-touch-target"
              onClick={() => handleToggleTaskStatus(todayFocus.nextItem.id, false)}
              style={{
                background: 'var(--bg-card-soft)',
                border: '1px solid var(--border)',
                color: 'var(--code)',
                fontWeight: '700',
                fontSize: '12px',
                padding: '6px 12px',
                borderRadius: '8px',
                cursor: 'pointer',
              }}
              title="Mark this focus task as completed"
            >
              ✓ Complete
            </button>
          )}

          {onOpenCompass && (
            <button
              type="button"
              className="btn-touch-target"
              onClick={() => {
                const prompt =
                  todayFocus.count > 0
                    ? `I have ${todayFocus.count} tasks needing attention today. Please analyze my deadlines and suggest an optimal step-by-step roadmap for today.`
                    : 'Please review my upcoming tasks and projects and propose a focus schedule for this week.'
                onOpenCompass(prompt)
              }}
              style={{
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                color: 'var(--brand)',
                fontWeight: '700',
                fontSize: '12px',
                padding: '6px 12px',
                borderRadius: '8px',
                cursor: 'pointer',
              }}
            >
              🧭 Ask Compass to Plan
            </button>
          )}
        </div>
      </div>

      {/* DOMAIN FILTER BAR */}
      <div className="dashboard-filter-bar" role="tablist" aria-label="Filter dashboard by context domain">
        <button
          type="button"
          onClick={() => setSelectedDomainFilter('all')}
          className={`dashboard-filter-pill ${selectedDomainFilter === 'all' ? 'active' : ''}`}
          role="tab"
          aria-selected={selectedDomainFilter === 'all'}
        >
          <span>▦</span>
          <span>All Domains ({cleanTasks.length})</span>
        </button>

        {domainBreakdown.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setSelectedDomainFilter(item.key)}
            className={`dashboard-filter-pill ${selectedDomainFilter === item.key ? 'active' : ''}`}
            role="tab"
            aria-selected={selectedDomainFilter === item.key}
            style={
              selectedDomainFilter === item.key
                ? { background: item.color, color: '#1a162b', borderColor: item.color }
                : undefined
            }
          >
            <span>{item.icon}</span>
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
              color: 'var(--brand)',
              fontSize: '11.5px',
              fontWeight: '700',
              cursor: 'pointer',
              padding: '4px 8px',
            }}
          >
            Reset filter ✕
          </button>
        )}
      </div>

      {/* SECTION 1: Quick Stat Cards (Interactive Filtering) */}
      <div className="dashboard-stat-grid" role="region" aria-label="Quick statistics">
        {/* Total Tasks */}
        <div
          className={`dashboard-stat-card ${timeFilter === 'all' ? 'active-filter' : ''}`}
          onClick={() => setTimeFilter('all')}
          tabIndex={0}
          role="button"
          aria-pressed={timeFilter === 'all'}
          aria-label={`Total tasks: ${metrics.total}. Click to show all tasks.`}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              setTimeFilter('all')
            }
          }}
          title="Click to view all tasks"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '11px', fontWeight: '700', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Total Tasks
            </span>
            <span style={{ fontSize: '18px' }}>📋</span>
          </div>
          <div style={{ fontSize: '28px', fontWeight: '800', color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            {metrics.total}
          </div>
          <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '4px' }}>
            {selectedDomainFilter === 'all' ? 'Across all domains' : `In ${selectedDomainFilter}`}
          </div>
        </div>

        {/* Completion Rate */}
        <div
          className={`dashboard-stat-card ${timeFilter === 'completed' ? 'active-filter' : ''}`}
          onClick={() => setTimeFilter((prev) => (prev === 'completed' ? 'all' : 'completed'))}
          tabIndex={0}
          role="button"
          aria-pressed={timeFilter === 'completed'}
          aria-label={`Completion rate: ${metrics.completionRate} percent. Click to filter completed tasks.`}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              setTimeFilter((prev) => (prev === 'completed' ? 'all' : 'completed'))
            }
          }}
          title="Click to filter completed tasks"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '11px', fontWeight: '700', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Completion Rate
            </span>
            <span style={{ fontSize: '18px' }}>📈</span>
          </div>
          <div style={{ fontSize: '28px', fontWeight: '800', color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            {metrics.completionRate}%
          </div>
          <div style={{ width: '100%', height: '6px', background: 'var(--border-soft)', borderRadius: '3px', marginTop: '8px', overflow: 'hidden' }}>
            <div
              style={{
                width: `${metrics.completionRate}%`,
                height: '100%',
                background: 'var(--code)',
                borderRadius: '3px',
                transition: 'width 0.3s ease',
              }}
            />
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '6px' }}>
            {metrics.completedCount} of {metrics.total} tasks completed
          </div>
        </div>

        {/* Overdue Tasks */}
        <div
          className={`dashboard-stat-card ${timeFilter === 'overdue' ? 'active-filter' : ''}`}
          onClick={() => setTimeFilter((prev) => (prev === 'overdue' ? 'all' : 'overdue'))}
          tabIndex={0}
          role="button"
          aria-pressed={timeFilter === 'overdue'}
          aria-label={`Overdue tasks: ${metrics.overdueCount}. Click to filter overdue tasks.`}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              setTimeFilter((prev) => (prev === 'overdue' ? 'all' : 'overdue'))
            }
          }}
          title="Click to filter overdue tasks"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '11px', fontWeight: '700', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Overdue
            </span>
            <span style={{ fontSize: '18px' }}>⚠️</span>
          </div>
          <div
            style={{
              fontSize: '28px',
              fontWeight: '800',
              color: metrics.overdueCount > 0 ? '#ef4444' : 'var(--text-primary)',
              letterSpacing: '-0.5px',
            }}
          >
            {metrics.overdueCount}
          </div>
          <div style={{ fontSize: '11.5px', color: metrics.overdueCount > 0 ? '#ef4444' : 'var(--text-muted)', marginTop: '4px' }}>
            {metrics.overdueCount > 0 ? 'Requires attention' : 'No overdue items'}
          </div>
        </div>

        {/* Completed Today */}
        <div
          className={`dashboard-stat-card ${timeFilter === 'today' ? 'active-filter' : ''}`}
          onClick={() => setTimeFilter((prev) => (prev === 'today' ? 'all' : 'today'))}
          tabIndex={0}
          role="button"
          aria-pressed={timeFilter === 'today'}
          aria-label={`Completed today: ${metrics.completedTodayCount}. Click to filter today's tasks.`}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              setTimeFilter((prev) => (prev === 'today' ? 'all' : 'today'))
            }
          }}
          title="Click to filter today's tasks"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '11px', fontWeight: '700', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Completed Today
            </span>
            <span style={{ fontSize: '18px' }}>✅</span>
          </div>
          <div style={{ fontSize: '28px', fontWeight: '800', color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            {metrics.completedTodayCount}
          </div>
          <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Checked off today
          </div>
        </div>
      </div>

      {/* SECTION 2 & 3: Main Two-Column Row */}
      <div className="dashboard-main-grid">
        {/* Tasks by Domain */}
        <div className="dashboard-section-card" role="region" aria-label="Tasks distributed by domain">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: '800', color: 'var(--text-primary)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span>🏷️</span>
              <span>Tasks by Domain</span>
            </h3>
            {onSelectTab && (
              <button
                type="button"
                onClick={() => {
                  if (onSelectDomain && selectedDomainFilter !== 'all') {
                    onSelectDomain(selectedDomainFilter)
                  }
                  onSelectTab('timeline')
                }}
                className="btn-touch-target"
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--brand)',
                  fontSize: '12px',
                  fontWeight: '700',
                  cursor: 'pointer',
                  padding: '4px 8px',
                }}
              >
                Timeline view →
              </button>
            )}
          </div>

          {cleanTasks.length === 0 ? (
            <div className="dashboard-empty-state">
              <span style={{ fontSize: '28px', marginBottom: '8px' }}>📭</span>
              <p style={{ margin: 0, fontSize: '13.5px', fontWeight: '700', color: 'var(--text-primary)' }}>
                No tasks tracked yet
              </p>
              <p style={{ margin: '4px 0 14px 0', fontSize: '12px', color: 'var(--text-muted)', maxWidth: '300px' }}>
                Create your first deadline or ask Compass Assistant to synthesize your workload.
              </p>
              <button
                type="button"
                onClick={() => setShowAddModal(true)}
                style={{
                  background: 'var(--brand)',
                  border: 'none',
                  color: '#1a162b',
                  padding: '8px 16px',
                  borderRadius: '8px',
                  fontWeight: '700',
                  fontSize: '12.5px',
                  cursor: 'pointer',
                }}
              >
                + Create First Task
              </button>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {domainBreakdown.map((item) => (
                <div
                  key={item.key}
                  tabIndex={0}
                  role="button"
                  aria-label={`${item.label}: ${item.count} tasks, ${item.pct} percent. Click to filter.`}
                  style={{
                    padding: '10px 12px',
                    borderRadius: '10px',
                    background: selectedDomainFilter === item.key ? 'var(--bg-card-soft)' : 'var(--bg-card-soft)',
                    border: selectedDomainFilter === item.key ? `1.5px solid ${item.color}` : '1px solid var(--border)',
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
                      <span style={{ fontSize: '15px' }}>{item.icon}</span>
                      <span style={{ fontSize: '13.5px', fontWeight: '700', color: 'var(--text-primary)' }}>
                        {item.label}
                      </span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontSize: '12px', fontWeight: '700', color: 'var(--text-secondary)' }}>
                        {item.count} {item.count === 1 ? 'task' : 'tasks'}
                      </span>
                      <span style={{ fontSize: '11px', color: 'var(--text-muted)', minWidth: '34px', textAlign: 'right' }}>
                        {item.pct}%
                      </span>
                    </div>
                  </div>
                  <div style={{ width: '100%', height: '6px', background: 'var(--border-soft)', borderRadius: '3px', overflow: 'hidden' }}>
                    <div
                      style={{
                        width: `${item.pct}%`,
                        height: '100%',
                        background: item.color,
                        borderRadius: '3px',
                        transition: 'width 0.3s ease',
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Upcoming Deadlines */}
        <div className="dashboard-section-card" role="region" aria-label="Upcoming deadlines list">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: '800', color: 'var(--text-primary)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span>⏰</span>
              <span>Upcoming Deadlines</span>
            </h3>
            {onSelectTab && (
              <button
                type="button"
                onClick={() => onSelectTab('timeline')}
                className="btn-touch-target"
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--brand)',
                  fontSize: '12px',
                  fontWeight: '700',
                  cursor: 'pointer',
                  padding: '4px 8px',
                }}
              >
                View all ({upcomingDeadlines.length}) →
              </button>
            )}
          </div>

          {upcomingDeadlines.length === 0 ? (
            <div className="dashboard-empty-state">
              <span style={{ fontSize: '28px', marginBottom: '8px' }}>🎉</span>
              <p style={{ margin: 0, fontSize: '13.5px', fontWeight: '700', color: 'var(--text-primary)' }}>
                No pending deadlines
              </p>
              <p style={{ margin: '4px 0 14px 0', fontSize: '12px', color: 'var(--text-muted)', maxWidth: '300px' }}>
                You have cleared all scheduled deadlines! Take a breather or log a new milestone.
              </p>
              <button
                type="button"
                onClick={() => setShowAddModal(true)}
                style={{
                  background: 'var(--brand)',
                  border: 'none',
                  color: '#1a162b',
                  padding: '8px 16px',
                  borderRadius: '8px',
                  fontWeight: '700',
                  fontSize: '12.5px',
                  cursor: 'pointer',
                }}
              >
                + Add Deadline
              </button>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {upcomingDeadlines.map((task) => {
                const meta = getDomainMeta(task.domain)
                const isOverdue = task.urgency?.isOverdue
                const isUrgent = task.urgency?.isUrgent

                return (
                  <div
                    key={task.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: '12px',
                      padding: '10px 12px',
                      borderRadius: '10px',
                      background: 'var(--bg-card-soft)',
                      border: isOverdue
                        ? '1px solid rgba(239, 68, 68, 0.4)'
                        : isUrgent
                        ? '1px solid rgba(245, 158, 11, 0.4)'
                        : '1px solid var(--border)',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    {/* Inline Completion Checkbox */}
                    <button
                      type="button"
                      onClick={() => handleToggleTaskStatus(task.id, false)}
                      className="btn-touch-target"
                      style={{
                        width: '26px',
                        height: '26px',
                        minWidth: '26px',
                        minHeight: '26px',
                        borderRadius: '50%',
                        border: '1.5px solid var(--border)',
                        background: 'var(--bg-card)',
                        color: 'var(--text-muted)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        fontSize: '12px',
                        flexShrink: 0,
                        transition: 'all 0.15s ease',
                      }}
                      title="Mark as completed"
                      aria-label={`Mark task ${task.title} as completed`}
                    >
                      ✓
                    </button>

                    <div
                      style={{ minWidth: 0, flex: 1, cursor: onSelectTab ? 'pointer' : 'default' }}
                      onClick={() => {
                        if (onSelectTab) onSelectTab('timeline')
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }}>
                        <span style={{ fontSize: '12px' }}>{meta.icon}</span>
                        <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>
                          {task.project || meta.label}
                        </span>
                      </div>
                      <div
                        style={{
                          fontSize: '13px',
                          fontWeight: '700',
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
                          background: isOverdue
                            ? 'var(--danger-bg)'
                            : isUrgent
                            ? 'rgba(245, 158, 11, 0.15)'
                            : 'var(--bg-card)',
                          color: isOverdue
                            ? '#ef4444'
                            : isUrgent
                            ? 'var(--brand)'
                            : 'var(--text-secondary)',
                          border: isOverdue
                            ? '1px solid rgba(239, 68, 68, 0.3)'
                            : isUrgent
                            ? '1px solid rgba(245, 158, 11, 0.3)'
                            : '1px solid var(--border)',
                          padding: '4px 8px',
                          borderRadius: '6px',
                          fontSize: '11px',
                          fontWeight: '700',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {task.urgency?.label || task.countdown || 'Active'}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* SECTION 4 & 5: Recent Activity & System Status */}
      <div className="dashboard-main-grid">
        {/* Recent Activity */}
        <div className="dashboard-section-card" role="region" aria-label="Recent activity feed">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: '800', color: 'var(--text-primary)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span>⚡</span>
              <span>Recent Activity</span>
            </h3>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: '600' }}>
              Latest milestones
            </span>
          </div>

          {recentActivity.length === 0 ? (
            <div className="dashboard-empty-state">
              <span style={{ fontSize: '28px', marginBottom: '8px' }}>📜</span>
              <p style={{ margin: 0, fontSize: '13.5px', fontWeight: '700', color: 'var(--text-primary)' }}>
                No activity to display
              </p>
              <p style={{ margin: '4px 0 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
                Completed and created tasks will appear here.
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {recentActivity.map((task) => {
                const meta = getDomainMeta(task.domain)
                const isCompleted =
                  (task.status || '').toLowerCase() === 'completed' ||
                  (task.status || '').toLowerCase() === 'done' ||
                  (task.countdown || '').toLowerCase() === 'completed'

                return (
                  <div
                    key={task.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: '12px',
                      padding: '10px 12px',
                      borderRadius: '10px',
                      background: 'var(--bg-card-soft)',
                      border: '1px solid var(--border)',
                      opacity: isCompleted ? 0.85 : 1,
                    }}
                  >
                    {/* Toggle button */}
                    <button
                      type="button"
                      onClick={() => handleToggleTaskStatus(task.id, isCompleted)}
                      className="btn-touch-target"
                      style={{
                        width: '26px',
                        height: '26px',
                        minWidth: '26px',
                        minHeight: '26px',
                        borderRadius: '50%',
                        border: isCompleted ? '1.5px solid #10b981' : '1.5px solid var(--border)',
                        background: isCompleted ? '#10b981' : 'var(--bg-card)',
                        color: isCompleted ? '#ffffff' : 'var(--text-muted)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        fontSize: '12px',
                        flexShrink: 0,
                        transition: 'all 0.15s ease',
                      }}
                      title={isCompleted ? 'Mark as open' : 'Mark as completed'}
                      aria-label={`Toggle task completion for ${task.title}`}
                    >
                      ✓
                    </button>

                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px', flexWrap: 'wrap' }}>
                        <span
                          className={`badge-${task.domain || 'general'}`}
                          style={{
                            fontSize: '10.5px',
                            padding: '2px 8px',
                            borderRadius: '12px',
                            fontWeight: '700',
                            background: 'rgba(255, 255, 255, 0.06)',
                            color: meta.color,
                            border: `1px solid ${meta.border || 'rgba(255, 255, 255, 0.1)'}`,
                          }}
                        >
                          {meta.icon} {meta.label}
                        </span>
                        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                          {task.timestamp || 'Recently'}
                        </span>
                      </div>
                      <div
                        style={{
                          fontSize: '13px',
                          fontWeight: '600',
                          color: isCompleted ? 'var(--text-muted)' : 'var(--text-primary)',
                          textDecoration: isCompleted ? 'line-through' : 'none',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}
                        title={task.title}
                      >
                        {task.title || 'Untitled task'}
                      </div>
                    </div>

                    <div style={{ flexShrink: 0 }}>
                      <span
                        style={{
                          fontSize: '11px',
                          fontWeight: '700',
                          padding: '3px 8px',
                          borderRadius: '6px',
                          background: isCompleted ? 'rgba(16, 185, 129, 0.15)' : 'var(--bg-card)',
                          color: isCompleted ? 'var(--code)' : 'var(--text-secondary)',
                          border: `1px solid ${isCompleted ? 'rgba(16, 185, 129, 0.3)' : 'var(--border)'}`,
                        }}
                      >
                        {isCompleted ? '✓ Done' : 'Open'}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* System & Telemetry Status */}
        <div className="dashboard-section-card" role="region" aria-label="System connectivity and model telemetry">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: '800', color: 'var(--text-primary)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span>🖥️</span>
              <span>System & Telemetry</span>
            </h3>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: '11.5px',
                fontWeight: '700',
                padding: '3px 8px',
                borderRadius: '12px',
                background: isOnline ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                color: isOnline ? 'var(--code)' : 'var(--brand)',
                border: `1px solid ${isOnline ? 'rgba(16, 185, 129, 0.3)' : 'rgba(245, 158, 11, 0.3)'}`,
              }}
            >
              <span
                style={{
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  background: isOnline ? '#10b981' : '#f5a623',
                }}
              />
              {isOnline ? 'System Online' : 'Connecting'}
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {/* Backend Database Status */}
            <div
              style={{
                padding: '10px 12px',
                borderRadius: '10px',
                background: 'var(--bg-card-soft)',
                border: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600', textTransform: 'uppercase' }}>
                  Backend Database
                </div>
                <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary)', marginTop: '2px' }}>
                  {backendStatus || 'Online'}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '1px' }}>
                  PostgreSQL 16 · pgvector HNSW
                </div>
              </div>
              <span style={{ fontSize: '18px' }}>🗄️</span>
            </div>

            {/* Workspace & Google Calendar Connection */}
            <div
              style={{
                padding: '10px 12px',
                borderRadius: '10px',
                background: 'var(--bg-card-soft)',
                border: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600', textTransform: 'uppercase' }}>
                  Workspace & Calendar
                </div>
                <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary)', marginTop: '2px' }}>
                  {currentUser?.calendar?.connected
                    ? `Google Calendar (${currentUser.calendar.mode === 'live' ? 'Live' : 'Demo'})`
                    : 'Local Sandbox Workspace'}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '1px' }}>
                  {currentUser?.email || 'Anonymous Guest Session'}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                {onOpenAuth && (
                  <button
                    type="button"
                    onClick={onOpenAuth}
                    className="btn-touch-target"
                    style={{
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      color: 'var(--text-primary)',
                      fontSize: '11.5px',
                      fontWeight: '600',
                      padding: '4px 8px',
                      borderRadius: '6px',
                      cursor: 'pointer',
                    }}
                  >
                    {currentUser?.authenticated ? 'Account' : 'Sign in'}
                  </button>
                )}
                <span style={{ fontSize: '18px' }}>🗓️</span>
              </div>
            </div>

            {/* API Usage & Cost */}
            <div
              style={{
                padding: '10px 12px',
                borderRadius: '10px',
                background: 'var(--bg-card-soft)',
                border: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600', textTransform: 'uppercase' }}>
                  Nebius API Telemetry
                </div>
                <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary)', marginTop: '2px' }}>
                  {usageStats?.total_requests ?? 0} calls ·{' '}
                  {usageStats?.total_estimated_cost_usd !== undefined
                    ? `$${Number(usageStats.total_estimated_cost_usd).toFixed(5)}`
                    : '$0.00000'}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '1px' }}>
                  Nebius Token Factory · Nemotron-3 MoE
                </div>
              </div>
              <span style={{ fontSize: '18px' }}>⚡</span>
            </div>
          </div>
        </div>
      </div>

      {/* Task Creation Modal */}
      {showAddModal && (
        <AddDeadlineModal
          isOpen={showAddModal}
          onClose={() => setShowAddModal(false)}
          onCreated={() => {
            setShowAddModal(false)
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
    </div>
  )
}
