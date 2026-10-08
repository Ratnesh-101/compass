// Compass — Authoritative Frontend Specialist Agent Registry

export const SPECIALIST_AGENTS = [
  {
    id: 'auto-dispatcher',
    name: 'Auto Dispatcher',
    command: '/auto',
    icon: '🧭',
    color: '#38bdf8',
    bg: 'rgba(56, 189, 248, 0.12)',
    border: 'rgba(56, 189, 248, 0.3)',
    description: 'Automatically selects the best specialist agent based on prompt intent.',
    placeholder: 'Ask anything — Auto Dispatcher will select the optimal specialist...',
    keywords: ['auto', 'dispatcher', 'routing', 'intent', 'all'],
  },
  {
    id: 'coursework',
    name: 'Coursework Agent',
    command: '/coursework',
    icon: '📚',
    color: '#818cf8',
    bg: 'rgba(129, 140, 248, 0.12)',
    border: 'rgba(129, 140, 248, 0.3)',
    description: 'Academic assignments, lab notes, exams & CS 61C coursework context.',
    placeholder: 'Ask about CS 61C labs, RISC-V notes, or upcoming assignments...',
    keywords: ['coursework', 'assignment', 'lab', 'exam', 'cs61c', 'academic', 'hw'],
  },
  {
    id: 'research',
    name: 'Research Agent',
    command: '/research',
    icon: '🔎',
    color: '#fbbf24',
    bg: 'rgba(251, 191, 36, 0.12)',
    border: 'rgba(251, 191, 36, 0.3)',
    description: 'Real-time web search, hackathon rules & deadline verification.',
    placeholder: 'Verify hackathon rules, research APIs, or search web for live docs...',
    keywords: ['research', 'web', 'search', 'devpost', 'rules', 'verify', 'deadline'],
  },
  {
    id: 'calendar',
    name: 'Calendar Agent',
    command: '/calendar',
    icon: '📅',
    color: '#34d399',
    bg: 'rgba(52, 211, 153, 0.12)',
    border: 'rgba(52, 211, 153, 0.3)',
    description: 'Google Calendar availability, free time slots, conflict detection & workload triage.',
    placeholder: 'Find free time tomorrow, check calendar conflicts, or assess workload feasibility...',
    keywords: ['calendar', 'schedule', 'free time', 'conflicts', 'workload', 'feasibility', 'slot'],
  },
  {
    id: 'memory',
    name: 'Memory Agent',
    command: '/memory',
    icon: '🧠',
    color: '#a78bfa',
    bg: 'rgba(167, 139, 250, 0.12)',
    border: 'rgba(167, 139, 250, 0.3)',
    description: 'Vector memory search (768-dim Matryoshka), code context & task backlog.',
    placeholder: 'Search vector memory, recall code architecture, or inspect backlog context...',
    keywords: ['memory', 'vector', 'pgvector', 'matryoshka', 'context', 'code', 'backlog'],
  },
]

export function getSpecialistById(id) {
  if (!id) return null
  const clean = id.trim().toLowerCase().replace(/^\//, '')
  return SPECIALIST_AGENTS.find(s =>
    s.id === clean ||
    s.id.replace('-', '') === clean ||
    s.command === `/${clean}` ||
    (clean === 'auto' && s.id === 'auto-dispatcher')
  ) || null
}

export function filterSpecialists(query) {
  if (query === null || query === undefined) return SPECIALIST_AGENTS
  const clean = String(query).trim().toLowerCase().replace(/^\//, '')
  if (!clean) return SPECIALIST_AGENTS
  return SPECIALIST_AGENTS.filter(s =>
    s.id.toLowerCase().includes(clean) ||
    s.name.toLowerCase().includes(clean) ||
    s.command.toLowerCase().includes(clean) ||
    s.keywords.some(k => k.toLowerCase().includes(clean))
  )
}
