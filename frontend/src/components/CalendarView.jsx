import React, { useState, useEffect, useCallback } from 'react'
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
}

const HOURS = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]

export default function CalendarView({ tasks, activeDomain, onTasksUpdated }) {
  const [calendarStatus, setCalendarStatus] = useState({ connected: false, mode: 'demo', account_email: 'demo-scholar@compass.ai' })
  const [selectedDate, setSelectedDate] = useState(() => {
    const d = new Date()
    return d.toISOString().split('T')[0]
  })
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


  // Fetch free/busy intervals for selected date
  const loadAvailability = useCallback(async (dateStr) => {
    setLoadingAvailability(true)
    try {
      const nextDate = new Date(dateStr)
      nextDate.setDate(nextDate.getDate() + 1)
      const nextDateStr = nextDate.toISOString().split('T')[0]

      const data = await fetchCalendarAvailability(dateStr, nextDateStr)
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
    loadAvailability(selectedDate)
  }, [selectedDate, loadAvailability])

  // Filter tasks that have scheduled_start matching selectedDate
  const scheduledForSelectedDay = tasks.filter(t => {
    if (!t.scheduled_start) return false
    const taskDate = t.scheduled_start.split('T')[0]
    const matchesDomain = activeDomain === 'all' || t.domain === activeDomain
    return taskDate === selectedDate && matchesDomain
  })

  // Filter unplaced / unscheduled tasks
  const unscheduledTasks = tasks.filter(t => {
    const isUnplaced = !t.scheduled_start
    const matchesDomain = activeDomain === 'all' || t.domain === activeDomain
    const isOpen = (t.status || 'open') !== 'done'
    return isUnplaced && matchesDomain && isOpen
  })

  // External calendar events for selectedDate
  const externalEventsForDay = busyIntervals.filter(b => {
    if (!b.start) return false
    const bDate = b.start.split('T')[0]
    return bDate === selectedDate && b.source === 'google_calendar'
  })

  // Calculate top and height percentage for 08:00 - 20:00 (12 hours = 720 minutes)
  const getEventPosition = (startIso, endIso) => {
    try {
      const start = new Date(startIso)
      const end = new Date(endIso)
      const startMinutes = start.getUTCHours() * 60 + start.getUTCMinutes()
      const endMinutes = end.getUTCHours() * 60 + end.getUTCMinutes()

      const gridStart = 8 * 60 // 08:00 = 480 mins
      const gridEnd = 20 * 60  // 20:00 = 1200 mins
      const totalMinutes = gridEnd - gridStart

      const top = Math.max(0, ((startMinutes - gridStart) / totalMinutes) * 100)
      const height = Math.max(4, ((endMinutes - startMinutes) / totalMinutes) * 100)

      return { top: `${top}%`, height: `${height}%` }
    } catch {
      return { top: '0%', height: '10%' }
    }
  }

  // Handle Propose Schedule
  const handleAutoSchedule = async () => {
    setProposing(true)
    setBannerMessage(null)
    try {
      const result = await proposeSchedule({
        targetDate: selectedDate,
        domain: activeDomain,
      })
      setProposedPlan(result)
    } catch (err) {
      setBannerMessage({ type: 'error', text: `Failed to propose schedule: ${err.message}` })
    } finally {
      setProposing(false)
    }
  }

  // Handle Commit Schedule
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
      setBannerMessage({
        type: 'success',
        text: `✅ Successfully slotted ${assignments.length} tasks and synced to Google Calendar!`
      })
      setProposedPlan(null)
      if (onTasksUpdated) onTasksUpdated()
      loadAvailability(selectedDate)
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
        setBannerMessage({
          type: 'success',
          text: '✅ Schedule is currently on track — no uncompleted tasks have slipped past their end time.'
        })
      }
    } catch (e) {
      setBannerMessage({
        type: 'error',
        text: `Error checking schedule slips: ${e.message}`
      })
    } finally {
      setCheckingReactive(false)
    }
  }

  // Generate 7 days for the date selector
  const dayTabs = []
  const today = new Date()
  for (let i = -2; i < 5; i++) {
    const d = new Date()
    d.setDate(today.getDate() + i)
    const isoStr = d.toISOString().split('T')[0]
    const dayName = d.toLocaleDateString('en-US', { weekday: 'short' })
    const dayNum = d.getDate()
    dayTabs.push({ iso: isoStr, label: `${dayName} ${dayNum}`, isToday: i === 0 })
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', background: '#0b0f17' }}>
      {/* Top Header Bar */}
      <div style={{
        padding: '16px 24px',
        borderBottom: '1px solid #1e293b',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: '#0d131f',
        flexShrink: 0
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h2 style={{ fontSize: '18px', fontWeight: '700', color: '#f8fafc', letterSpacing: '-0.3px' }}>
              🗓️ Dynamic Schedule & Google Calendar
            </h2>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '4px 10px',
              borderRadius: '12px',
              background: calendarStatus.connected && calendarStatus.mode === 'live' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(245, 158, 11, 0.1)',
              border: calendarStatus.connected && calendarStatus.mode === 'live' ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(245, 158, 11, 0.3)',
              fontSize: '11px',
              color: calendarStatus.connected && calendarStatus.mode === 'live' ? '#34d399' : '#fbbf24',
              fontWeight: '500'
            }}>
              <span style={{
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                background: calendarStatus.connected && calendarStatus.mode === 'live' ? '#10b981' : '#f59e0b'
              }} />
              {calendarStatus.connected && calendarStatus.mode === 'live'
                ? `Google Calendar: ${calendarStatus.account_email} (Live OAuth Connected)`
                : `Google Calendar: ${calendarStatus.account_email || 'demo-scholar@compass.ai'} (simulated / demo mode — live OAuth not yet connected)`}
            </div>
          </div>
          <p style={{ fontSize: '12px', color: '#64748b', marginTop: '2px' }}>
            Deterministic Python interval slot allocator · Working hours (09:00–18:00) · 15m inter-task buffer
            {calendarStatus.mode === 'demo' && ' · Simulated calendar commitments (live OAuth available)'}
          </p>
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
          {calendarStatus.connected && calendarStatus.mode === 'live' ? (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <button
                id="btn-sync-gcal"
                onClick={async () => {
                  setSyncingCalendar(true)
                  setBannerMessage(null)
                  try {
                    const res = await syncCalendarNow()
                    setBannerMessage({
                      type: 'success',
                      text: `✅ Synced ${res.count || 0} scheduled tasks to your Google Calendar (${calendarStatus.account_email})!`
                    })
                    loadAvailability(selectedDate)
                  } catch (err) {
                    setBannerMessage({
                      type: 'error',
                      text: `Failed to sync to Google Calendar: ${err.message}`
                    })
                  } finally {
                    setSyncingCalendar(false)
                  }
                }}
                disabled={syncingCalendar}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '7px 12px',
                  borderRadius: '8px',
                  background: 'rgba(16, 185, 129, 0.15)',
                  border: '1px solid rgba(16, 185, 129, 0.4)',
                  color: '#34d399',
                  fontSize: '12px',
                  fontWeight: '500',
                  cursor: syncingCalendar ? 'wait' : 'pointer',
                  transition: 'all 0.15s ease'
                }}>
                {syncingCalendar ? '🔄 Syncing...' : '📅 Sync to Google Calendar'}
              </button>
              <a
                href="https://calendar.google.com"
                target="_blank"
                rel="noreferrer"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  padding: '7px 10px',
                  borderRadius: '8px',
                  background: '#1e293b',
                  border: '1px solid #334155',
                  color: '#94a3b8',
                  fontSize: '12px',
                  textDecoration: 'none'
                }}>
                Open Calendar ↗
              </a>
              <button
                id="btn-disconnect-google"
                onClick={async () => {
                  await disconnectCalendar()
                  setCalendarStatus({ connected: false, mode: 'demo', account_email: 'demo-scholar@compass.ai' })
                  loadAvailability(selectedDate)
                }}
                style={{
                  padding: '7px 10px',
                  borderRadius: '8px',
                  background: '#1e293b',
                  border: '1px solid #334155',
                  color: '#ef4444',
                  fontSize: '12px',
                  cursor: 'pointer'
                }}>
                Disconnect
              </button>
            </div>
          ) : (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <a
                id="btn-connect-google"
                href={getGoogleOAuthConnectUrl()}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '7px 12px',
                  borderRadius: '8px',
                  background: 'rgba(59, 130, 246, 0.15)',
                  border: '1px solid rgba(59, 130, 246, 0.4)',
                  color: '#60a5fa',
                  fontSize: '12px',
                  fontWeight: '500',
                  textDecoration: 'none',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease'
                }}>
                🔗 Sign in with Google
              </a>
              <button
                id="btn-quick-login"
                onClick={() => setShowQuickModal(true)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  padding: '7px 10px',
                  borderRadius: '8px',
                  background: '#1e293b',
                  border: '1px solid #334155',
                  color: '#cbd5e1',
                  fontSize: '12px',
                  cursor: 'pointer'
                }}>
                ⚡ Quick Gmail Login
              </button>
            </div>
          )}

          <a
            id="btn-export-ics"
            href={getCalendarExportUrl(activeDomain)}
            download="compass_schedule.ics"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '7px 12px',
              borderRadius: '8px',
              background: '#1e293b',
              border: '1px solid #334155',
              color: '#cbd5e1',
              fontSize: '12px',
              fontWeight: '500',
              textDecoration: 'none',
              cursor: 'pointer',
              transition: 'all 0.15s ease'
            }}>
            📥 Export .ics Feed
          </a>

          <button
            id="btn-check-slipped"
            onClick={handleCheckReactive}
            disabled={checkingReactive}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '7px 12px',
              borderRadius: '8px',
              background: 'rgba(245, 158, 11, 0.12)',
              border: '1px solid rgba(245, 158, 11, 0.35)',
              color: '#fbbf24',
              fontSize: '12px',
              fontWeight: '500',
              cursor: checkingReactive ? 'wait' : 'pointer',
              transition: 'all 0.15s ease'
            }}>
            {checkingReactive ? '🔄 Scanning...' : '⚡ Scan Schedule Slip'}
          </button>

          <button
            id="btn-auto-schedule"
            onClick={handleAutoSchedule}
            disabled={proposing}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '7px 14px',
              borderRadius: '8px',
              background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
              border: 'none',
              color: '#ffffff',
              fontSize: '12.5px',
              fontWeight: '600',
              cursor: proposing ? 'wait' : 'pointer',
              boxShadow: '0 0 14px rgba(99, 102, 241, 0.35)',
              opacity: proposing ? 0.7 : 1,
              transition: 'all 0.15s ease'
            }}>
            {proposing ? '⚡ Optimizing Slots...' : '⚡ Auto-Schedule Unplaced Tasks'}
          </button>
        </div>
      </div>

      {/* Status Notifications Banner */}
      {bannerMessage && (
        <div style={{
          padding: '10px 24px',
          background: bannerMessage.type === 'error' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.15)',
          borderBottom: bannerMessage.type === 'error' ? '1px solid rgba(239, 68, 68, 0.3)' : '1px solid rgba(16, 185, 129, 0.3)',
          color: bannerMessage.type === 'error' ? '#fca5a5' : '#86efac',
          fontSize: '12.5px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <span>{bannerMessage.text}</span>
          <button
            onClick={() => setBannerMessage(null)}
            style={{ background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: '14px' }}>
            ✕
          </button>
        </div>
      )}

      {/* Date Horizon Navigator */}
      <div style={{
        padding: '10px 24px',
        borderBottom: '1px solid #1e293b',
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        background: '#090d14',
        flexShrink: 0
      }}>
        <span style={{ fontSize: '12px', color: '#64748b', fontWeight: '600', marginRight: '8px' }}>
          HORIZON:
        </span>
        {dayTabs.map(tab => {
          const isSelected = selectedDate === tab.iso
          return (
            <button
              key={tab.iso}
              onClick={() => setSelectedDate(tab.iso)}
              style={{
                padding: '6px 14px',
                borderRadius: '8px',
                border: isSelected ? '1px solid #6366f1' : '1px solid #1e293b',
                background: isSelected ? 'rgba(99, 102, 241, 0.15)' : '#0d131f',
                color: isSelected ? '#a5b4fc' : '#94a3b8',
                fontSize: '12px',
                fontWeight: isSelected ? '600' : '500',
                cursor: 'pointer',
                transition: 'all 0.15s ease'
              }}>
              {tab.label} {tab.isToday && '•'}
            </button>
          )
        })}
      </div>

      {/* Main Grid & Task Allocation View */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden' }}>
        {/* Left Side: 08:00 - 20:00 Time Grid */}
        <div style={{
          flex: '1 1 70%',
          display: 'flex',
          flexDirection: 'column',
          borderRight: '1px solid #1e293b',
          overflowY: 'auto',
          position: 'relative'
        }}>
          <div style={{
            position: 'relative',
            minHeight: '720px',
            padding: '10px 20px 20px 70px',
            background: '#0b0f17'
          }}>
            {/* Hour Markers */}
            {HOURS.map((hour) => (
              <div
                key={hour}
                style={{
                  height: '60px',
                  borderTop: '1px solid #1e293b',
                  position: 'relative'
                }}>
                <span style={{
                  position: 'absolute',
                  left: '-55px',
                  top: '-9px',
                  fontSize: '11px',
                  color: '#475569',
                  fontFamily: 'JetBrains Mono, monospace'
                }}>
                  {String(hour).padStart(2, '0')}:00
                </span>
              </div>
            ))}

            {/* External Google Calendar Busy Blocks */}
            {externalEventsForDay.map(ev => {
              const pos = getEventPosition(ev.start, ev.end)
              return (
                <div
                  key={ev.id}
                  style={{
                    position: 'absolute',
                    left: '80px',
                    right: '20px',
                    top: pos.top,
                    height: pos.height,
                    background: 'rgba(30, 41, 59, 0.75)',
                    border: '1px dashed #475569',
                    borderRadius: '6px',
                    padding: '6px 12px',
                    color: '#94a3b8',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center',
                    zIndex: 2,
                    backdropFilter: 'blur(4px)'
                  }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ fontSize: '11px' }}>📅 Google Calendar:</span>
                    <strong style={{ fontSize: '12px', color: '#e2e8f0' }}>{ev.title}</strong>
                  </div>
                  <span style={{ fontSize: '10.5px', color: '#64748b', fontFamily: 'JetBrains Mono, monospace' }}>
                    {ev.start.slice(11, 16)} - {ev.end.slice(11, 16)} UTC (Busy Window)
                  </span>
                </div>
              )
            })}

            {/* Scheduled Compass Tasks */}
            {scheduledForSelectedDay.map(task => {
              const pos = getEventPosition(task.scheduled_start, task.scheduled_end)
              const style = DOMAIN_STYLES[task.domain] || DOMAIN_STYLES.general
              return (
                <div
                  key={task.id}
                  style={{
                    position: 'absolute',
                    left: '90px',
                    right: '30px',
                    top: pos.top,
                    height: pos.height,
                    background: style.bg,
                    border: style.border,
                    borderRadius: '8px',
                    padding: '8px 14px',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                    zIndex: 4,
                    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.3)',
                    transition: 'transform 0.15s ease'
                  }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span className={style.badgeClass} style={{ padding: '2px 8px', borderRadius: '4px', fontSize: '10.5px', fontWeight: '700' }}>
                        {task.domain.toUpperCase()}
                      </span>
                      <strong style={{ fontSize: '13px', color: '#f8fafc' }}>{task.title}</strong>
                    </div>
                    <span style={{
                      fontSize: '11px',
                      color: '#10b981',
                      fontWeight: '600',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px'
                    }}>
                      ✓ Synced
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '4px' }}>
                    <span style={{ fontSize: '11px', color: style.text, fontFamily: 'JetBrains Mono, monospace' }}>
                      ⏰ {task.scheduled_start.slice(11, 16)} → {task.scheduled_end.slice(11, 16)} UTC ({task.duration_minutes || 60}m)
                    </span>
                    {task.project && (
                      <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                        📁 {task.project}
                      </span>
                    )}
                    <span style={{ fontSize: '11px', color: '#64748b' }}>
                      Prio: {task.priority || 'medium'}
                    </span>
                  </div>
                </div>
              )
            })}

            {scheduledForSelectedDay.length === 0 && externalEventsForDay.length === 0 && (
              <div style={{
                position: 'absolute',
                top: '35%',
                left: '50%',
                transform: 'translate(-50%, -50%)',
                textAlign: 'center',
                color: '#475569'
              }}>
                <div style={{ fontSize: '32px', marginBottom: '8px' }}>🗓️</div>
                <p style={{ fontSize: '14px', fontWeight: '500' }}>No tasks or events scheduled for this day</p>
                <p style={{ fontSize: '12px', marginTop: '4px' }}>Click "Auto-Schedule Unplaced Tasks" to automatically place open tasks into working hours.</p>
              </div>
            )}
          </div>
        </div>

        {/* Right Side: Unscheduled Tasks & Working Constraints */}
        <div style={{
          flex: '0 0 30%',
          minWidth: '280px',
          display: 'flex',
          flexDirection: 'column',
          background: '#0d131f',
          padding: '16px',
          overflowY: 'auto'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h3 style={{ fontSize: '13px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#94a3b8', fontWeight: '700' }}>
              Pending Tasks ({unscheduledTasks.length})
            </h3>
            <span style={{ fontSize: '11px', color: '#64748b' }}>Unscheduled</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '20px' }}>
            {unscheduledTasks.map(task => {
              const style = DOMAIN_STYLES[task.domain] || DOMAIN_STYLES.general
              return (
                <div
                  key={task.id}
                  style={{
                    padding: '10px 12px',
                    borderRadius: '8px',
                    background: '#131c2e',
                    border: '1px solid #1e293b',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '4px'
                  }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <span style={{ fontSize: '12.5px', color: '#f1f5f9', fontWeight: '500' }}>
                      {task.title}
                    </span>
                    <span className={style.badgeClass} style={{ padding: '1px 6px', borderRadius: '4px', fontSize: '10px', fontWeight: '700' }}>
                      {task.domain}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px' }}>
                    <span style={{ fontSize: '11px', color: '#64748b' }}>
                      ⏱️ {task.duration_minutes || 60}m · {task.priority || 'medium'}
                    </span>
                    <span style={{ fontSize: '11px', color: '#f59e0b' }}>
                      {task.countdown || 'Needs slot'}
                    </span>
                  </div>
                </div>
              )
            })}

            {unscheduledTasks.length === 0 && (
              <div style={{
                padding: '24px 16px',
                textAlign: 'center',
                color: '#64748b',
                background: '#131c2e',
                borderRadius: '8px',
                border: '1px dashed #1e293b'
              }}>
                <span style={{ fontSize: '20px' }}>🎉</span>
                <p style={{ fontSize: '12px', marginTop: '6px' }}>All tasks are scheduled into calendar time slots!</p>
              </div>
            )}
          </div>

          {/* Allocation Rules & Constraints Widget */}
          <div style={{
            marginTop: 'auto',
            padding: '14px',
            borderRadius: '8px',
            background: 'rgba(99, 102, 241, 0.05)',
            border: '1px solid rgba(99, 102, 241, 0.2)'
          }}>
            <h4 style={{ fontSize: '12px', fontWeight: '700', color: '#a5b4fc', marginBottom: '8px' }}>
              ⚙️ Deterministic Policy
            </h4>
            <ul style={{ fontSize: '11px', color: '#94a3b8', lineHeight: '1.6', paddingLeft: '14px' }}>
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
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0, 0, 0, 0.75)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
          backdropFilter: 'blur(5px)'
        }}>
          <div style={{
            width: '580px',
            maxWidth: '90vw',
            background: '#0d131f',
            borderRadius: '12px',
            border: '1px solid #334155',
            boxShadow: '0 20px 40px rgba(0, 0, 0, 0.6)',
            padding: '24px',
            display: 'flex',
            flexDirection: 'column',
            gap: '16px'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ fontSize: '16px', fontWeight: '700', color: '#f8fafc' }}>
                ⚡ Review Proposed Schedule Allocation
              </h3>
              <button
                onClick={() => setProposedPlan(null)}
                style={{ background: 'transparent', border: 'none', color: '#64748b', fontSize: '16px', cursor: 'pointer' }}>
                ✕
              </button>
            </div>

            <p style={{ fontSize: '13px', color: '#94a3b8', lineHeight: '1.5' }}>
              {proposedPlan.summary}
            </p>

            <div style={{
              maxHeight: '260px',
              overflowY: 'auto',
              display: 'flex',
              flexDirection: 'column',
              gap: '8px',
              background: '#090d14',
              padding: '12px',
              borderRadius: '8px',
              border: '1px solid #1e293b'
            }}>
              {proposedPlan.scheduled && proposedPlan.scheduled.map(s => (
                <div
                  key={s.task_id}
                  style={{
                    padding: '8px 12px',
                    borderRadius: '6px',
                    background: '#131c2e',
                    border: '1px solid #1e293b',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center'
                  }}>
                  <div>
                    <strong style={{ fontSize: '12.5px', color: '#f8fafc' }}>{s.title}</strong>
                    <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>
                      Domain: {s.domain} · Duration: {s.duration_minutes}m
                    </div>
                  </div>
                  <span style={{ fontSize: '11.5px', color: '#a5b4fc', fontFamily: 'JetBrains Mono, monospace', fontWeight: '600' }}>
                    {s.scheduled_start.slice(0, 10)} {s.scheduled_start.slice(11, 16)} → {s.scheduled_end.slice(11, 16)}
                  </span>
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '8px' }}>
              <button
                onClick={() => setProposedPlan(null)}
                style={{
                  padding: '8px 16px',
                  borderRadius: '8px',
                  background: '#1e293b',
                  border: '1px solid #334155',
                  color: '#94a3b8',
                  fontSize: '13px',
                  cursor: 'pointer'
                }}>
                Cancel
              </button>
              <button
                id="btn-confirm-commit-schedule"
                onClick={handleCommitPlan}
                disabled={committing}
                style={{
                  padding: '8px 20px',
                  borderRadius: '8px',
                  background: 'linear-gradient(135deg, #10b981, #059669)',
                  border: 'none',
                  color: '#ffffff',
                  fontSize: '13px',
                  fontWeight: '600',
                  cursor: committing ? 'wait' : 'pointer',
                  boxShadow: '0 0 12px rgba(16, 185, 129, 0.4)'
                }}>
                {committing ? 'Committing...' : '✅ Approve & Commit to Google Calendar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Quick Gmail Login Modal */}
      {showQuickModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0, 0, 0, 0.75)',
          backdropFilter: 'blur(4px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999
        }}>
          <div style={{
            background: '#131c2e',
            border: '1px solid #334155',
            borderRadius: '16px',
            padding: '28px',
            width: '100%',
            maxWidth: '420px',
            boxShadow: '0 20px 40px rgba(0,0,0,0.6)'
          }}>
            <h3 style={{ margin: '0 0 8px', color: '#f8fafc', fontSize: '18px' }}>⚡ Connect Your Gmail</h3>
            <p style={{ color: '#94a3b8', fontSize: '13px', margin: '0 0 20px', lineHeight: '1.5' }}>
              Enter your Google / Gmail address to activate your calendar profile. Scheduled tasks will be synchronized to your calendar.
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
                  fetchCalendarStatus().then(status => {
                    if (status) setCalendarStatus(status)
                  })
                  setBannerMessage({
                    type: 'success',
                    text: `✅ Connected as ${quickEmailInput}! Tasks will sync to your Google Calendar.`
                  })
                }
              }}
              style={{
                width: '100%',
                padding: '10px 14px',
                borderRadius: '8px',
                background: '#0f172a',
                border: '1px solid #334155',
                color: '#f8fafc',
                fontSize: '14px',
                marginBottom: '18px',
                boxSizing: 'border-box'
              }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button
                onClick={() => setShowQuickModal(false)}
                style={{
                  padding: '8px 16px',
                  borderRadius: '8px',
                  background: '#1e293b',
                  border: '1px solid #334155',
                  color: '#94a3b8',
                  fontSize: '13px',
                  cursor: 'pointer'
                }}>
                Cancel
              </button>
              <button
                id="btn-submit-quick-connect"
                disabled={!quickEmailInput.includes('@')}
                onClick={async () => {
                  try {
                    await quickConnectUser(quickEmailInput)
                    setShowQuickModal(false)
                    fetchCalendarStatus().then(status => {
                      if (status) setCalendarStatus(status)
                    })
                    setBannerMessage({
                      type: 'success',
                      text: `✅ Connected as ${quickEmailInput}! Tasks will sync to your Google Calendar.`
                    })
                  } catch (err) {
                    alert(`Could not connect: ${err.message}`)
                  }
                }}
                style={{
                  padding: '8px 18px',
                  borderRadius: '8px',
                  background: quickEmailInput.includes('@') ? 'linear-gradient(135deg, #2563eb, #3b82f6)' : '#334155',
                  border: 'none',
                  color: '#ffffff',
                  fontSize: '13px',
                  fontWeight: '600',
                  cursor: quickEmailInput.includes('@') ? 'pointer' : 'not-allowed'
                }}>
                Connect Account
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
