import React, { useMemo } from 'react'
import DarkModeToggle from './DarkModeToggle'
import { getDomainMeta } from './timeline/domainMeta'

export default function Dashboard({
  tasks = [],
  backendStatus = 'Waking up the server…',
  usageStats = null,
  currentUser = null,
  onSelectTab,
  onSelectDomain,
  isDarkMode = false,
  onToggleDarkMode,
}) {
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

  // ---------------------------------------------------------------------------
  // Metric Calculations from Real Task Data
  // ---------------------------------------------------------------------------
  const metrics = useMemo(() => {
    const total = tasks.length

    const isCompleted = (t) => {
      const status = (t.status || '').toLowerCase()
      const countdown = (t.countdown || '').toLowerCase()
      return status === 'completed' || status === 'done' || countdown === 'completed'
    }

    const completed = tasks.filter(isCompleted)
    const completionRate = total > 0 ? Math.round((completed.length / total) * 100) : 0

    const now = new Date()
    const todayMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate())

    const overdue = tasks.filter((t) => {
      if (isCompleted(t)) return false
      const countdown = (t.countdown || '').toLowerCase()
      if (countdown.includes('overdue')) return true
      if (t.due_date) {
        const due = new Date(t.due_date + 'T23:59:59')
        return !isNaN(due.getTime()) && due < todayMidnight
      }
      return false
    })

    const todayShort = now
      .toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      .toLowerCase()

    const completedToday = completed.filter((t) => {
      if (t.updated_at) {
        const d = new Date(t.updated_at)
        if (!isNaN(d.getTime()) && d.toDateString() === now.toDateString()) {
          return true
        }
      }
      if (t.timestamp) {
        const ts = String(t.timestamp).toLowerCase()
        if (ts.includes('just now') || ts.includes('min') || ts.includes('hour') || ts.includes('today')) {
          return true
        }
        if (ts.includes(todayShort)) {
          return true
        }
      }
      return false
    })

    return {
      total,
      completionRate,
      overdueCount: overdue.length,
      completedTodayCount: completedToday.length,
    }
  }, [tasks])

  // ---------------------------------------------------------------------------
  // Tasks by Domain
  // ---------------------------------------------------------------------------
  const domainBreakdown = useMemo(() => {
    const baseKeys = ['hackathon', 'coursework', 'code', 'general', 'other']
    const discoveredKeys = new Set(baseKeys)

    tasks.forEach((t) => {
      if (t.domain) {
        discoveredKeys.add(t.domain.toLowerCase().trim())
      }
    })

    const counts = {}
    discoveredKeys.forEach((k) => {
      counts[k] = 0
    })

    tasks.forEach((t) => {
      const d = (t.domain || 'general').toLowerCase().trim()
      counts[d] = (counts[d] || 0) + 1
    })

    const list = Array.from(discoveredKeys).map((key) => {
      const meta = getDomainMeta(key)
      const count = counts[key] || 0
      const pct = metrics.total > 0 ? Math.round((count / metrics.total) * 100) : 0
      return {
        key,
        label: meta.label,
        icon: meta.icon,
        color: meta.color,
        count,
        pct,
      }
    })

    // Sort by count descending, keeping zero-counts at the bottom
    list.sort((a, b) => b.count - a.count)
    return list
  }, [tasks, metrics.total])

  // ---------------------------------------------------------------------------
  // Upcoming Deadlines (Next 5 Open Tasks Due)
  // ---------------------------------------------------------------------------
  const upcomingDeadlines = useMemo(() => {
    const isCompleted = (t) => {
      const status = (t.status || '').toLowerCase()
      const countdown = (t.countdown || '').toLowerCase()
      return status === 'completed' || status === 'done' || countdown === 'completed'
    }

    const openTasks = tasks.filter((t) => !isCompleted(t))
    const now = Date.now()

    const parseDiffHours = (t) => {
      if (t.due_date) {
        const d = new Date(t.due_date + 'T23:59:59')
        if (!isNaN(d.getTime())) {
          return (d.getTime() - now) / (1000 * 60 * 60)
        }
      }
      const c = (t.countdown || '').toLowerCase()
      if (c.includes('overdue')) return -1
      if (c.includes('today')) return 8
      if (c.includes('1d')) return 24
      if (c.includes('2d')) return 48
      if (c.includes('3d')) return 72
      return 999
    }

    const withDiff = openTasks.map((t) => {
      const diffHours = parseDiffHours(t)
      const isUrgent = diffHours <= 24
      return {
        ...t,
        diffHours,
        isUrgent,
      }
    })

    withDiff.sort((a, b) => a.diffHours - b.diffHours)
    return withDiff.slice(0, 5)
  }, [tasks])

  // ---------------------------------------------------------------------------
  // Recent Activity (Latest Tasks)
  // ---------------------------------------------------------------------------
  const recentActivity = useMemo(() => {
    return tasks.slice(0, 5)
  }, [tasks])

  return (
    <div className="dashboard-container" style={{ background: 'var(--bg-app)' }}>
      {/* Page Header */}
      <div style={{ marginBottom: '24px' }}>
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
              Live workspace telemetry, task distribution, upcoming deadlines, and system status
            </p>
          </div>

          <div style={{ flexShrink: 0 }}>
            <DarkModeToggle
              isDarkMode={Boolean(isDarkMode)}
              onToggleDarkMode={onToggleDarkMode}
              id="dashboard-theme-toggle"
            />
          </div>
        </div>
      </div>

      {/* SECTION 1: Quick Stat Cards */}
      <div className="dashboard-stat-grid">
        {/* Total Tasks */}
        <div className="dashboard-stat-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: '700', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Total Tasks
            </span>
            <span style={{ fontSize: '18px' }}>📋</span>
          </div>
          <div style={{ fontSize: '28px', fontWeight: '800', color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            {metrics.total}
          </div>
          <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Across all context domains
          </div>
        </div>

        {/* Completion Rate */}
        <div className="dashboard-stat-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: '700', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
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
        </div>

        {/* Overdue Tasks */}
        <div className="dashboard-stat-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: '700', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
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
        <div className="dashboard-stat-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: '700', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Completed Today
            </span>
            <span style={{ fontSize: '18px' }}>✅</span>
          </div>
          <div style={{ fontSize: '28px', fontWeight: '800', color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            {metrics.completedTodayCount}
          </div>
          <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Tasks checked off today
          </div>
        </div>
      </div>

      {/* SECTION 2 & 3: Main Two-Column Row */}
      <div className="dashboard-main-grid">
        {/* Tasks by Domain */}
        <div className="dashboard-section-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: '800', color: 'var(--text-primary)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span>🏷️</span>
              <span>Tasks by Domain</span>
            </h3>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: '600' }}>
              {domainBreakdown.filter((d) => d.count > 0).length} active
            </span>
          </div>

          {metrics.total === 0 ? (
            <div className="dashboard-empty-state">
              <span style={{ fontSize: '24px', marginBottom: '8px' }}>📭</span>
              <p style={{ margin: 0, fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>
                No tasks tracked yet
              </p>
              <p style={{ margin: '4px 0 0 0', fontSize: '11.5px', color: 'var(--text-muted)' }}>
                Create a task in Timeline or ask Compass to build your schedule.
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {domainBreakdown.map((item) => (
                <div
                  key={item.key}
                  style={{
                    padding: '8px 10px',
                    borderRadius: '8px',
                    background: 'var(--bg-card-soft)',
                    border: '1px solid var(--border)',
                    cursor: onSelectDomain ? 'pointer' : 'default',
                    transition: 'all 0.15s ease',
                  }}
                  onClick={() => {
                    if (onSelectDomain && onSelectTab) {
                      onSelectDomain(item.key)
                      onSelectTab('timeline')
                    }
                  }}
                  title={`View ${item.label} tasks`}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span style={{ fontSize: '14px' }}>{item.icon}</span>
                      <span style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary)' }}>
                        {item.label}
                      </span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontSize: '12px', fontWeight: '700', color: 'var(--text-secondary)' }}>
                        {item.count} {item.count === 1 ? 'task' : 'tasks'}
                      </span>
                      <span style={{ fontSize: '11px', color: 'var(--text-muted)', minWidth: '32px', textAlign: 'right' }}>
                        {item.pct}%
                      </span>
                    </div>
                  </div>
                  <div style={{ width: '100%', height: '6px', background: 'var(--border-soft)', borderRadius: '3px', overflow: 'hidden' }}>
                    <div
                      style={{
                        width: `${item.pct}%`,
                        height: '100%',
                        background: item.color || 'var(--brand)',
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
        <div className="dashboard-section-card">
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
                  borderRadius: '6px',
                }}
              >
                View all →
              </button>
            )}
          </div>

          {upcomingDeadlines.length === 0 ? (
            <div className="dashboard-empty-state">
              <span style={{ fontSize: '24px', marginBottom: '8px' }}>🎉</span>
              <p style={{ margin: 0, fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>
                No upcoming deadlines
              </p>
              <p style={{ margin: '4px 0 0 0', fontSize: '11.5px', color: 'var(--text-muted)' }}>
                You are all caught up! Enjoy your focused time.
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {upcomingDeadlines.map((task) => {
                const meta = getDomainMeta(task.domain)
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
                      border: task.isUrgent ? '1px solid rgba(239, 68, 68, 0.4)' : '1px solid var(--border)',
                      cursor: onSelectTab ? 'pointer' : 'default',
                      transition: 'all 0.15s ease',
                    }}
                    onClick={() => {
                      if (onSelectTab) onSelectTab('timeline')
                    }}
                  >
                    <div style={{ minWidth: 0, flex: 1 }}>
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
                      >
                        {task.title}
                      </div>
                    </div>

                    <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: '6px' }}>
                      {task.isUrgent ? (
                        <span
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px',
                            background: 'var(--danger-bg)',
                            color: '#ef4444',
                            border: '1px solid rgba(239, 68, 68, 0.3)',
                            padding: '4px 8px',
                            borderRadius: '6px',
                            fontSize: '11px',
                            fontWeight: '700',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          ⚠️ Due &lt;24h
                        </span>
                      ) : (
                        <span
                          style={{
                            background: 'rgba(251, 191, 36, 0.12)',
                            color: 'var(--brand)',
                            border: '1px solid rgba(251, 191, 36, 0.3)',
                            padding: '4px 8px',
                            borderRadius: '6px',
                            fontSize: '11px',
                            fontWeight: '600',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {task.countdown || 'Active'}
                        </span>
                      )}
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
        <div className="dashboard-section-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: '800', color: 'var(--text-primary)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span>⚡</span>
              <span>Recent Activity</span>
            </h3>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: '600' }}>
              Latest updates
            </span>
          </div>

          {recentActivity.length === 0 ? (
            <div className="dashboard-empty-state">
              <span style={{ fontSize: '24px', marginBottom: '8px' }}>📜</span>
              <p style={{ margin: 0, fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>
                No recent activity
              </p>
              <p style={{ margin: '4px 0 0 0', fontSize: '11.5px', color: 'var(--text-muted)' }}>
                Created and updated tasks will be listed here.
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
                    }}
                  >
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px', flexWrap: 'wrap' }}>
                        <span
                          className={`badge-${task.domain}`}
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
                      >
                        {task.title}
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
                        {isCompleted ? '✓ Completed' : 'Open'}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* System Status */}
        <div className="dashboard-section-card">
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
                  {backendStatus}
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
                    : 'Local Workspace'}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '1px' }}>
                  {currentUser?.email || 'Anonymous Guest Session'}
                </div>
              </div>
              <span style={{ fontSize: '18px' }}>🗓️</span>
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
                  Nebius Token Factory · Nemotron-3
                </div>
              </div>
              <span style={{ fontSize: '18px' }}>⚡</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
