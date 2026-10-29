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
  deleteTask,
  safeHref,
  downloadAuthedFile,
} from '../api/client'

import {
  Calendar,
  RefreshCw,
  Zap,
  MoreHorizontal,
  Download,
  BookOpen,
  ExternalLink,
  Link2,
  LogOut,
  CheckCircle2,
  AlertCircle,
  Trash2,
  Clock,
  Settings,
  X,
} from 'lucide-react'
import { CalendarGrid } from './calendar/CalendarGrid'
import { CalendarSidebar } from './calendar/CalendarSidebar'
import { ProposedPlanModal, QuickConnectModal, IcsExportModal } from './calendar/CalendarModals'
import DarkModeToggle from './DarkModeToggle'
import { syncResultBanner, syncErrorBanner, commitResultBanner, reactiveResultBanner, availabilityNote } from '../utils/scheduleHonesty'

const DOMAIN_STYLES = {
  hackathon: {
    bg: 'var(--hackathon-bg)',
    border: '1px solid var(--border)',
    accent: '#f5a623',
    text: 'var(--text-primary)',
    badgeClass: 'badge-hackathon',
  },
  coursework: {
    bg: 'var(--coursework-bg)',
    border: '1px solid var(--border)',
    accent: '#2f64c8',
    text: 'var(--text-primary)',
    badgeClass: 'badge-coursework',
  },
  code: {
    bg: 'var(--code-bg)',
    border: '1px solid var(--border)',
    accent: '#1c8a62',
    text: 'var(--text-primary)',
    badgeClass: 'badge-code',
  },
  general: {
    bg: 'var(--general-bg)',
    border: '1px solid var(--border)',
    accent: '#6b7a86',
    text: 'var(--text-primary)',
    badgeClass: 'badge-general',
  },
  other: {
    bg: 'var(--bg-card-soft)',
    border: '1px solid var(--border)',
    accent: '#6b7a86',
    text: 'var(--text-primary)',
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

export default function CalendarView({
  tasks,
  activeDomain,
  onTasksUpdated,
  onOpenAuthModal,
  isSignedIn = true,
  isDarkMode,
  onToggleDarkMode,
}) {
  const [calendarStatus, setCalendarStatus] = useState({ connected: false, mode: 'demo', account_email: 'demo-scholar@compass.ai' })
  const [selectedDate, setSelectedDate] = useState(() => toIso(new Date()))
  const [monthCursor, setMonthCursor] = useState(() => new Date())
  const [busyIntervals, setBusyIntervals] = useState([])
  const [_loadingAvailability, setLoadingAvailability] = useState(false)
  const [proposing, setProposing] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [proposedPlan, setProposedPlan] = useState(null)
  const [bannerMessage, setBannerMessage] = useState(null)
  const [availabilityError, setAvailabilityError] = useState(null)
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
      // The ?email= value is untrusted; the verified account comes from fetchCalendarStatus below.
      setBannerMessage({
        type: 'success',
        text: 'Google Calendar connection finished. Verifying the connected account...'
      })
      window.history.replaceState({}, document.title, window.location.pathname)
    }

    if (urlParams.get('calendar_error')) {
      const rawError = urlParams.get('calendar_error')
      const errorMap = {
        access_denied: 'Google Calendar connection was cancelled or access denied.',
        missing_code: 'Google authorization code was missing.',
        missing_state: 'Security validation failed: missing OAuth state parameter.',
        invalid_state: 'Security validation failed: invalid or cross-user OAuth state. Please try connecting again.',
        expired_state: 'OAuth connection timed out. Please try connecting again.',
        replayed_state: 'This OAuth authorization was already processed. If you need to reconnect, please click Connect again.',
        token_exchange_failed: 'Failed to exchange authorization tokens with Google. Please try again.',
        database_error: 'Database error occurred while saving Google Calendar credentials. Please try again.',
        invalid_userinfo: 'Unable to retrieve verified profile email from Google.',
      }
      const desc = errorMap[rawError] || `Google Calendar connection failed (${rawError}).`
      setBannerMessage({
        type: 'error',
        text: desc
      })
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
      setAvailabilityError(availabilityNote(data))
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
      const result = await commitSchedule(assignments, proposedPlan.summary)
      setBannerMessage(commitResultBanner(result))
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
      setBannerMessage(reactiveResultBanner(res))
      if (res.slipped_count > 0 && onTasksUpdated) onTasksUpdated()
    } catch (e) {
      setBannerMessage({ type: 'error', text: `Error checking schedule slips: ${e.message}` })
    } finally {
      setCheckingReactive(false)
    }
  }

  const handleSyncNow = async () => {
    setBannerMessage(null)
    if (!isSignedIn) {
      setBannerMessage(syncErrorBanner(null, false))
      setShowMoreMenu(false)
      return
    }
    setSyncingCalendar(true)
    try {
      const res = await syncCalendarNow()
      const banner = syncResultBanner(res, calendarStatus.account_email)
      setBannerMessage(banner)
      if (Number(res.live_created ?? 0) === 0 && banner.type !== 'error') setShowIcsModal(true)
      loadAvailability(weekStart)
    } catch (err) {
      setBannerMessage(syncErrorBanner(err, true))
    } finally {
      setSyncingCalendar(false)
      setShowMoreMenu(false)
    }
  }

  const [exportingIcs, setExportingIcs] = useState(false)
  const handleExportIcs = async () => {
    if (exportingIcs) return
    setExportingIcs(true)
    try {
      const url = getCalendarExportUrl(activeDomain)
      await downloadAuthedFile(url, 'compass_schedule.ics')
    } catch (err) {
      setBannerMessage({ type: 'error', text: err.message || 'Failed to export calendar feed.' })
    } finally {
      setExportingIcs(false)
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

  const [mobileCalendarDrawerOpen, setMobileCalendarDrawerOpen] = useState(false)

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', background: 'var(--bg-app)' }}>
      {/* Top Header Bar: Google Calendar Style */}
      <div className="calendar-header-bar" style={{
        padding: '14px 20px', borderBottom: '1px solid var(--border)', background: 'var(--bg-card)',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap', minWidth: 0 }}>
            {/* Mobile Calendar Drawer Toggle Button */}
            <button
              id="btn-toggle-calendar-drawer"
              type="button"
              onClick={() => setMobileCalendarDrawerOpen(v => !v)}
              className="calendar-drawer-toggle-btn btn-touch-target btn-secondary"
              aria-label="Toggle Calendar Drawer"
              title="Open / Close Calendar"
              style={{
                display: 'none',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px',
                padding: '8px 12px',
                borderRadius: 'var(--radius-btn, 6px)',
                background: mobileCalendarDrawerOpen ? 'var(--bg-card-soft)' : 'var(--bg-card)',
                color: 'var(--text-primary)',
                fontWeight: '600',
                fontSize: '13px',
                cursor: 'pointer',
                minHeight: '44px',
              }}
            >
              <Calendar size={15} strokeWidth={1.8} />
              <span>{mobileCalendarDrawerOpen ? 'Hide Cal' : 'View Cal'}</span>
            </button>

            <h2 style={{ fontSize: '26px', fontWeight: '600', color: 'var(--text-primary)', letterSpacing: '-0.3px', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Calendar size={22} strokeWidth={1.8} style={{ color: 'var(--text-primary)' }} />
              <span>Schedule</span>
            </h2>
            <div
              onClick={() => { if (onOpenAuthModal) onOpenAuthModal(); else setShowQuickModal(true) }}
              title="Click to switch account or manage Google Calendar"
              style={{
                display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '6px 10px', borderRadius: 'var(--radius-btn, 6px)',
                background: 'var(--bg-card-soft)', border: '1px solid var(--border)',
                fontSize: '12px', color: 'var(--text-primary)',
                fontWeight: '500', cursor: 'pointer', maxWidth: '240px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                minHeight: '32px',
              }}>
              <span className="domain-swatch" style={{ width: '8px', height: '8px', borderRadius: '2px', background: isLive ? 'var(--code)' : 'var(--hackathon)', flexShrink: 0 }} />
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {isLive ? `${calendarStatus.account_email}` : (calendarStatus.account_email || 'demo')}
              </span>
            </div>
          </div>

          <DarkModeToggle
            isDarkMode={Boolean(isDarkMode)}
            onToggleDarkMode={onToggleDarkMode}
            id="calendar-theme-toggle"
          />
        </div>

        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', marginTop: '8px' }}>
          <p className="calendar-policy-subtext" style={{ fontSize: '13px', color: 'var(--text-muted)', margin: 0 }}>
            09:00 - 18:00 UTC · 15m buffer · deterministic allocation
          </p>

          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <button
              id="btn-check-slipped"
              onClick={handleCheckReactive}
              disabled={checkingReactive}
              className="btn-touch-target btn-primary-amber"
              style={{
                padding: '8px 14px', borderRadius: 'var(--radius-btn, 6px)',
                fontSize: '13px', fontWeight: '600', cursor: checkingReactive ? 'wait' : 'pointer',
                display: 'inline-flex', alignItems: 'center', gap: '6px',
                minHeight: '44px',
              }}>
              {checkingReactive ? <RefreshCw size={14} strokeWidth={1.8} className="animate-spin" /> : <Zap size={14} strokeWidth={1.8} />}
              <span>{checkingReactive ? 'Scanning...' : 'Scan Slip'}</span>
            </button>

            <div ref={moreMenuRef} style={{ position: 'relative' }}>
              <button
                onClick={() => setShowMoreMenu(v => !v)}
                className="btn-touch-target btn-secondary"
                aria-label="More options"
                style={{
                  padding: '8px 12px', borderRadius: 'var(--radius-btn, 6px)',
                  fontSize: '13px', fontWeight: '600', cursor: 'pointer',
                  minHeight: '44px', minWidth: '44px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center'
                }}>
                <MoreHorizontal size={16} strokeWidth={1.8} />
              </button>
              {showMoreMenu && (
                <div style={{
                  position: 'absolute', top: '110%', right: 0, background: 'var(--bg-card)', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-card, 8px)', boxShadow: '0 4px 12px rgba(0,0,0,0.08)', width: '240px', padding: '6px', zIndex: 50
                }}>
                  <button
                    id="btn-sync-gcal"
                    onClick={handleSyncNow}
                    disabled={syncingCalendar}
                    style={{ ...menuItemStyle, display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Calendar size={14} strokeWidth={1.8} />
                    <span>{syncingCalendar ? 'Syncing...' : (isLive ? 'Sync to Google Calendar' : (calendarStatus.is_simulated ? 'Sync Tasks (Simulated)' : 'Slot / Sync Tasks'))}</span>
                  </button>
                  <button
                    id="btn-export-ics"
                    type="button"
                    disabled={exportingIcs}
                    onClick={handleExportIcs}
                    style={{ ...menuItemStyle, border: 'none', background: 'transparent', textAlign: 'left', width: '100%', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px' }}
                  >
                    <Download size={14} strokeWidth={1.8} />
                    <span>{exportingIcs ? 'Exporting…' : 'Export .ics Feed'}</span>
                  </button>
                  <button onClick={() => { setShowIcsModal(true); setShowMoreMenu(false) }} style={{ ...menuItemStyle, display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <BookOpen size={14} strokeWidth={1.8} />
                    <span>Sync Guide</span>
                  </button>
                  <div style={{ height: '1px', background: 'var(--border-soft)', margin: '4px 0' }} />
                  {calendarStatus.connected ? (
                    <>
                      <a href="https://calendar.google.com" target="_blank" rel="noreferrer" style={{ ...menuItemStyle, textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <ExternalLink size={14} strokeWidth={1.8} />
                        <span>Open Google Calendar ↗</span>
                      </a>
                      {!isLive && (
                        <a id="btn-connect-google" href={safeHref(getGoogleOAuthConnectUrl())} style={{ ...menuItemStyle, textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <Link2 size={14} strokeWidth={1.8} />
                          <span>Sign in with Google</span>
                        </a>
                      )}

                      <button id="btn-disconnect-google" onClick={handleDisconnect} style={{ ...menuItemStyle, color: '#dc2626', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <LogOut size={14} strokeWidth={1.8} />
                        <span>Disconnect</span>
                      </button>
                    </>
                  ) : (
                    <>
                      <button id="btn-connect-google" onClick={() => { if (onOpenAuthModal) onOpenAuthModal(); else setShowQuickModal(true); setShowMoreMenu(false) }} style={{ ...menuItemStyle, display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Link2 size={14} strokeWidth={1.8} />
                        <span>Connect Google Calendar</span>
                      </button>
                      <button id="btn-quick-login" onClick={() => { if (onOpenAuthModal) onOpenAuthModal(); else setShowQuickModal(true); setShowMoreMenu(false) }} style={{ ...menuItemStyle, display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Zap size={14} strokeWidth={1.8} />
                        <span>Switch Account</span>
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Status Notifications Banner */}
      {bannerMessage && (
        <div style={{
          padding: '10px 16px',
          margin: '12px 16px 0 16px',
          borderRadius: 'var(--radius-card, 8px)',
          border: '1px solid var(--border)',
          background: bannerMessage.type === 'error' ? 'var(--danger-bg)' : 'var(--bg-card)',
          color: bannerMessage.type === 'error' ? 'var(--danger-text, #b91c1c)' : 'var(--text-primary)',
          fontSize: '13px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {bannerMessage.type === 'error' || bannerMessage.type === 'warning' ? (
              <AlertCircle size={16} strokeWidth={1.8} style={{ color: 'var(--danger-text, #b91c1c)', flexShrink: 0 }} />
            ) : (
              <CheckCircle2 size={16} strokeWidth={1.8} style={{ color: 'var(--domain-code, #1c8a62)', flexShrink: 0 }} />
            )}
            <span>{bannerMessage.text}</span>
          </div>
          <button
            onClick={() => setBannerMessage(null)}
            aria-label="Dismiss banner"
            style={{ background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer', padding: '4px', display: 'flex', alignItems: 'center' }}
          >
            <X size={14} strokeWidth={1.8} />
          </button>
        </div>
      )}

      {availabilityError && (
        <div role="status" id="calendar-availability-error" style={{ margin: '8px 16px 0 16px', fontSize: '12px', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
          <AlertCircle size={13} strokeWidth={1.8} style={{ flexShrink: 0 }} />
          <span>{availabilityError}</span>
        </div>
      )}

      {/* Mobile Calendar Drawer Overlay / Modal */}
      {mobileCalendarDrawerOpen && (
        <div className="mobile-calendar-drawer-backdrop" onClick={() => setMobileCalendarDrawerOpen(false)}>
          <div className="mobile-calendar-drawer-content" onClick={e => e.stopPropagation()} style={{ borderRadius: 'var(--radius-card, 8px)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px', borderBottom: '1px solid var(--border)', paddingBottom: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Calendar size={18} strokeWidth={1.8} style={{ color: 'var(--text-primary)' }} />
                <h3 style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)', margin: 0 }}>Calendar Picker & Overview</h3>
              </div>
              <button
                type="button"
                onClick={() => setMobileCalendarDrawerOpen(false)}
                className="btn-touch-target btn-secondary"
                style={{
                  width: '36px', height: '36px', minHeight: '36px', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: 'var(--text-secondary)', cursor: 'pointer', borderRadius: 'var(--radius-btn, 6px)'
                }}
              >
                <X size={16} strokeWidth={1.8} />
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <CalendarSidebar
                monthCursor={monthCursor}
                setMonthCursor={setMonthCursor}
                monthDays={monthDays}
                selectedDate={selectedDate}
                setSelectedDate={(date) => {
                  setSelectedDate(date)
                  setMobileCalendarDrawerOpen(false)
                }}
                selectedDateObj={selectedDateObj}
                today={today}
                scheduledDateSet={scheduledDateSet}
                scheduledForDay={scheduledForDay}
                getCalendarDomainStyle={getCalendarDomainStyle}
                toIso={toIso}
                isSameDay={isSameDay}
              />
              <div style={{ marginTop: '8px', borderTop: '1px solid var(--border-soft)', paddingTop: '14px' }}>
                <div style={{ fontSize: '12px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '10px' }}>Week Grid View</div>
                <div style={{ minHeight: '340px' }}>
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
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Google Calendar Layout:
          DESKTOP: Left: Compact Calendar (Sidebar, max-width: 300px) | Right: Tasks/Events & Schedule (flex: 1)
          MOBILE: Calendar is hidden in drawer; Main Content (Tasks/Events) is full width and primary!
      */}
      <div className="calendar-google-layout" style={{ flex: 1, display: 'flex', gap: '16px', padding: '16px', overflow: 'hidden', minHeight: 0 }}>
        {/* Left: Compact Calendar (Secondary on Desktop, max-width: 300px, hidden on mobile) */}
        <aside className="calendar-left-sidebar" style={{ width: '280px', maxWidth: '300px', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: '14px', overflowY: 'auto' }}>
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
        </aside>

        {/* Center/Right: Primary Content (Tasks & Events - flex: 1, full width on mobile) */}
        <main className="calendar-main-content" style={{ flex: 1, display: 'flex', gap: '16px', minWidth: 0, overflow: 'hidden' }}>
          {/* Calendar week/agenda grid view */}
          <section className="calendar-grid-section" style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
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
          </section>

          {/* Tasks & Policy column: visible directly beside grid on desktop, or stacked full width on tablet/mobile */}
          <section className="calendar-tasks-section" style={{ width: '320px', flexShrink: 0, display: 'flex', flexDirection: 'column', background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-card, 8px)', padding: '16px', overflowY: 'auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <h3 style={{ fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-primary)', fontWeight: '600' }}>
                Pending Tasks ({unscheduledTasks.length})
              </h3>
              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Unscheduled</span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '20px' }}>
              {unscheduledTasks.map(task => {
                const s = getCalendarDomainStyle(task.domain)
                return (
                  <div key={task.id} style={{ padding: '12px 14px', borderRadius: 'var(--radius-card, 8px)', background: 'var(--bg-card)', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <span style={{ fontSize: '13px', color: 'var(--text-primary)', fontWeight: '600' }}>{task.title}</span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', fontSize: '11px', color: 'var(--text-primary)', fontWeight: '500' }}>
                          <span className="domain-swatch" style={{ background: s.accent }} />
                          <span>{task.domain}</span>
                        </span>
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
                          style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '4px', borderRadius: 'var(--radius-btn, 6px)', display: 'flex', alignItems: 'center' }}
                          onMouseEnter={e => e.currentTarget.style.color = 'var(--danger-text)'}
                          onMouseLeave={e => e.currentTarget.style.color = 'var(--text-muted)'}
                        ><Trash2 size={13} strokeWidth={1.8} /></button>
                      </div>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px' }}>
                      <span style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <Clock size={11} strokeWidth={1.8} />
                        <span>{task.duration_minutes || 60}m · {task.priority || 'medium'}</span>
                      </span>
                      <span style={{ fontSize: '12px', color: 'var(--accent)', fontWeight: '600' }}>{task.countdown || 'Needs slot'}</span>
                    </div>
                  </div>
                )
              })}

              {unscheduledTasks.length === 0 && (
                <div style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--text-muted)', background: 'var(--bg-card-soft)', borderRadius: 'var(--radius-card, 8px)', border: '1px dashed var(--border)' }}>
                  <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '8px' }}>
                    <CheckCircle2 size={24} strokeWidth={1.8} style={{ color: 'var(--code)' }} />
                  </div>
                  <p style={{ fontSize: '13px', margin: 0, color: 'var(--text-primary)', fontWeight: '500' }}>{(tasks || []).length > 0 ? 'All tasks are scheduled into calendar time slots!' : 'No pending tasks.'}</p>
                </div>
              )}
            </div>

            <div style={{ marginTop: 'auto', padding: '14px', borderRadius: 'var(--radius-card, 8px)', background: 'var(--bg-card-soft)', border: '1px solid var(--border)' }}>
              <h4 style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Settings size={14} strokeWidth={1.8} />
                <span>Deterministic Policy</span>
              </h4>
              <ul style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: '1.6', paddingLeft: '16px', margin: 0 }}>
                <li>Working Window: 09:00 - 18:00 UTC</li>
                <li>Days: Monday - Friday (workdays)</li>
                <li>Inter-task buffer: 15 minutes</li>
                <li>Deterministic slot allocator</li>
                <li>Export as .ics (RFC 5545)</li>
              </ul>
            </div>
          </section>
        </main>
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