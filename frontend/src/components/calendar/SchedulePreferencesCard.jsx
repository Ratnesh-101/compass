import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Settings } from 'lucide-react'
import { formatPlanningHours, formatBreak } from './planningHours'
import { updateSchedulingPreferences } from '../../api/calendarApi'

const WEEKDAYS = [
  { id: 1, label: 'Mon' },
  { id: 2, label: 'Tue' },
  { id: 3, label: 'Wed' },
  { id: 4, label: 'Thu' },
  { id: 5, label: 'Fri' },
  { id: 6, label: 'Sat' },
  { id: 7, label: 'Sun' },
]

const BREAK_OPTIONS = [0, 5, 10, 15, 20, 30, 45, 60]

function validatePreferences(start, end, days, buffer) {
  const timeRegex = /^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$/
  if (!start || !timeRegex.test(start)) {
    return 'Start time must be a valid 24-hour time (HH:MM).'
  }
  if (!end || !timeRegex.test(end)) {
    return 'End time must be a valid 24-hour time (HH:MM).'
  }
  if (end <= start) {
    return 'End time must be strictly after start time.'
  }
  if (!Array.isArray(days) || days.length === 0) {
    return 'Please select at least one working day.'
  }
  if (days.some(d => !Number.isInteger(d) || d < 1 || d > 7)) {
    return 'Working days must be between Monday (1) and Sunday (7).'
  }
  const numBuffer = Number(buffer)
  if (!Number.isInteger(numBuffer) || numBuffer < 0 || numBuffer > 120) {
    return 'Break minutes must be between 0 and 120.'
  }
  return null
}

export function SchedulePreferencesCard({ prefs, onSaved }) {
  const [isEditing, setIsEditing] = useState(false)
  const [startTime, setStartTime] = useState(() => (prefs?.work_start_time || '09:00:00').slice(0, 5))
  const [endTime, setEndTime] = useState(() => (prefs?.work_end_time || '18:00:00').slice(0, 5))
  const [selectedDays, setSelectedDays] = useState(() => prefs?.work_days || [1, 2, 3, 4, 5])
  const [bufferMinutes, setBufferMinutes] = useState(() => Number(prefs?.buffer_minutes ?? 15))
  const [isSaving, setIsSaving] = useState(false)
  const [validationError, setValidationError] = useState('')
  const [savedStatus, setSavedStatus] = useState(false)

  const firstFieldRef = useRef(null)
  const editBtnRef = useRef(null)
  const wasEditingRef = useRef(false)

  useEffect(() => {
    if (!isEditing) {
      setStartTime((prefs?.work_start_time || '09:00:00').slice(0, 5))
      setEndTime((prefs?.work_end_time || '18:00:00').slice(0, 5))
      setSelectedDays(prefs?.work_days || [1, 2, 3, 4, 5])
      setBufferMinutes(Number(prefs?.buffer_minutes ?? 15))
    }
  }, [prefs, isEditing])

  useEffect(() => {
    if (isEditing) {
      wasEditingRef.current = true
      firstFieldRef.current?.focus()
    } else if (wasEditingRef.current) {
      wasEditingRef.current = false
      editBtnRef.current?.focus()
    }
  }, [isEditing])

  const handleCancel = useCallback(() => {
    setStartTime((prefs?.work_start_time || '09:00:00').slice(0, 5))
    setEndTime((prefs?.work_end_time || '18:00:00').slice(0, 5))
    setSelectedDays(prefs?.work_days || [1, 2, 3, 4, 5])
    setBufferMinutes(Number(prefs?.buffer_minutes ?? 15))
    setValidationError('')
    setIsEditing(false)
  }, [prefs])

  useEffect(() => {
    if (!isEditing) return
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        handleCancel()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isEditing, handleCancel])

  const toggleDay = (dayId) => {
    setValidationError('')
    setSelectedDays(prev => {
      if (prev.includes(dayId)) {
        return prev.filter(d => d !== dayId)
      } else {
        return [...prev, dayId].sort((a, b) => a - b)
      }
    })
  }

  const initialStart = (prefs?.work_start_time || '09:00:00').slice(0, 5)
  const initialEnd = (prefs?.work_end_time || '18:00:00').slice(0, 5)
  const initialDays = [...(prefs?.work_days || [1, 2, 3, 4, 5])].sort((a, b) => a - b).join(',')
  const initialBuffer = Number(prefs?.buffer_minutes ?? 15)

  const currentDays = [...selectedDays].sort((a, b) => a - b).join(',')
  const hasChanged =
    startTime !== initialStart ||
    endTime !== initialEnd ||
    currentDays !== initialDays ||
    Number(bufferMinutes) !== initialBuffer

  const handleSave = async (e) => {
    if (e) e.preventDefault()
    const error = validatePreferences(startTime, endTime, selectedDays, bufferMinutes)
    if (error) {
      setValidationError(error)
      return
    }

    setIsSaving(true)
    setValidationError('')
    try {
      const payload = {
        work_start_time: startTime.length === 5 ? `${startTime}:00` : startTime,
        work_end_time: endTime.length === 5 ? `${endTime}:00` : endTime,
        work_days: [...selectedDays].sort((a, b) => a - b),
        buffer_minutes: Number(bufferMinutes),
      }
      const res = await updateSchedulingPreferences(payload)
      const newPrefs = res?.preferences || payload
      onSaved?.(newPrefs)
      setSavedStatus(true)
      setIsEditing(false)
    } catch (err) {
      setValidationError(err?.message || 'Failed to save preferences.')
    } finally {
      setIsSaving(false)
    }
  }

  const clientValidationError = validatePreferences(startTime, endTime, selectedDays, bufferMinutes)
  const isSaveDisabled = isSaving || !hasChanged || Boolean(clientValidationError)

  return (
    <div
      style={{
        marginTop: 'auto',
        padding: '14px',
        borderRadius: 'var(--radius-card, 8px)',
        background: 'var(--bg-card-soft)',
        border: '1px solid var(--border)',
      }}
    >
      {!isEditing ? (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <h4 style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)', margin: 0, display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Settings size={14} strokeWidth={1.8} />
              <span>Study Schedule Preferences</span>
            </h4>
            <button
              ref={editBtnRef}
              type="button"
              onClick={() => {
                setSavedStatus(false)
                setValidationError('')
                setIsEditing(true)
              }}
              style={{
                background: 'transparent',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-btn, 6px)',
                color: 'var(--text-primary)',
                fontSize: '12px',
                fontWeight: '500',
                padding: '4px 8px',
                cursor: 'pointer',
              }}
            >
              Edit preferences
            </button>
          </div>

          {savedStatus && (
            <div
              role="status"
              style={{
                fontSize: '12px',
                color: 'var(--accent)',
                marginBottom: '8px',
                lineHeight: '1.4',
              }}
            >
              Saved. Your next auto-schedule uses these hours.
            </div>
          )}

          <ul style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: '1.6', paddingLeft: '16px', margin: 0 }}>
            <li>{formatPlanningHours(prefs)}</li>
            <li>{formatBreak(prefs?.buffer_minutes ?? 15)}</li>
            <li>Automatic focus time allocator</li>
            <li>Export to calendar (.ics format)</li>
          </ul>
        </div>
      ) : (
        <form onSubmit={handleSave} noValidate>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h4 style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)', margin: 0, display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Settings size={14} strokeWidth={1.8} />
              <span>Study Schedule Preferences</span>
            </h4>
          </div>

          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '10px' }}>
            <div style={{ flex: '1 1 120px' }}>
              <label
                htmlFor="schedule-pref-start-time"
                style={{ display: 'block', fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '4px' }}
              >
                Start time
              </label>
              <input
                id="schedule-pref-start-time"
                ref={firstFieldRef}
                type="time"
                step="900"
                value={startTime}
                onChange={e => {
                  setStartTime(e.target.value)
                  setValidationError('')
                }}
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  padding: '6px 8px',
                  fontSize: '13px',
                  borderRadius: 'var(--radius-btn, 6px)',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-card-soft)',
                  color: 'var(--text-primary)',
                }}
              />
            </div>

            <div style={{ flex: '1 1 120px' }}>
              <label
                htmlFor="schedule-pref-end-time"
                style={{ display: 'block', fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '4px' }}
              >
                End time
              </label>
              <input
                id="schedule-pref-end-time"
                type="time"
                step="900"
                value={endTime}
                onChange={e => {
                  setEndTime(e.target.value)
                  setValidationError('')
                }}
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  padding: '6px 8px',
                  fontSize: '13px',
                  borderRadius: 'var(--radius-btn, 6px)',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-card-soft)',
                  color: 'var(--text-primary)',
                }}
              />
            </div>
          </div>

          <div style={{ marginBottom: '10px' }}>
            <span style={{ display: 'block', fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>
              Working days
            </span>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {WEEKDAYS.map(day => {
                const active = selectedDays.includes(day.id)
                return (
                  <button
                    key={day.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => toggleDay(day.id)}
                    style={{
                      minWidth: '44px',
                      minHeight: '44px',
                      padding: '0 8px',
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      borderRadius: 'var(--radius-btn, 6px)',
                      border: active ? '1px solid var(--accent)' : '1px solid var(--border)',
                      background: active ? 'var(--accent)' : 'transparent',
                      color: active ? 'var(--accent-text, #ffffff)' : 'var(--text-primary)',
                      fontSize: '12px',
                      fontWeight: active ? '600' : '500',
                      cursor: 'pointer',
                      boxSizing: 'border-box',
                    }}
                  >
                    {day.label}
                  </button>
                )
              })}
            </div>
          </div>

          <div style={{ marginBottom: '12px' }}>
            <label
              htmlFor="schedule-pref-buffer-minutes"
              style={{ display: 'block', fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '4px' }}
            >
              Break between tasks
            </label>
            <select
              id="schedule-pref-buffer-minutes"
              value={bufferMinutes}
              onChange={e => {
                setBufferMinutes(Number(e.target.value))
                setValidationError('')
              }}
              style={{
                width: '100%',
                minHeight: '36px',
                boxSizing: 'border-box',
                padding: '6px 8px',
                fontSize: '13px',
                borderRadius: 'var(--radius-btn, 6px)',
                border: '1px solid var(--border)',
                background: 'var(--bg-card-soft)',
                color: 'var(--text-primary)',
              }}
            >
              {BREAK_OPTIONS.map(mins => (
                <option key={mins} value={mins}>
                  {mins === 0 ? '0 minutes (no break)' : mins === 60 ? '60 minutes (1 hour)' : `${mins} minutes`}
                </option>
              ))}
            </select>
          </div>

          {(validationError || clientValidationError) && (
            <div
              role="alert"
              style={{
                fontSize: '12px',
                color: 'var(--danger-text, #ef4444)',
                marginBottom: '10px',
                lineHeight: '1.4',
              }}
            >
              {validationError || clientValidationError}
            </div>
          )}

          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', marginTop: '12px' }}>
            <button
              type="button"
              onClick={handleCancel}
              disabled={isSaving}
              style={{
                padding: '8px 14px',
                fontSize: '12px',
                fontWeight: '500',
                borderRadius: 'var(--radius-btn, 6px)',
                border: '1px solid var(--border)',
                background: 'transparent',
                color: 'var(--text-secondary)',
                cursor: isSaving ? 'not-allowed' : 'pointer',
                minHeight: '36px',
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSaveDisabled}
              style={{
                padding: '8px 14px',
                fontSize: '12px',
                fontWeight: '600',
                borderRadius: 'var(--radius-btn, 6px)',
                border: 'none',
                background: 'var(--accent)',
                color: 'var(--accent-text, #ffffff)',
                cursor: isSaveDisabled ? 'not-allowed' : 'pointer',
                opacity: isSaveDisabled ? 0.6 : 1,
                minHeight: '36px',
              }}
            >
              {isSaving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}

export default SchedulePreferencesCard
