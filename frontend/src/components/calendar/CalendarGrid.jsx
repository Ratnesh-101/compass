import React from 'react'
import { ChevronLeft, ChevronRight, Zap, RefreshCw, Calendar, Check, Clock } from 'lucide-react'
import { formatLocalTime, localDateKey, minutesSinceLocalMidnight, parseApiInstant } from '../../utils/localTime'

function getLocalEventPosition(startIso, endIso) {
  try {
    const startMinutes = minutesSinceLocalMidnight(startIso)
    const endMinutes = minutesSinceLocalMidnight(endIso)
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

const iconBtnStyle = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  cursor: 'pointer',
  color: 'var(--text-secondary)',
  padding: '6px',
  borderRadius: 'var(--radius-btn, 6px)',
  minWidth: '44px',
  minHeight: '44px',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center'
}

export function CalendarGrid({
  viewMode,
  setViewMode,
  selectedDate,
  setSelectedDate,
  selectedDateObj,
  today,
  weekLabel,
  weekDays,
  handleAutoSchedule,
  proposing,
  HOURS,
  HOUR_ROW_HEIGHT,
  scheduledForDay,
  externalEventsForDay,
  getEventPosition,
  getCalendarDomainStyle,
  isLive,
  allScheduledTasks,
  toIso,
  addDays,
  isSameDay,
}) {
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-card, 8px)', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            onClick={() => setSelectedDate(toIso(today))}
            className="btn-touch-target btn-secondary"
            style={{ borderRadius: 'var(--radius-btn, 6px)', minHeight: '44px', padding: '8px 14px', fontSize: '13px', fontWeight: '500' }}>
            Today
          </button>
          <button
            onClick={() => setSelectedDate(toIso(addDays(selectedDateObj, -7)))}
            className="btn-touch-target"
            aria-label="Previous Week"
            style={iconBtnStyle}>
            <ChevronLeft size={16} strokeWidth={1.8} />
          </button>
          <button
            onClick={() => setSelectedDate(toIso(addDays(selectedDateObj, 7)))}
            className="btn-touch-target"
            aria-label="Next Week"
            style={iconBtnStyle}>
            <ChevronRight size={16} strokeWidth={1.8} />
          </button>
          <div style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)', marginLeft: '4px' }}>{weekLabel}</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{ display: 'flex', border: '1px solid var(--border)', borderRadius: 'var(--radius-btn, 6px)', overflow: 'hidden' }}>
            {['week', 'agenda'].map(m => (
              <button
                key={m}
                onClick={() => setViewMode(m)}
                className="btn-touch-target"
                style={{
                  padding: '8px 14px',
                  border: 'none',
                  cursor: 'pointer',
                  fontSize: '13px',
                  fontWeight: '500',
                  minHeight: '44px',
                  background: viewMode === m ? 'var(--bg-card-soft)' : 'var(--bg-card)',
                  color: viewMode === m ? 'var(--text-primary)' : 'var(--text-muted)',
                  textTransform: 'capitalize'
                }}>
                {m}
              </button>
            ))}
          </div>
          <button
            id="btn-auto-schedule"
            onClick={handleAutoSchedule}
            disabled={proposing}
            className="btn-touch-target btn-secondary"
            style={{
              padding: '8px 16px',
              borderRadius: 'var(--radius-btn, 6px)',
              fontSize: '13px',
              fontWeight: '600',
              cursor: proposing ? 'wait' : 'pointer',
              opacity: proposing ? 0.7 : 1,
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              minHeight: '44px',
            }}>
            {proposing ? <RefreshCw size={14} strokeWidth={1.8} className="animate-spin" /> : <Zap size={14} strokeWidth={1.8} />}
            <span>{proposing ? 'Optimizing…' : 'Auto-Schedule'}</span>
          </button>
        </div>
      </div>

      {viewMode === 'week' ? (
        <div style={{ flex: 1, overflow: 'auto' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '48px repeat(7, 1fr)', borderBottom: '1px solid var(--border)', position: 'sticky', top: 0, background: 'var(--bg-card)', zIndex: 1 }}>
            <div />
            {weekDays.map((d, i) => {
              const isCurrToday = isSameDay(d, today)
              const iso = toIso(d)
              return (
                <div key={i} onClick={() => setSelectedDate(iso)} style={{
                  padding: '8px 6px', textAlign: 'center', borderLeft: '1px solid var(--border-soft)', cursor: 'pointer',
                  background: iso === selectedDate ? 'var(--bg-card-soft)' : 'transparent'
                }}>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '500' }}>{d.toLocaleDateString('en-US', { weekday: 'short' })}</div>
                  <div style={{
                    fontSize: '13px', fontWeight: '600', color: isCurrToday ? 'var(--accent)' : 'var(--text-primary)',
                    width: '26px', height: '26px', borderRadius: 'var(--radius-btn, 6px)', margin: '2px auto 0',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    background: isCurrToday ? 'var(--bg-card-soft)' : 'transparent',
                    border: isCurrToday ? '1px solid var(--accent)' : 'none'
                  }}>{d.getDate()}</div>
                </div>
              )
            })}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '48px repeat(7, 1fr)', position: 'relative' }}>
            <div>
              {HOURS.map(h => (
                <div key={h} style={{ height: `${HOUR_ROW_HEIGHT}px`, textAlign: 'right', paddingRight: '6px', fontSize: '11px', color: 'var(--text-muted)', transform: 'translateY(-6px)', fontFamily: 'inherit' }}>
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
                    const pos = (ev.start && ev.end) ? getLocalEventPosition(ev.start, ev.end) : getEventPosition(ev.start, ev.end)
                    const isSimulated = !isLive || ev.is_simulated || ev.source === 'google_calendar_simulated' || (ev.title && (ev.title.includes('(demo simulation)') || ev.title.includes('demo')))
                    return (
                      <div key={ev.id} style={{
                        position: 'absolute', left: '3px', right: '3px', top: pos.top, height: pos.height,
                        background: isSimulated ? 'var(--bg-card-soft)' : 'var(--bg-card-soft)',
                        border: isSimulated ? '1px dashed var(--accent)' : '1px dashed var(--border)',
                        borderRadius: 'var(--radius-btn, 6px)',
                        padding: '3px 6px', overflow: 'hidden', zIndex: 2
                      }}>
                        <div style={{ fontSize: '11px', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px', flexWrap: 'wrap' }}>
                          <Calendar size={11} strokeWidth={1.8} />
                          <span>{ev.title}</span>
                          {isSimulated && (
                            <span style={{ fontSize: '10px', padding: '1px 4px', borderRadius: 'var(--radius-btn, 4px)', background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-muted)', fontWeight: '500' }}>
                              Simulated
                            </span>
                          )}
                        </div>
                      </div>
                    )
                  })}

                  {dayEvents.map(t => {
                    const pos = (t.scheduled_start && t.scheduled_end) ? getLocalEventPosition(t.scheduled_start, t.scheduled_end) : getEventPosition(t.scheduled_start, t.scheduled_end)
                    const s = getCalendarDomainStyle(t.domain)
                    return (
                      <div key={t.id} style={{
                        position: 'absolute', left: '3px', right: '3px', top: pos.top, height: pos.height,
                        background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-btn, 6px)', padding: '4px 6px',
                        overflow: 'hidden', zIndex: 4, display: 'flex', flexDirection: 'column', justifyContent: 'center'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <span className="domain-swatch" style={{ background: s.accent, width: '6px', height: '6px' }} />
                          <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {t.title}
                          </span>
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px', marginTop: '1px' }}>
                          <span>{formatLocalTime(t.scheduled_start)}</span>
                          {isLive ? <Check size={10} strokeWidth={1.8} /> : <Clock size={10} strokeWidth={1.8} />}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )
            })}
          </div>

          {allScheduledTasks.filter(t => weekDays.some(d => toIso(d) === localDateKey(t.scheduled_start))).length === 0 && (
            <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)' }}>
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '8px' }}>
                <Calendar size={28} strokeWidth={1.8} style={{ color: 'var(--text-muted)' }} />
              </div>
              <p style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)' }}>No tasks or events scheduled this week</p>
              <p style={{ fontSize: '13px', marginTop: '4px' }}>Click "Auto-Schedule" to automatically place open tasks into working hours.</p>
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
                .sort((a, b) => {
                  const ta = parseApiInstant(a.scheduled_start)?.getTime() || 0
                  const tb = parseApiInstant(b.scheduled_start)?.getTime() || 0
                  return ta - tb
                })
                .map(t => {
                  const s = getCalendarDomainStyle(t.domain)
                  const start = parseApiInstant(t.scheduled_start)
                  return (
                    <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: '14px', padding: '12px 14px', background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-card, 8px)' }}>
                      <div style={{ width: '70px', flexShrink: 0, textAlign: 'center' }}>
                        <div style={{ fontSize: '12px', color: 'var(--text-primary)', fontWeight: '600' }}>{start ? start.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : ''}</div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{formatLocalTime(t.scheduled_start)}</div>
                      </div>
                      <span className="domain-swatch" style={{ background: s.accent }} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>{t.title}</div>
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t.domain} · {t.duration_minutes || 60}min</div>
                      </div>
                    </div>
                  )
                })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
