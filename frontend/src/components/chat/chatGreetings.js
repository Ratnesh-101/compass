export const DEFAULT_STARTING_PHRASES = [
  "Where should we begin?",
  "Ready when you are.",
  "Pick a direction, or just start talking and we'll find one.",
  "No wrong place to start. What's pulling at you?",
  "Half-formed thoughts welcome.",
  "Take your time. I'm not going anywhere.",
]

export const DEFAULT_RETURNING_PHRASES = [
  "You returned! Want to pick up where we left off, or start somewhere new?",
  "Welcome back. What changed since last time?",
  "Good to see you again. Where shall we dive in?",
  "Ready to pick up the thread, or start somewhere fresh?",
]

export const STARTER_QUESTIONS = [
  "Find internships for me",
  "Plan my week",
  "Add a reminder",
  "Help me with my deadlines",
]

export function filterDuplicateTaskList(text, items) {
  if (!text) return ''
  const lines = text.split('\n')
  const kept = lines.filter((line) => {
    const trimmed = line.trim()
    if (/^(\d+\.|\*|-)\s+/.test(trimmed)) {
      if (items.some((it) => it.title && trimmed.toLowerCase().includes(it.title.toLowerCase()))) {
        return false
      }
    }
    if (/nothing is saved until you confirm/i.test(trimmed)) return false
    if (/reply\s*['"]confirm['"]/i.test(trimmed)) return false
    return true
  })
  return kept.join('\n').trim()
}

export function getTimeGreeting() {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

export function getEmptyStateGreeting(isReturning, userName, startingPool = DEFAULT_STARTING_PHRASES, returningPool = DEFAULT_RETURNING_PHRASES) {
  const pool = (isReturning ? returningPool : startingPool) || DEFAULT_STARTING_PHRASES
  const storageKey = isReturning ? 'compass_last_returning_phrase_idx' : 'compass_last_starting_phrase_idx'
  let lastIdx = -1
  try {
    const val = localStorage.getItem(storageKey)
    if (val !== null) lastIdx = parseInt(val, 10)
  } catch {
    /* ignore storage access error */
  }

  let candidates = pool.map((_, i) => i).filter(i => isNaN(lastIdx) || i !== lastIdx)
  if (candidates.length === 0) candidates = pool.map((_, i) => i)

  const chosenIdx = candidates[Math.floor(Math.random() * candidates.length)]
  try {
    localStorage.setItem(storageKey, String(chosenIdx))
  } catch {
    /* ignore storage access error */
  }

  let phrase = pool[chosenIdx] || pool[0] || "Where should we begin?"

  if (userName && isReturning) {
    if (phrase.includes("Welcome back.")) {
      phrase = `Welcome back, ${userName}. What changed since last time?`
    } else if (phrase.includes("You returned!")) {
      phrase = `Welcome back, ${userName}! Want to pick up where we left off, or start somewhere new?`
    } else if (phrase.includes("Good to see you again.")) {
      phrase = `Good to see you again, ${userName}. Where shall we dive in?`
    }
  }

  // 15% chance of subtle time-aware touch
  if (Math.random() < 0.15) {
    const hour = new Date().getHours()
    let touch = null
    if (hour >= 23 || hour < 5) touch = "Burning the midnight oil."
    else if (hour >= 5 && hour < 8) touch = "Early start today."
    else if (hour >= 8 && hour < 12) touch = "Morning focus."
    else if (hour >= 18 && hour < 23) touch = "Evening unwind."
    if (touch) {
      phrase = `${touch} ${phrase}`
    }
  }

  return phrase
}
