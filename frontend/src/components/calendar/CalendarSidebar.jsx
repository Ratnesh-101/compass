import React from 'react'

const iconBtnStyle = {
  background: 'none', border: 'none', cursor: 'pointer', fontSize: '15px', color: 'var(--text-secondary)', padding: '2px 6px'
}

export function CalendarSidebar({
  monthCursor,
  setMonthCursor,
  monthDays,
  selectedDate,
  setSelectedDate,
  selectedDateObj,
  today,
  scheduledDateSet,
  scheduledForDay,
  getCalendarDomainStyle,
  toIso,
  isSameDay,
}) {
  return (
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
  )
}
