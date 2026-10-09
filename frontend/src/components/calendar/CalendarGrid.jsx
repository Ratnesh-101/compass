import React from 'react'

const pillBtnStyle = {
  padding: '6px 12px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)',
  color: 'var(--text-secondary)', fontSize: '12px', fontWeight: '600', cursor: 'pointer'
}
const iconBtnStyle = {
  background: 'none', border: 'none', cursor: 'pointer', fontSize: '15px', color: 'var(--text-secondary)', padding: '2px 6px'
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
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '14px', overflow: 'hidden', boxShadow: 'var(--shadow-sm)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button onClick={() => setSelectedDate(toIso(today))} className="btn-touch-target" style={{ ...pillBtnStyle, minHeight: '38px', padding: '6px 14px' }}>Today</button>
          <button onClick={() => setSelectedDate(toIso(addDays(selectedDateObj, -7)))} className="btn-touch-target" style={{ ...iconBtnStyle, minWidth: '38px', minHeight: '38px', fontSize: '18px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>‹</button>
          <button onClick={() => setSelectedDate(toIso(addDays(selectedDateObj, 7)))} className="btn-touch-target" style={{ ...iconBtnStyle, minWidth: '38px', minHeight: '38px', fontSize: '18px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>›</button>
          <div style={{ fontSize: '14px', fontWeight: '700', color: 'var(--text-primary)' }}>{weekLabel}</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{ display: 'flex', border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden' }}>
            {['week', 'agenda'].map(m => (
              <button key={m} onClick={() => setViewMode(m)} className="btn-touch-target" style={{
                padding: '6px 14px', border: 'none', cursor: 'pointer', fontSize: '12px', fontWeight: '600',
                background: viewMode === m ? 'var(--coursework)' : 'var(--bg-card)',
                color: viewMode === m ? '#fff' : 'var(--text-secondary)', textTransform: 'capitalize'
              }}>{m}</button>
            ))}
          </div>
          <button
            id="btn-auto-schedule"
            onClick={handleAutoSchedule}
            disabled={proposing}
            className="btn-touch-target"
            style={{
              padding: '8px 16px', borderRadius: '8px', border: 'none',
              background: 'linear-gradient(135deg, #6c5ce7, #8b5cf6)', color: '#fff',
              fontSize: '12.5px', fontWeight: '700', cursor: proposing ? 'wait' : 'pointer',
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
              const isCurrToday = isSameDay(d, today)
              const iso = toIso(d)
              return (
                <div key={i} onClick={() => setSelectedDate(iso)} style={{
                  padding: '8px 6px', textAlign: 'center', borderLeft: '1px solid var(--border-soft)', cursor: 'pointer',
                  background: iso === selectedDate ? 'var(--coursework-bg)' : 'transparent'
                }}>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: '600' }}>{d.toLocaleDateString('en-US', { weekday: 'short' })}</div>
                  <div style={{
                    fontSize: '13px', fontWeight: '700', color: isCurrToday ? 'var(--coursework)' : 'var(--text-primary)',
                    width: '24px', height: '24px', borderRadius: '50%', margin: '2px auto 0',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    background: isCurrToday ? 'var(--coursework-bg)' : 'transparent'
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
                    const isSimulated = !isLive || ev.is_simulated || ev.source === 'google_calendar_simulated' || (ev.title && (ev.title.includes('(demo simulation)') || ev.title.includes('demo')))
                    return (
                      <div key={ev.id} style={{
                        position: 'absolute', left: '3px', right: '3px', top: pos.top, height: pos.height,
                        background: isSimulated ? 'rgba(245, 166, 35, 0.08)' : 'rgba(31,27,46,0.04)',
                        border: isSimulated ? '1px dashed #f5a623' : '1px dashed var(--border)',
                        borderRadius: '6px',
                        padding: '3px 6px', overflow: 'hidden', zIndex: 2
                      }}>
                        <div style={{ fontSize: '9.5px', color: isSimulated ? '#b45309' : 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px', flexWrap: 'wrap' }}>
                          <span>📅 {ev.title}</span>
                          {isSimulated && (
                            <span style={{ fontSize: '8px', padding: '1px 4px', borderRadius: '4px', background: '#fef3c7', color: '#b45309', fontWeight: '700' }}>
                              Simulated
                            </span>
                          )}
                        </div>
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
  )
}
