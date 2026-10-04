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
import { CalendarGrid } from './calendar/CalendarGrid'
import { CalendarSidebar } from './calendar/CalendarSidebar'
import { ProposedPlanModal, QuickConnectModal, IcsExportModal } from './calendar/CalendarModals'

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
        <CalendarSidebar
          monthCursor={monthCursor}
          setMonthCursor={setMonthCursor}
          monthDays={monthDays}
          selectedDate={selectedDate}
          setSelectedDate={setSelectedDate}
          selectedDateObj={selectedDateObj}
          today={today}
          scheduledDateSet={scheduledDateSet}
          scheduledForDay={scheduledForDay}
          getCalendarDomainStyle={getCalendarDomainStyle}
          toIso={toIso}
          isSameDay={isSameDay}
        />

        {/* Center: week grid / agenda */}
        <CalendarGrid
          viewMode={viewMode}
          setViewMode={setViewMode}
          selectedDate={selectedDate}
          setSelectedDate={setSelectedDate}
          selectedDateObj={selectedDateObj}
          today={today}
          weekLabel={weekLabel}
          weekDays={weekDays}
          handleAutoSchedule={handleAutoSchedule}
          proposing={proposing}
          HOURS={HOURS}
          HOUR_ROW_HEIGHT={HOUR_ROW_HEIGHT}
          scheduledForDay={scheduledForDay}
          externalEventsForDay={externalEventsForDay}
          getEventPosition={getEventPosition}
          getCalendarDomainStyle={getCalendarDomainStyle}
          isLive={isLive}
          allScheduledTasks={allScheduledTasks}
          toIso={toIso}
          addDays={addDays}
          isSameDay={isSameDay}
        />

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

      {/* Extracted Calendar Modals */}
      <ProposedPlanModal
        proposedPlan={proposedPlan}
        onClose={() => setProposedPlan(null)}
        onCommit={handleCommitPlan}
        committing={committing}
      />

      <QuickConnectModal
        show={showQuickModal}
        onClose={() => setShowQuickModal(false)}
        quickEmailInput={quickEmailInput}
        setQuickEmailInput={setQuickEmailInput}
        setCalendarStatus={setCalendarStatus}
        setBannerMessage={setBannerMessage}
      />

      <IcsExportModal
        show={showIcsModal}
        onClose={() => setShowIcsModal(false)}
        activeDomain={activeDomain}
      />
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