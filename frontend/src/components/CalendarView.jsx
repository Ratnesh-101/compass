import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import {
  fetchCalendarStatus,
  fetchCalendarAvailability,
  proposeSchedule,
  commitSchedule,
  getCalendarExportUrl,
  getGoogleOAuthConnectUrl,
  disconnectCalendar,
  checkReactiveSchedule,
  syncCalendarNow,
  quickConnectUser,
  deleteTask,
} from '../api/client'

const DOMAIN_STYLES = {
  hackathon: {
    bg: 'rgba(245, 158, 11, 0.15)',
    border: '1px solid rgba(245, 158, 11, 0.45)',
    accent: '#f59e0b',
    text: '#fbbf24',
    badgeClass: 'badge-hackathon',
  },
  coursework: {
    bg: 'rgba(59, 130, 246, 0.15)',
    border: '1px solid rgba(59, 130, 246, 0.45)',
    accent: '#3b82f6',
    text: '#60a5fa',
    badgeClass: 'badge-coursework',
  },
  code: {
    bg: 'rgba(16, 185, 129, 0.15)',
    border: '1px solid rgba(16, 185, 129, 0.45)',
    accent: '#10b981',
    text: '#34d399',
    badgeClass: 'badge-code',
  },
  general: {
    bg: 'rgba(100, 116, 139, 0.15)',
    border: '1px solid rgba(100, 116, 139, 0.45)',
    accent: '#64748b',
    text: '#94a3b8',
    badgeClass: 'badge-general',
  },
  other: {
    bg: 'rgba(167, 139, 250, 0.15)',
    border: '1px solid rgba(167, 139, 250, 0.45)',
    accent: '#a78bfa',
    text: '#c084fc',
    badgeClass: 'badge-other',
  },
}

export function getCalendarDomainStyle(dom) {
  if (!dom) return DOMAIN_STYLES.general
  const key = String(dom).toLowerCase().trim()
  if (DOMAIN_STYLES[key]) return DOMAIN_STYLES[key]
  return {
    bg: 'rgba(192, 132, 252, 0.15)',
    border: '1px solid rgba(192, 132, 252, 0.45)',
    accent: '#c084fc',
    text: '#e9d5ff',
    badgeClass: 'badge-other',
  }
}

const HOURS = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
const HOUR_ROW_HEIGHT = 52

// ---------------------------------------------------------------------------
// Date helpers (local-time based, matching the original day-tab generation)
// ---------------------------------------------------------------------------
function toIso(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}
function parseIsoLocal(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}
function addDays(date, n) {
  const d = new Date(date)
  d.setDate(d.getDate() + n)
  return d
}
function startOfWeek(date) {
  const d = new Date(date)
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() - d.getDay())
  return d
}
function isSameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}
function startOfMonthGrid(cursor) {
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1)
  return startOfWeek(first)
}

export default function CalendarView({ tasks, activeDomain, onTasksUpdated, onOpenAuthModal }) {
  const [calendarStatus, setCalendarStatus] = useState({ connected: false, mode: 'demo', account_email: 'demo-scholar@compass.ai' })
  const [selectedDate, setSelectedDate] = useState(() => toIso(new Date()))
  const [monthCursor, setMonthCursor] = useState(() => new Date())
  const [busyIntervals, setBusyIntervals] = useState([])
  const [loadingAvailability, setLoadingAvailability] = useState(false)
  const [proposing, setProposing] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [proposedPlan, setProposedPlan] = useState(null)
  const [bannerMessage, setBannerMessage] = useState(null)
  const [checkingReactive, setCheckingReactive] = useState(false)
  const [syncingCalendar, setSyncingCalendar] = useState(false)
  const [quickEmailInput, setQuickEmailInput] = useState('')
  const [showQuickModal, setShowQuickModal] = useState(false)
  const [showIcsModal, setShowIcsModal] = useState(false)
  const [showMoreMenu, setShowMoreMenu] = useState(false)
  const [viewMode, setViewMode] = useState('week') // 'week' | 'agenda'
  const moreMenuRef = useRef(null)

  const selectedDateObj = useMemo(() => parseIsoLocal(selectedDate), [selectedDate])
  const weekStart = useMemo(() => startOfWeek(selectedDateObj), [selectedDateObj])
  const weekDays = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)), [weekStart])
  const today = new Date()

  // Close the overflow menu on outside click
  useEffect(() => {
    const handler = (e) => {
      if (moreMenuRef.current && !moreMenuRef.current.contains(e.target)) setShowMoreMenu(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Sync calendar connection status & check URL callback
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search)
    if (urlParams.get('calendar_connected') === 'true') {
      const email = urlParams.get('email') || ''
      setBannerMessage({
        type: 'success',
        text: `✅ Google Calendar successfully connected via OAuth (${email || 'Live'})! Scheduled tasks will synchronize directly.`
      })
      if (email) {
        setCalendarStatus({
          connected: true,
          mode: 'live',
          account_email: email,
          label: `Google Calendar: ${email} (Live OAuth Connected)`,
        })
      }
      window.history.replaceState({}, document.title, window.location.pathname)
    }

    fetchCalendarStatus().then(status => {
      if (status) setCalendarStatus(status)
    })
  }, [])

  // Fetch free/busy intervals for the whole visible week
  const loadAvailability = useCallback(async (weekStartDate) => {
    setLoadingAvailability(true)
    try {
      const rangeStart = toIso(weekStartDate)
      const rangeEnd = toIso(addDays(weekStartDate, 7))
      const data = await fetchCalendarAvailability(rangeStart, rangeEnd)
      if (data && Array.isArray(data.busy_intervals)) {
        setBusyIntervals(data.busy_intervals)
      }
    } catch (e) {
      console.warn('Could not load availability:', e)
    } finally {
      setLoadingAvailability(false)
    }
  }, [])

  useEffect(() => {
    loadAvailability(weekStart)
  }, [weekStart, loadAvailability])

  // Tasks scheduled on a given ISO date, filtered by active domain
  const scheduledForDay = useCallback((isoDate) => {
    return tasks.filter(t => {
      if (!t.scheduled_start) return false
      const taskDate = t.scheduled_start.split('T')[0]
      const matchesDomain = activeDomain === 'all' || t.domain === activeDomain
      return taskDate === isoDate && matchesDomain
    })
  }, [tasks, activeDomain])

  // External busy events on a given ISO date
  const externalEventsForDay = useCallback((isoDate) => {
    return busyIntervals.filter(b => {
      if (!b.start) return false
      return b.start.split('T')[0] === isoDate && b.source === 'google_calendar'
    })
  }, [busyIntervals])

  // Filter unplaced / unscheduled tasks
  const unscheduledTasks = tasks.filter(t => {
    const isUnplaced = !t.scheduled_start
    const matchesDomain = activeDomain === 'all' || t.domain === activeDomain
    const isOpen = (t.status || 'open') !== 'done'
    return isUnplaced && matchesDomain && isOpen
  })

  // All scheduled tasks, for agenda view + mini-calendar dot markers
  const allScheduledTasks = useMemo(
    () => tasks.filter(t => t.scheduled_start && (activeDomain === 'all' || t.domain === activeDomain)),
    [tasks, activeDomain]
  )
  const scheduledDateSet = useMemo(
    () => new Set(allScheduledTasks.map(t => t.scheduled_start.split('T')[0])),
    [allScheduledTasks]
  )

  // Calculate top/height (%) for the 08:00–20:00 grid (12h = 720 min)
  const getEventPosition = (startIso, endIso) => {
    try {
      const start = new Date(startIso)
      const end = new Date(endIso)
      const startMinutes = start.getUTCHours() * 60 + start.getUTCMinutes()
      const endMinutes = end.getUTCHours() * 60 + end.getUTCMinutes()
      const gridStart = 8 * 60
      const gridEnd = 20 * 60
      const totalMinutes = gridEnd - gridStart
      const top = Math.max(0, ((startMinutes - gridStart) / totalMinutes) * 100)
      const height = Math.max(4, ((endMinutes - startMinutes) / totalMinutes) * 100)
      return { top: `${top}%`, height: `${height}%` }
    } catch {
      return { top: '0%', height: '10%' }
    }
  }

  const handleAutoSchedule = async () => {
    setProposing(true)
    setBannerMessage(null)
    try {
      const result = await proposeSchedule({ targetDate: selectedDate, domain: activeDomain })
      setProposedPlan(result)
    } catch (err) {
      setBannerMessage({ type: 'error', text: `Failed to propose schedule: ${err.message}` })
    } finally {
      setProposing(false)
    }
  }

  const handleCommitPlan = async () => {
    if (!proposedPlan || !proposedPlan.scheduled || proposedPlan.scheduled.length === 0) return
    setCommitting(true)
    try {
      const assignments = proposedPlan.scheduled.map(s => ({
        task_id: s.task_id,
        scheduled_start: s.scheduled_start,
        scheduled_end: s.scheduled_end,
      }))
      await commitSchedule(assignments, proposedPlan.summary)
      setBannerMessage({ type: 'success', text: `✅ Successfully slotted ${assignments.length} tasks and synced to Google Calendar!` })
      setProposedPlan(null)
      if (onTasksUpdated) onTasksUpdated()
      loadAvailability(weekStart)
    } catch (err) {
      setBannerMessage({ type: 'error', text: `Error committing schedule: ${err.message}` })
    } finally {
      setCommitting(false)
    }
  }

  const handleCheckReactive = async () => {
    setCheckingReactive(true)
    try {
      const res = await checkReactiveSchedule()
      if (res.slipped_count > 0) {
        setBannerMessage({
          type: 'warning',
          text: `⚠️ Detected ${res.slipped_count} slipped task(s) past scheduled end time! Reactive re-plan staged with cascading dependencies (Run ID: ${res.run_id || 'staged'}).`
        })
        if (onTasksUpdated) onTasksUpdated()
      } else {
        setBannerMessage({ type: 'success', text: '✅ Schedule is currently on track — no uncompleted tasks have slipped past their end time.' })
      }
    } catch (e) {
      setBannerMessage({ type: 'error', text: `Error checking schedule slips: ${e.message}` })
    } finally {
      setCheckingReactive(false)
    }
  }

  const handleSyncNow = async () => {
    setSyncingCalendar(true)
    setBannerMessage(null)
    try {
      const res = await syncCalendarNow()
      if (res.is_live) {
        setBannerMessage({ type: 'success', text: `✅ Synced ${res.live_count || res.count || 0} scheduled tasks directly to your Google Calendar (${calendarStatus.account_email})!` })
      } else {
        setBannerMessage({ type: 'info', text: `ℹ️ ${res.message || `Slotted ${res.count || 0} tasks in Compass.`}` })
        setShowIcsModal(true)
      }
      loadAvailability(weekStart)
    } catch (err) {
      setBannerMessage({ type: 'error', text: `Failed to sync: ${err.message}` })
    } finally {
      setSyncingCalendar(false)
      setShowMoreMenu(false)
    }
  }

  const handleDisconnect = async () => {
    await disconnectCalendar()
    setCalendarStatus({ connected: false, mode: 'demo', account_email: 'demo-scholar@compass.ai' })
    loadAvailability(weekStart)
    setShowMoreMenu(false)
  }

  const isLive = calendarStatus.connected && calendarStatus.mode === 'live'

  // Mini month calendar grid
  const monthGridStart = useMemo(() => startOfMonthGrid(monthCursor), [monthCursor])
  const monthDays = useMemo(() => Array.from({ length: 42 }, (_, i) => addDays(monthGridStart, i)), [monthGridStart])

  const weekLabel = `Week of ${weekStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', background: 'var(--bg-app)' }}>
      {/* Top Header Bar — condensed */}
      <div style={{
        padding: '14px 24px', borderBottom: '1px solid var(--border)', background: 'var(--bg-card)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0, flexWrap: 'wrap', gap: '10px'
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <h2 style={{ fontSize: '17px', fontWeight: '700', color: 'var(--text-primary)', letterSpacing: '-0.3px' }}>
              🗓️ Schedule
            </h2>
            <div
              onClick={() => { if (onOpenAuthModal) onOpenAuthModal(); else setShowQuickModal(true) }}
              title="Click to switch account or manage Google Calendar"
              style={{
                display: 'flex', alignItems: 'center', gap: '6px', padding: '4px 10px', borderRadius: '20px',
                background: isLive ? 'var(--code-bg)' : 'var(--hackathon-bg)',
                fontSize: '11px', color: isLive ? 'var(--code-text)' : 'var(--hackathon-text)',
                fontWeight: '600', cursor: 'pointer'
              }}>
              <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: isLive ? '#10b981' : '#f5a623' }} />
              {isLive ? `${calendarStatus.account_email} (Live)` : `${calendarStatus.account_email || 'demo-scholar@compass.ai'} (demo — click to link)`}
            </div>
          </div>
          <p style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '3px' }}>
            Working hours 09:00–18:00 · 15m inter-task buffer · deterministic slot allocator
          </p>
        </div>

        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button
            id="btn-check-slipped"
            onClick={handleCheckReactive}
            disabled={checkingReactive}
            style={{
              padding: '8px 14px', borderRadius: '8px', background: 'var(--hackathon-bg)', border: 'none',
              color: 'var(--hackathon-text)', fontSize: '12px', fontWeight: '600', cursor: checkingReactive ? 'wait' : 'pointer'
            }}>
            {checkingReactive ? '🔄 Scanning...' : '⚡ Scan Slip'}
          </button>

          <div ref={moreMenuRef} style={{ position: 'relative' }}>
            <button
              onClick={() => setShowMoreMenu(v => !v)}
              style={{
                padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)',
                color: 'var(--text-secondary)', fontSize: '13px', fontWeight: '700', cursor: 'pointer'
              }}>
              •••
            </button>
            {showMoreMenu && (
              <div style={{
                position: 'absolute', top: '110%', right: 0, background: 'var(--bg-card)', border: '1px solid var(--border)',
                borderRadius: '12px', boxShadow: 'var(--shadow-lg)', width: '240px', padding: '8px', zIndex: 50
              }}>
                <button
                  id="btn-sync-gcal"
                  onClick={handleSyncNow}
                  disabled={syncingCalendar}
                  style={menuItemStyle}>
                  {syncingCalendar ? '🔄 Syncing...' : (isLive ? '📅 Sync to Google Calendar' : '📅 Slot / Sync Tasks')}
                </button>
                <a id="btn-export-ics" href={getCalendarExportUrl(activeDomain)} download="compass_schedule.ics" style={{ ...menuItemStyle, textDecoration: 'none', display: 'block' }}>
                  📥 Export .ics Feed
                </a>
                <button onClick={() => { setShowIcsModal(true); setShowMoreMenu(false) }} style={menuItemStyle}>
                  📘 Sync Guide
                </button>
                <div style={{ height: '1px', background: 'var(--border-soft)', margin: '6px 0' }} />
                {calendarStatus.connected ? (
                  <>
                    <a href="https://calendar.google.com" target="_blank" rel="noreferrer" style={{ ...menuItemStyle, textDecoration: 'none', display: 'block' }}>
                      Open Google Calendar ↗
                    </a>
                    {!isLive && (
                      <a id="btn-connect-google" href={getGoogleOAuthConnectUrl()} style={{ ...menuItemStyle, textDecoration: 'none', display: 'block' }}>
                        🔗 Sign in with Google
                      </a>
                    )}
                    <button id="btn-disconnect-google" onClick={handleDisconnect} style={{ ...menuItemStyle, color: '#dc2626' }}>
                      Disconnect
                    </button>
                  </>
                ) : (
                  <>
                    <button id="btn-connect-google" onClick={() => { if (onOpenAuthModal) onOpenAuthModal(); else setShowQuickModal(true); setShowMoreMenu(false) }} style={menuItemStyle}>
                      🔗 Connect Google Calendar
                    </button>
                    <button id="btn-quick-login" onClick={() => { if (onOpenAuthModal) onOpenAuthModal(); else setShowQuickModal(true); setShowMoreMenu(false) }} style={menuItemStyle}>
                      ⚡ Switch Account
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Status Notifications Banner */}
      {bannerMessage && (
        <div style={{
          padding: '10px 24px',
          background: bannerMessage.type === 'error' ? 'var(--danger-bg)' : 'var(--code-bg)',
          color: bannerMessage.type === 'error' ? '#b91c1c' : 'var(--code-text)',
          fontSize: '12.5px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0
        }}>
          <span>{bannerMessage.text}</span>
          <button onClick={() => setBannerMessage(null)} style={{ background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: '14px' }}>✕</button>
        </div>
      )}

      {/* Main 3-column layout */}
      <div style={{ flex: 1, display: 'flex', gap: '16px', padding: '16px', overflow: 'hidden', minHeight: 0 }}>
        {/* Left: mini month calendar + selected-day panel */}
        <div style={{ width: '270px', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: '14px', overflowY: 'auto' }}>
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '14px', padding: '14px', boxShadow: 'var(--shadow-sm)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
              <button onClick={() => setMonthCursor(new Date(monthCursor.getFullYear(), monthCursor.getMonth() - 1, 1))} style={iconBtnStyle}>‹</button>
              <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary)' }}>
                {monthCursor.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}
              </div>
              <button onClick={() => setMonthCursor(new Date(monthCursor.getFullYear(), monthCursor.getMonth() + 1, 1))} style={iconBtnStyle}>›</button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '3px', marginBottom: '4px' }}>
              {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((d, i) => (
                <div key={i} style={{ fontSize: '9.5px', color: 'var(--text-muted)', textAlign: 'center', fontWeight: '700' }}>{d}</div>
              ))}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '3px' }}>
              {monthDays.map((d, i) => {
                const iso = toIso(d)
                const inMonth = d.getMonth() === monthCursor.getMonth()
                const isSelected = iso === selectedDate
                const isToday = isSameDay(d, today)
                const hasEvents = scheduledDateSet.has(iso)
                return (
                  <button
                    key={i}
                    onClick={() => setSelectedDate(iso)}
                    style={{
                      aspectRatio: '1', border: 'none', borderRadius: '7px', cursor: 'pointer',
                      background: isSelected ? 'var(--brand)' : 'transparent',
                      color: isSelected ? '#2a1a00' : (inMonth ? 'var(--text-primary)' : 'var(--text-muted)'),
                      fontWeight: isToday ? '800' : '500', fontSize: '11.5px',
                      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '2px'
                    }}>
                    {d.getDate()}
                    {hasEvents && !isSelected && <span style={{ width: '3px', height: '3px', borderRadius: '50%', background: 'var(--brand)' }} />}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Selected day panel */}
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '14px', padding: '14px', boxShadow: 'var(--shadow-sm)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
              <div style={{ fontSize: '10.5px', fontWeight: '700', color: 'var(--text-muted)', letterSpacing: '0.06em' }}>
                {selectedDateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toUpperCase()}
              </div>
              <div style={{ fontSize: '10.5px', fontWeight: '600', color: 'var(--coursework-text)', background: 'var(--coursework-bg)', padding: '2px 8px', borderRadius: '20px' }}>
                {scheduledForDay(selectedDate).length} event{scheduledForDay(selectedDate).length === 1 ? '' : 's'}
              </div>
            </div>
            {scheduledForDay(selectedDate).length === 0 ? (
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>No scheduled tasks this day.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '7px' }}>
                {scheduledForDay(selectedDate).map(t => {
                  const s = getCalendarDomainStyle(t.domain)
                  return (
                    <div key={t.id} style={{ background: s.bg, borderLeft: `3px solid ${s.accent}`, borderRadius: '8px', padding: '8px 10px' }}>
                      <div style={{ fontSize: '12px', fontWeight: '700', color: s.text }}>{t.title}</div>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '2px' }}>
                        🕐 {t.scheduled_start.slice(11, 16)}–{t.scheduled_end.slice(11, 16)} UTC · {t.duration_minutes || 60}m
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        {/* Center: week grid / agenda */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '14px', overflow: 'hidden', boxShadow: 'var(--shadow-sm)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap', gap: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <button onClick={() => setSelectedDate(toIso(today))} style={pillBtnStyle}>Today</button>
              <button onClick={() => setSelectedDate(toIso(addDays(selectedDateObj, -7)))} style={iconBtnStyle}>‹</button>
              <button onClick={() => setSelectedDate(toIso(addDays(selectedDateObj, 7)))} style={iconBtnStyle}>›</button>
              <div style={{ fontSize: '14px', fontWeight: '700', color: 'var(--text-primary)' }}>{weekLabel}</div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ display: 'flex', border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden' }}>
                {['week', 'agenda'].map(m => (
                  <button key={m} onClick={() => setViewMode(m)} style={{
                    padding: '6px 12px', border: 'none', cursor: 'pointer', fontSize: '11.5px', fontWeight: '600',
                    background: viewMode === m ? 'var(--coursework)' : 'var(--bg-card)',
                    color: viewMode === m ? '#fff' : 'var(--text-secondary)', textTransform: 'capitalize'
                  }}>{m}</button>
                ))}
              </div>
              <button
                id="btn-auto-schedule"
                onClick={handleAutoSchedule}
                disabled={proposing}
                style={{
                  padding: '7px 14px', borderRadius: '8px', border: 'none',
                  background: 'linear-gradient(135deg, #6c5ce7, #8b5cf6)', color: '#fff',
                  fontSize: '12px', fontWeight: '700', cursor: proposing ? 'wait' : 'pointer',
                  opacity: proposing ? 0.7 : 1
                }}>
                {proposing ? '⚡ Optimizing…' : '⚡ Auto-Schedule'}
              </button>
            </div>
          </div>

          {viewMode === 'week' ? (
            <div style={{ flex: 1, overflow: 'auto' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '48px repeat(7, 1fr)', borderBottom: '1px solid var(--border)', position: 'sticky', top: 0, background: 'var(--bg-card)', zIndex: 1 }}>
                <div />
                {weekDays.map((d, i) => {
                  const isToday = isSameDay(d, today)
                  const iso = toIso(d)
                  return (
                    <div key={i} onClick={() => setSelectedDate(iso)} style={{
                      padding: '8px 6px', textAlign: 'center', borderLeft: '1px solid var(--border-soft)', cursor: 'pointer',
                      background: iso === selectedDate ? 'var(--coursework-bg)' : 'transparent'
                    }}>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: '600' }}>{d.toLocaleDateString('en-US', { weekday: 'short' })}</div>
                      <div style={{
                        fontSize: '13px', fontWeight: '700', color: isToday ? 'var(--coursework)' : 'var(--text-primary)',
                        width: '24px', height: '24px', borderRadius: '50%', margin: '2px auto 0',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        background: isToday ? 'var(--coursework-bg)' : 'transparent'
                      }}>{d.getDate()}</div>
                    </div>
                  )
                })}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '48px repeat(7, 1fr)', position: 'relative' }}>
                <div>
                  {HOURS.map(h => (
                    <div key={h} style={{ height: `${HOUR_ROW_HEIGHT}px`, textAlign: 'right', paddingRight: '6px', fontSize: '9.5px', color: 'var(--text-muted)', transform: 'translateY(-6px)', fontFamily: 'JetBrains Mono, monospace' }}>
                      {String(h).padStart(2, '0')}:00
                    </div>
                  ))}
                </div>

                {weekDays.map((d, dayIdx) => {
                  const iso = toIso(d)
                  const dayEvents = scheduledForDay(iso)
                  const dayBusy = externalEventsForDay(iso)
                  return (
                    <div key={dayIdx} style={{ position: 'relative', borderLeft: '1px solid var(--border-soft)', minHeight: `${HOUR_ROW_HEIGHT * HOURS.length}px` }}>
                      {HOURS.map(h => (
                        <div key={h} style={{ height: `${HOUR_ROW_HEIGHT}px`, borderBottom: '1px solid var(--border-soft)' }} />
                      ))}

                      {dayBusy.map(ev => {
                        const pos = getEventPosition(ev.start, ev.end)
                        return (
                          <div key={ev.id} style={{
                            position: 'absolute', left: '3px', right: '3px', top: pos.top, height: pos.height,
                            background: 'rgba(31,27,46,0.04)', border: '1px dashed var(--border)', borderRadius: '6px',
                            padding: '3px 6px', overflow: 'hidden', zIndex: 2
                          }}>
                            <div style={{ fontSize: '9.5px', color: 'var(--text-secondary)' }}>📅 {ev.title}</div>
                          </div>
                        )
                      })}

                      {dayEvents.map(t => {
                        const pos = getEventPosition(t.scheduled_start, t.scheduled_end)
                        const s = getCalendarDomainStyle(t.domain)
                        return (
                          <div key={t.id} style={{
                            position: 'absolute', left: '3px', right: '3px', top: pos.top, height: pos.height,
                            background: s.bg, border: s.border, borderRadius: '6px', padding: '4px 7px',
                            overflow: 'hidden', zIndex: 4, boxShadow: 'var(--shadow-sm)'
                          }}>
                            <div style={{ fontSize: '10.5px', fontWeight: '700', color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                              {t.title}
                            </div>
                            <div style={{ fontSize: '9px', color: s.text }}>
                              {t.scheduled_start.slice(11, 16)}
                              {isLive ? ' ✓' : ' ⏱'}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )
                })}
              </div>

              {allScheduledTasks.filter(t => weekDays.some(d => toIso(d) === t.scheduled_start.split('T')[0])).length === 0 && (
                <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)' }}>
                  <div style={{ fontSize: '28px', marginBottom: '8px' }}>🗓️</div>
                  <p style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>No tasks or events scheduled this week</p>
                  <p style={{ fontSize: '11.5px', marginTop: '4px' }}>Click "Auto-Schedule" to automatically place open tasks into working hours.</p>
                </div>
              )}
            </div>
          ) : (
            <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }}>
              {allScheduledTasks.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)', fontSize: '13px' }}>
                  No scheduled tasks yet. Use "Auto-Schedule" to place your open tasks.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {allScheduledTasks
                    .slice()
                    .sort((a, b) => new Date(a.scheduled_start) - new Date(b.scheduled_start))
                    .map(t => {
                      const s = getCalendarDomainStyle(t.domain)
                      const start = new Date(t.scheduled_start)
                      return (
                        <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: '14px', padding: '12px 14px', background: 'var(--bg-card-soft)', border: '1px solid var(--border)', borderRadius: '10px' }}>
                          <div style={{ width: '64px', flexShrink: 0, textAlign: 'center' }}>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '700' }}>{start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</div>
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{t.scheduled_start.slice(11, 16)} UTC</div>
                          </div>
                          <div style={{ width: '3px', height: '32px', background: s.accent, borderRadius: '2px', flexShrink: 0 }} />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary)' }}>{t.title}</div>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{t.domain} · {t.duration_minutes || 60}min</div>
                          </div>
                        </div>
                      )
                    })}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right: pending tasks + policy widget (unchanged content) */}
        <div style={{ width: '280px', flexShrink: 0, display: 'flex', flexDirection: 'column', background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '14px', padding: '16px', overflowY: 'auto', boxShadow: 'var(--shadow-sm)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h3 style={{ fontSize: '12.5px', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-primary)', fontWeight: '700' }}>
              Pending Tasks ({unscheduledTasks.length})
            </h3>
            <span style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>Unscheduled</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '20px' }}>
            {unscheduledTasks.map(task => {
              const s = getCalendarDomainStyle(task.domain)
              return (
                <div key={task.id} style={{ padding: '10px 12px', borderRadius: '8px', background: 'var(--bg-card-soft)', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <span style={{ fontSize: '12px', color: 'var(--text-primary)', fontWeight: '600' }}>{task.title}</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span className={s.badgeClass} style={{ padding: '1px 6px', borderRadius: '4px', fontSize: '9.5px', fontWeight: '700' }}>{task.domain}</span>
                      <button
                        title="Delete task/deadline"
                        onClick={async (e) => {
                          e.stopPropagation()
                          if (window.confirm(`Delete "${task.title}"?`)) {
                            try {
                              await deleteTask(task.id)
                              if (onTasksUpdated) onTasksUpdated()
                            } catch (err) {
                              alert(`Failed to delete: ${err.message}`)
                            }
                          }
                        }}
                        style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '2px 4px', borderRadius: '4px', fontSize: '11px' }}
                        onMouseEnter={e => e.currentTarget.style.color = '#ef4444'}
                        onMouseLeave={e => e.currentTarget.style.color = 'var(--text-muted)'}
                      >🗑️</button>
                    </div>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px' }}>
                    <span style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>⏱️ {task.duration_minutes || 60}m · {task.priority || 'medium'}</span>
                    <span style={{ fontSize: '10.5px', color: 'var(--hackathon-text)', fontWeight: '600' }}>{task.countdown || 'Needs slot'}</span>
                  </div>
                </div>
              )
            })}

            {unscheduledTasks.length === 0 && (
              <div style={{ padding: '20px 14px', textAlign: 'center', color: 'var(--text-muted)', background: 'var(--bg-card-soft)', borderRadius: '8px', border: '1px dashed var(--border)' }}>
                <span style={{ fontSize: '18px' }}>🎉</span>
                <p style={{ fontSize: '11.5px', marginTop: '6px' }}>All tasks are scheduled into calendar time slots!</p>
              </div>
            )}
          </div>

          <div style={{ marginTop: 'auto', padding: '14px', borderRadius: '8px', background: 'var(--coursework-bg)' }}>
            <h4 style={{ fontSize: '11.5px', fontWeight: '700', color: 'var(--coursework-text)', marginBottom: '8px' }}>⚙️ Deterministic Policy</h4>
            <ul style={{ fontSize: '10.5px', color: 'var(--text-secondary)', lineHeight: '1.6', paddingLeft: '14px' }}>
              <li>Working Window: 09:00 - 18:00 UTC</li>
              <li>Days: Monday - Friday (workdays)</li>
              <li>Inter-task buffer: 15 minutes</li>
              <li>LLM slot hallucinations: 0% (pure Python)</li>
              <li>Calendar sync: Instant RFC 5545 + Google</li>
            </ul>
          </div>
        </div>
      </div>

      {/* Auto-Schedule Review & Confirmation Modal */}
      {proposedPlan && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(31, 27, 46, 0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, backdropFilter: 'blur(5px)' }}>
          <div style={{ width: '580px', maxWidth: '90vw', background: 'var(--bg-card)', borderRadius: '16px', border: '1px solid var(--border)', boxShadow: 'var(--shadow-lg)', padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ fontSize: '16px', fontWeight: '800', color: 'var(--text-primary)' }}>⚡ Review Proposed Schedule Allocation</h3>
              <button onClick={() => setProposedPlan(null)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: '16px', cursor: 'pointer' }}>✕</button>
            </div>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: '1.5' }}>{proposedPlan.summary}</p>
            <div style={{ maxHeight: '260px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px', background: 'var(--bg-card-soft)', padding: '12px', borderRadius: '10px', border: '1px solid var(--border)' }}>
              {proposedPlan.scheduled && proposedPlan.scheduled.map(s => (
                <div key={s.task_id} style={{ padding: '8px 12px', borderRadius: '8px', background: 'var(--bg-card)', border: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <strong style={{ fontSize: '12.5px', color: 'var(--text-primary)' }}>{s.title}</strong>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>Domain: {s.domain} · Duration: {s.duration_minutes}m</div>
                  </div>
                  <span style={{ fontSize: '11.5px', color: 'var(--coursework-text)', fontFamily: 'JetBrains Mono, monospace', fontWeight: '700' }}>
                    {s.scheduled_start.slice(0, 10)} {s.scheduled_start.slice(11, 16)} → {s.scheduled_end.slice(11, 16)}
                  </span>
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '8px' }}>
              <button onClick={() => setProposedPlan(null)} style={{ padding: '8px 16px', borderRadius: '8px', background: 'var(--bg-card-soft)', border: '1px solid var(--border)', color: 'var(--text-secondary)', fontSize: '13px', fontWeight: '500', cursor: 'pointer' }}>Cancel</button>
              <button
                id="btn-confirm-commit-schedule"
                onClick={handleCommitPlan}
                disabled={committing}
                style={{ padding: '8px 20px', borderRadius: '8px', background: 'linear-gradient(135deg, #10b981, #059669)', border: 'none', color: '#ffffff', fontSize: '13px', fontWeight: '700', cursor: committing ? 'wait' : 'pointer' }}>
                {committing ? 'Committing...' : '✅ Approve & Commit to Google Calendar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Quick Gmail Login Modal */}
      {showQuickModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(31, 27, 46, 0.45)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '16px', padding: '28px', width: '100%', maxWidth: '420px', boxShadow: 'var(--shadow-lg)' }}>
            <h3 style={{ margin: '0 0 8px', color: 'var(--text-primary)', fontSize: '18px', fontWeight: '800' }}>⚡ Connect Your Gmail</h3>
            <p style={{ color: 'var(--text-secondary)', fontSize: '13px', margin: '0 0 20px', lineHeight: '1.5' }}>
              Enter your Gmail address to activate your schedule profile. Tasks will be slotted deterministically and can be imported or subscribed directly in Google Calendar.
            </p>
            <input
              id="input-quick-email"
              type="email"
              placeholder="e.g. yourname@gmail.com"
              value={quickEmailInput}
              onChange={(e) => setQuickEmailInput(e.target.value)}
              onKeyDown={async (e) => {
                if (e.key === 'Enter' && quickEmailInput.includes('@')) {
                  await quickConnectUser(quickEmailInput)
                  setShowQuickModal(false)
                  fetchCalendarStatus().then(status => { if (status) setCalendarStatus(status) })
                  setBannerMessage({ type: 'success', text: `✅ Connected as ${quickEmailInput}! Schedule slotted.` })
                }
              }}
              style={{ width: '100%', padding: '10px 14px', borderRadius: '8px', background: 'var(--bg-app)', border: '1px solid var(--border)', color: 'var(--text-primary)', fontSize: '14px', marginBottom: '18px', boxSizing: 'border-box', outline: 'none' }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button onClick={() => setShowQuickModal(false)} style={{ padding: '8px 16px', borderRadius: '8px', background: 'var(--bg-card-soft)', border: '1px solid var(--border)', color: 'var(--text-secondary)', fontSize: '13px', fontWeight: '500', cursor: 'pointer' }}>Cancel</button>
              <button
                id="btn-submit-quick-connect"
                disabled={!quickEmailInput.includes('@')}
                onClick={async () => {
                  try {
                    await quickConnectUser(quickEmailInput)
                    setShowQuickModal(false)
                    fetchCalendarStatus().then(status => { if (status) setCalendarStatus(status) })
                    setBannerMessage({ type: 'success', text: `✅ Connected as ${quickEmailInput}! Schedule slotted.` })
                  } catch (err) {
                    alert(`Could not connect: ${err.message}`)
                  }
                }}
                style={{ padding: '8px 18px', borderRadius: '8px', background: quickEmailInput.includes('@') ? 'linear-gradient(135deg, #2563eb, #3b82f6)' : 'var(--bg-card-soft)', border: 'none', color: quickEmailInput.includes('@') ? '#ffffff' : 'var(--text-muted)', fontSize: '13px', fontWeight: '700', cursor: quickEmailInput.includes('@') ? 'pointer' : 'not-allowed' }}>
                Connect Account
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Google Calendar Sync & .ics Import Guide Modal */}
      {showIcsModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(31, 27, 46, 0.45)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '16px', padding: '28px', width: '100%', maxWidth: '520px', boxShadow: 'var(--shadow-lg)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <h3 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '18px', fontWeight: '800', display: 'flex', alignItems: 'center', gap: '8px' }}>
                🗓️ Sync Tasks to Google Calendar
              </h3>
              <button onClick={() => setShowIcsModal(false)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: '18px', cursor: 'pointer' }}>✕</button>
            </div>
            <p style={{ color: 'var(--text-secondary)', fontSize: '13px', lineHeight: '1.5', margin: '0 0 16px' }}>
              Because direct Google Calendar API write requires registered Google Cloud OAuth credentials, you can sync all your scheduled tasks into your Google Calendar right now in 2 easy steps:
            </p>
            <div style={{ background: 'var(--bg-card-soft)', border: '1px solid var(--border)', borderRadius: '10px', padding: '14px', marginBottom: '16px' }}>
              <h4 style={{ margin: '0 0 8px', color: 'var(--coursework-text)', fontSize: '13px', fontWeight: '700' }}>Option 1: Instant 1-Click File Import (Recommended)</h4>
              <ol style={{ margin: '0 0 10px', paddingLeft: '18px', color: 'var(--text-primary)', fontSize: '12.5px', lineHeight: '1.6' }}>
                <li>
                  Click below to download the <code style={{ color: 'var(--coursework-text)' }}>compass_schedule.ics</code> file:
                  <div style={{ marginTop: '6px', marginBottom: '6px' }}>
                    <a href={getCalendarExportUrl(activeDomain)} download="compass_schedule.ics" style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '6px 12px', background: 'linear-gradient(135deg, #3b82f6, #1d4ed8)', borderRadius: '6px', color: '#ffffff', fontSize: '12px', fontWeight: '700', textDecoration: 'none' }}>
                      📥 Download compass_schedule.ics
                    </a>
                  </div>
                </li>
                <li>In Google Calendar, look at the left sidebar under <b>Other calendars</b> and click <b>+</b>.</li>
                <li>Click <b>Import</b>, select the downloaded file, and click <b>Import</b>.</li>
                <li>All scheduled tasks immediately appear in your Google Calendar!</li>
              </ol>
              <div style={{ borderTop: '1px solid var(--border)', paddingTop: '10px', marginTop: '10px' }}>
                <h4 style={{ margin: '0 0 8px', color: 'var(--code-text)', fontSize: '13px', fontWeight: '700' }}>Option 2: Live Auto-Sync via Calendar Subscription URL</h4>
                <p style={{ color: 'var(--text-secondary)', fontSize: '12px', margin: '0 0 8px' }}>
                  In Google Calendar &gt; <b>Other calendars (+)</b> &gt; <b>From URL</b>, paste this feed URL:
                </p>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input readOnly value={`${window.location.origin}/api/calendar/export.ics`} style={{ flex: 1, padding: '6px 10px', borderRadius: '6px', background: 'var(--bg-app)', border: '1px solid var(--border)', color: 'var(--text-primary)', fontSize: '11.5px', fontFamily: 'JetBrains Mono, monospace' }} />
                  <button
                    onClick={(e) => {
                      navigator.clipboard.writeText(`${window.location.origin}/api/calendar/export.ics`)
                      e.target.innerText = 'Copied! ✓'
                      setTimeout(() => { e.target.innerText = 'Copy' }, 2000)
                    }}
                    style={{ padding: '6px 12px', borderRadius: '6px', background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-primary)', fontSize: '12px', fontWeight: '600', cursor: 'pointer' }}>
                    Copy
                  </button>
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <a href="https://calendar.google.com" target="_blank" rel="noreferrer" style={{ padding: '8px 16px', borderRadius: '8px', background: 'var(--bg-card-soft)', border: '1px solid var(--border)', color: 'var(--text-primary)', fontSize: '13px', fontWeight: '600', textDecoration: 'none' }}>
                Open Google Calendar ↗
              </a>
              <button onClick={() => setShowIcsModal(false)} style={{ padding: '8px 18px', borderRadius: '8px', background: 'linear-gradient(135deg, #3b82f6, #1d4ed8)', border: 'none', color: '#ffffff', fontSize: '13px', fontWeight: '700', cursor: 'pointer' }}>
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const menuItemStyle = {
  width: '100%', textAlign: 'left', padding: '9px 10px', borderRadius: '8px', border: 'none',
  background: 'transparent', color: 'var(--text-primary)', fontSize: '12.5px', fontWeight: '600', cursor: 'pointer'
}
const iconBtnStyle = {
  background: 'none', border: 'none', cursor: 'pointer', fontSize: '15px', color: 'var(--text-secondary)', padding: '2px 6px'
}
const pillBtnStyle = {
  padding: '6px 12px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)',
  color: 'var(--text-secondary)', fontSize: '12px', fontWeight: '600', cursor: 'pointer'
}