import React from 'react'
import { ChevronLeft, ChevronRight, Clock } from 'lucide-react'

const iconBtnStyle = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  color: 'var(--text-secondary)',
  padding: '6px',
  borderRadius: 'var(--radius-btn, 6px)',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  minWidth: '44px',
  minHeight: '44px',
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
  const isCurrentMonth = Boolean(
    today &&
    monthCursor &&
    monthCursor.getFullYear() === today.getFullYear() &&
    monthCursor.getMonth() === today.getMonth()
  )

  return (
    <div style={{ width: '270px', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: '14px', overflowY: 'auto' }}>
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-card, 8px)', padding: '14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
          <button
            onClick={() => setMonthCursor(new Date(monthCursor.getFullYear(), monthCursor.getMonth() - 1, 1))}
            className="btn-touch-target"
            aria-label="Previous Month"
            style={iconBtnStyle}
          >
            <ChevronLeft size={16} strokeWidth={1.8} />
          </button>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <div style={{ fontSize: '13.5px', fontWeight: '600', color: 'var(--text-primary)' }}>
              {monthCursor.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}
            </div>
            {!isCurrentMonth && today && (
              <button
                type="button"
                onClick={() => {
                  setMonthCursor(new Date(today.getFullYear(), today.getMonth(), 1))
                  setSelectedDate(toIso(today))
                }}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--accent)',
                  cursor: 'pointer',
                  fontSize: '11px',
                  fontWeight: '600',
                  padding: '2px 4px',
                  borderRadius: 'var(--radius-btn, 4px)',
                  lineHeight: 1,
                }}
              >
                Today
              </button>
            )}
          </div>
          <button
            onClick={() => setMonthCursor(new Date(monthCursor.getFullYear(), monthCursor.getMonth() + 1, 1))}
            className="btn-touch-target"
            aria-label="Next Month"
            style={iconBtnStyle}
          >
            <ChevronRight size={16} strokeWidth={1.8} />
          </button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '3px', marginBottom: '4px' }}>
          {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((d, i) => (
            <div key={i} style={{ fontSize: '11px', color: 'var(--text-muted)', textAlign: 'center', fontWeight: '500' }}>{d}</div>
          ))}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '3px' }}>
          {monthDays.map((d, i) => {
            const iso = toIso(d)
            const inMonth = d.getMonth() === monthCursor.getMonth()
            const isSelected = iso === selectedDate
            const isToday = Boolean(today && isSameDay(d, today))
            const hasEvents = Boolean(scheduledDateSet && scheduledDateSet.has(iso))
            let ariaLabel = d.toLocaleDateString('en-US', {
              weekday: 'long',
              month: 'long',
              day: 'numeric',
              year: 'numeric',
            })
            if (isToday) {
              ariaLabel += ', today'
            }
            if (hasEvents) {
              ariaLabel += ', has events'
            }

            return (
              <button
                key={i}
                className="calendar-day-btn"
                onClick={() => setSelectedDate(iso)}
                aria-current={isToday ? 'date' : undefined}
                aria-label={ariaLabel}
                style={{
                  aspectRatio: '1',
                  boxSizing: 'border-box',
                  border: isToday ? '1px solid var(--accent)' : '1px solid transparent',
                  borderRadius: 'var(--radius-btn, 6px)',
                  cursor: 'pointer',
                  background: isSelected ? 'var(--accent)' : (isToday ? 'var(--bg-card-soft)' : 'transparent'),
                  color: isSelected ? 'var(--accent-text)' : (isToday ? 'var(--accent)' : (inMonth ? 'var(--text-primary)' : 'var(--text-muted)')),
                  boxShadow: (isSelected && isToday) ? '0 0 0 2px var(--bg-card), 0 0 0 3px var(--accent)' : undefined,
                  fontWeight: isToday ? '600' : '500',
                  fontSize: '12px',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '2px',
                  minHeight: '34px',
                }}>
                {d.getDate()}
                {hasEvents && !isSelected && <span style={{ width: '4px', height: '4px', borderRadius: '50%', background: 'var(--accent)' }} />}
              </button>
            )
          })}
        </div>
      </div>

      {/* Selected day panel */}
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-card, 8px)', padding: '14px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
          <div style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-muted)', letterSpacing: '0.06em' }}>
            {selectedDateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toUpperCase()}
          </div>
          <div style={{ fontSize: '11px', fontWeight: '500', color: 'var(--text-secondary)', background: 'var(--bg-card-soft)', border: '1px solid var(--border)', padding: '2px 8px', borderRadius: 'var(--radius-btn, 6px)' }}>
            {scheduledForDay(selectedDate).length} event{scheduledForDay(selectedDate).length === 1 ? '' : 's'}
          </div>
        </div>
        {scheduledForDay(selectedDate).length === 0 ? (
          <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>No scheduled tasks this day.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {scheduledForDay(selectedDate).map(t => {
              const s = getCalendarDomainStyle(t.domain)
              return (
                <div key={t.id} style={{ background: 'var(--bg-card-soft)', border: '1px solid var(--border)', borderRadius: 'var(--radius-card, 8px)', padding: '8px 10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span className="domain-swatch" style={{ background: s.accent }} />
                    <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>{t.title}</span>
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Clock size={11} strokeWidth={1.8} />
                    <span>{t.scheduled_start.slice(11, 16)} - {t.scheduled_end.slice(11, 16)} UTC · {t.duration_minutes || 60}m</span>
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
