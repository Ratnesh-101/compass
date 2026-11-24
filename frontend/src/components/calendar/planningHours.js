// The scheduler plans inside configured hours (backend default 09:00-18:00, Monday to Friday).
export const PLANNING_HOURS_TEXT = 'Planning hours: 9:00 to 18:00, Monday to Friday'

const DAY_NAMES = {
  1: 'Monday',
  2: 'Tuesday',
  3: 'Wednesday',
  4: 'Thursday',
  5: 'Friday',
  6: 'Saturday',
  7: 'Sunday',
}

function formatTime(t, fallback) {
  if (!t) return fallback
  const parts = String(t).split(':')
  const h = parseInt(parts[0], 10)
  if (isNaN(h)) return fallback
  const m = (parts[1] || '00').slice(0, 2)
  return `${h}:${m.padStart(2, '0')}`
}

function formatDays(days) {
  if (!Array.isArray(days) || days.length === 0) {
    return 'Monday to Friday'
  }
  const unique = [...new Set(days.map(Number))].filter(n => n >= 1 && n <= 7).sort((a, b) => a - b)
  if (unique.length === 0) return 'Monday to Friday'
  if (unique.length === 7) return 'every day'
  if (unique.length === 5 && unique.every((d, i) => d === i + 1)) {
    return 'Monday to Friday'
  }
  const names = unique.map(d => DAY_NAMES[d])
  if (names.length === 1) return names[0]
  if (names.length === 2) return `${names[0]} and ${names[1]}`
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

export function formatPlanningHours(prefs) {
  if (!prefs) return PLANNING_HOURS_TEXT
  const start = formatTime(prefs.work_start_time, '9:00')
  const end = formatTime(prefs.work_end_time, '18:00')
  const days = formatDays(prefs.work_days)
  return `Planning hours: ${start} to ${end}, ${days}`
}

export function formatBreak(minutes) {
  const m = Number(minutes)
  if (!m || m <= 0) {
    return 'Break between tasks: no break'
  }
  if (m === 60) {
    return 'Break between tasks: 1 hour'
  }
  if (m % 60 === 0) {
    return `Break between tasks: ${m / 60} hours`
  }
  return `Break between tasks: ${m} ${m === 1 ? 'minute' : 'minutes'}`
}
