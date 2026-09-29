import React, { useState, useRef, useEffect } from 'react'
import { getAuthHeaders } from '../api/client'

/**
 * AgentPanel — Live execution trace UI for the Compass ReAct agent.
 *
 * Shows step-by-step agent reasoning (think → tool_call → observe → critic → synthesize)
 * with animated cards and a confirmation gate for state-mutating actions.
 */

const STEP_STYLES = {
  think: {
    bg: 'rgba(59, 130, 246, 0.08)',
    border: '#3b82f6',
    icon: '🧠',
    label: 'Thinking',
    labelColor: '#2563eb',
  },
  tool_call: {
    bg: 'rgba(245, 158, 11, 0.08)',
    border: '#d97706',
    icon: '🔍',
    label: 'Checking your data',
    labelColor: '#b45309',
  },
  observe: {
    bg: 'rgba(16, 185, 129, 0.08)',
    border: '#10b981',
    icon: '📄',
    label: 'Found',
    labelColor: '#059669',
  },
  confirm_request: {
    bg: 'rgba(239, 68, 68, 0.08)',
    border: '#ef4444',
    icon: '⚠️',
    label: 'Needs your approval',
    labelColor: '#dc2626',
  },
  critic: {
    bg: 'rgba(147, 51, 234, 0.08)',
    border: '#9333ea',
    icon: '✔️',
    label: 'Quality check',
    labelColor: '#7e22ce',
  },
  synthesize: {
    bg: 'linear-gradient(135deg, rgba(99, 102, 241, 0.08), rgba(168, 85, 247, 0.08))',
    border: '#8b5cf6',
    icon: '✨',
    label: 'Summary',
    labelColor: '#6d28d9',
  },
  error: {
    bg: 'rgba(239, 68, 68, 0.08)',
    border: '#ef4444',
    icon: '❌',
    label: 'Something went wrong',
    labelColor: '#dc2626',
  },
  done: {
    bg: 'rgba(16, 185, 129, 0.08)',
    border: '#10b981',
    icon: '✅',
    label: 'Done',
    labelColor: '#059669',
  },
  propose: {
    bg: 'rgba(6, 182, 212, 0.08)',
    border: '#06b6d4',
    icon: '📋',
    label: 'Proposed plan',
    labelColor: '#0891b2',
  },
  verdict: {
    bg: 'rgba(239, 68, 68, 0.08)',
    border: '#ef4444',
    icon: '⚖️',
    label: 'Feasibility check',
    labelColor: '#dc2626',
  },
  replan: {
    bg: 'rgba(245, 158, 11, 0.08)',
    border: '#f59e0b',
    icon: '🔄',
    label: 'Replanning',
    labelColor: '#b45309',
  },
}

// Maps internal tool names to friendly human-readable descriptions
function friendlyTool(toolName) {
  const map = {
    query_tasks: 'Looking up your tasks',
    add_task: 'Adding a new task',
    edit_task: 'Updating a task',
    delete_task: 'Removing a task',
    update_task_status: 'Changing task status',
    ingest_url: 'Reading a web page',
    ingest_text: 'Reading content',
    memory_search: 'Searching your memory and notes',
    summarize_day: 'Preparing a summary of your day',
    query_calendar: 'Checking your calendar',
    schedule_event: 'Scheduling an event',
    query_code_context: 'Reading your code notes',
    query_coursework_notes: 'Reading your coursework notes',
    apply_triage_plan: 'Adjusting your workload & schedule',
    get_projects: 'Looking up your active projects',
    search_web: 'Searching the web',
    web_search: 'Searching the web',
    detect_schedule_conflicts: 'Scanning for schedule conflicts',
  }
  if (!toolName) return ''
  return map[toolName] || toolName.replace(/_/g, ' ')
}

// Maps internal table names to friendly descriptions
function friendlyTable(table) {
  const map = {
    tasks: 'Task',
    memory_chunks: 'Note',
    projects: 'Project',
    calendar_events: 'Event',
    agent_audit_log: 'Change log',
  }
  return map[table] || table
}

// Maps internal tool action names to past-tense human descriptions
function friendlyAction(tool) {
  const map = {
    add_task: 'Added a task',
    edit_task: 'Updated a task',
    delete_task: 'Deleted a task',
    update_task_status: 'Changed task status',
    ingest_url: 'Saved web page',
    ingest_text: 'Saved note',
    apply_triage_plan: 'Adjusted schedule',
    schedule_event: 'Scheduled event',
    commit_schedule: 'Scheduled tasks',
  }
  return map[tool] || (tool || '').replace(/_/g, ' ')
}

function formatFriendlyTime(dateStr) {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) return dateStr.slice(11, 16)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return dateStr.slice(11, 16)
  }
}

function formatActivityItem(item) {
  try {
    const args = typeof item.args === 'string' ? JSON.parse(item.args) : (item.args || {})
    const newState = typeof item.new_state === 'string' ? JSON.parse(item.new_state) : (item.new_state || {})
    const prevState = typeof item.previous_state === 'string' ? JSON.parse(item.previous_state) : (item.previous_state || {})

    const title = args.title || newState.title || prevState.title || ''

    if (item.tool === 'add_task') {
      return title ? `Added task "${title}"` : 'Added a new task'
    }
    if (item.tool === 'delete_task') {
      return title ? `Removed task "${title}"` : 'Removed a task'
    }
    if (item.tool === 'edit_task') {
      return title ? `Updated task "${title}"` : 'Updated a task'
    }
    if (item.tool === 'update_task_status') {
      const status = args.status || newState.status || 'updated'
      const statusLabel = status === 'done' ? 'completed' : status
      return title ? `Marked "${title}" as ${statusLabel}` : `Marked task as ${statusLabel}`
    }
    if (item.tool === 'ingest_url') {
      const url = args.url || ''
      const host = url ? url.replace(/^https?:\/\/(www\.)?/, '').split('/')[0] : ''
      return host ? `Saved link from ${host}` : 'Saved web page'
    }
    if (item.tool === 'ingest_text') {
      return title ? `Saved note: "${title}"` : 'Saved note to memory'
    }
    if (item.tool === 'commit_schedule' || item.tool === 'schedule_event') {
      return title ? `Scheduled "${title}"` : 'Scheduled calendar event'
    }
    if (item.tool === 'apply_triage_plan') {
      return 'Adjusted task plan & schedule'
    }
  } catch {
    // fallback
  }
  return friendlyAction(item.tool)
}

function formatActionDescription(action) {
  if (!action) return 'Update data'
  if (action.summary) return action.summary
  const tool = action.tool
  const args = action.args || {}
  if (tool === 'add_task') {
    return `Add task: "${args.title || 'New Task'}"`
  }
  if (tool === 'edit_task') {
    return `Update task: "${args.title || `Task #${args.task_id || ''}`}"`
  }
  if (tool === 'delete_task') {
    return `Delete task #${args.task_id || ''}`
  }
  if (tool === 'update_task_status') {
    const status = args.status || 'done'
    return `Mark task #${args.task_id || ''} as ${status === 'done' ? 'completed' : status}`
  }
  if (tool === 'schedule_event' || tool === 'commit_schedule') {
    return `Schedule "${args.title || 'event'}" on calendar`
  }
  if (tool === 'apply_triage_plan') {
    return 'Adjust task plan to balance workload'
  }
  return friendlyAction(tool)
}

function formatStepContent(step) {
  if (!step.content) return null

  if (step.type === 'done') {
    return formatDoneSummary(step.content)
  }

  if (step.type === 'tool_call') {
    const action = friendlyTool(step.tool)
    let extra = ''
    if (step.args) {
      if (step.args.query) extra = ` for "${step.args.query}"`
      else if (step.args.status) extra = ` (status: ${step.args.status})`
      else if (step.args.domain) extra = ` in ${step.args.domain}`
    }
    return `Looking up information: ${action.toLowerCase()}${extra}…`
  }

  if (step.type === 'observe' && typeof step.content === 'string') {
    const match = step.content.match(/^Found (\d+) task\(s\)(?: with status '([^']+)')?:/i)
    if (match) {
      const count = match[1]
      const status = match[2] ? ` (status: ${match[2]})` : ''
      return `Found ${count} task${count === '1' ? '' : 's'}${status}. Analyzing your schedule and commitments…`
    }
  }

  if (step.type === 'confirm_request') {
    return 'Please review the requested changes below and let me know if you would like to proceed.'
  }

  return step.content
}

const SUGGESTED_GOALS = [
  "I have 5 days left and I'm working 4 hours a day. Go through everything I have open across the hackathon, my coursework, and my code debt, and tell me honestly whether I can finish it — and if I can't, decide what I drop.",
  "Plan my week considering all hackathon deadlines and coursework",
  "Flag any deadline conflicts this week and suggest resolutions",
  "Write a retrospective for the Compass project",
  "What are my most urgent tasks across all domains?",
  "Summarize my open tasks and suggest what to tackle first",
]

function ReplanDiffCard({ diff }) {
  if (!diff) return null
  return (
    <div style={{
      margin: '10px 0 8px',
      background: 'rgba(245, 158, 11, 0.08)',
      border: '1px solid rgba(245,158,11,0.3)',
      borderRadius: '8px',
      padding: '10px 14px',
      fontSize: '13px',
    }}>
      <div style={{ color: '#b45309', fontWeight: '700', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
        🔄 Change was declined — finding a better approach
      </div>
      {diff.feedback && (
        <div style={{ color: 'var(--text-secondary)', marginBottom: '4px' }}>
          Your feedback: <span style={{ color: 'var(--text-primary)' }}>"{diff.feedback}"</span>
        </div>
      )}
      <div style={{ color: '#059669', fontSize: '12px' }}>
        ✓ Replanning without touching your data
      </div>
    </div>
  )
}

function ReportCard({ reportCard }) {
  if (!reportCard) return null
  const elapsedSec = reportCard.elapsed_ms ? (reportCard.elapsed_ms / 1000).toFixed(1) : null
  return (
    <div id="agent-report-card" style={{
      marginTop: '12px',
      background: 'var(--bg-card-soft)',
      border: '1px solid var(--border)',
      borderRadius: '10px',
      padding: '12px 16px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '16px' }}>✅</span>
          <span style={{ fontWeight: '700', fontSize: '13px', color: 'var(--text-secondary)' }}>
            Run summary
          </span>
        </div>
        <span style={{
          fontSize: '11px',
          fontWeight: '600',
          padding: '2px 10px',
          borderRadius: '12px',
          background: reportCard.abstained ? 'rgba(245, 158, 11, 0.15)' : 'rgba(16, 185, 129, 0.15)',
          color: reportCard.abstained ? '#b45309' : '#059669',
        }}>
          {reportCard.abstained ? 'Needs more info' : 'Completed'}
        </span>
      </div>
      <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', fontSize: '13px', color: 'var(--text-secondary)' }}>
        {elapsedSec && <span>⏱ {elapsedSec}s</span>}
        {reportCard.total_steps && <span>🔢 {reportCard.total_steps} steps</span>}
        {reportCard.critique_rounds > 0 && (
          <span>🔍 {reportCard.critique_rounds} quality check{reportCard.critique_rounds !== 1 ? 's' : ''}</span>
        )}
      </div>
    </div>
  )
}

function StepCard({ step, index }) {
  const style = STEP_STYLES[step.type] || STEP_STYLES.think
  const isGradient = step.type === 'synthesize'
  const isAbstained = step.metadata?.abstained || (typeof step.content === 'string' && step.content.includes('[ABSTAIN]'))
  const replanDiff = step.metadata?.replan_diff
  let reportCard = step.metadata?.report_card
  if (!reportCard && step.type === 'done') {
    try {
      const parsed = JSON.parse(step.content)
      reportCard = parsed.report_card
    } catch {}
  }

  return (
    <div
      style={{
        background: isGradient ? style.bg : style.bg,
        border: `1px solid ${style.border}33`,
        borderLeft: `3px solid ${style.border}`,
        borderRadius: '8px',
        padding: '12px 16px',
        marginBottom: '8px',
        animation: 'slideIn 0.3s ease-out',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '14px' }}>{style.icon}</span>
        <span style={{
          fontSize: '11px',
          fontWeight: '700',
          color: style.labelColor,
        }}>
          {style.label}
        </span>

        {/* Show friendly tool description instead of raw tool name for tool_call steps */}
        {step.type === 'tool_call' && step.tool && (
          <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
            — {friendlyTool(step.tool)}
          </span>
        )}

        <span style={{
          fontSize: '10px',
          color: 'var(--text-muted)',
          marginLeft: 'auto',
        }}>
          {step.elapsed_ms > 0 ? `${(step.elapsed_ms / 1000).toFixed(1)}s` : ''}
        </span>
      </div>



      {/* Workload Check Box */}
      {step.metadata?.verdict && (
        <div style={{
          margin: '8px 0',
          background: step.metadata.verdict.verdict === 'FEASIBLE'
            ? 'rgba(16, 185, 129, 0.08)'
            : 'rgba(239, 68, 68, 0.08)',
          border: `1px solid ${step.metadata.verdict.verdict === 'FEASIBLE' ? '#10b98144' : '#ef444444'}`,
          borderRadius: '8px',
          padding: '12px 14px',
          fontSize: '13px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{
              fontWeight: '700',
              color: step.metadata.verdict.verdict === 'FEASIBLE' ? '#059669' : '#dc2626',
              fontSize: '14px',
            }}>
              {step.metadata.verdict.verdict === 'FEASIBLE' ? '✅ You can do it!' : '⚠️ Too much to fit in the time'}
            </span>
            <span style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>
              {step.metadata.verdict.utilisation_pct}% of your available time
            </span>
          </div>
          <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', color: 'var(--text-secondary)', fontSize: '12px' }}>
            <span>📋 Work needed: <strong style={{ color: 'var(--text-primary)' }}>{step.metadata.verdict.demand_hours}h</strong></span>
            <span>🕐 Time available: <strong style={{ color: 'var(--text-primary)' }}>{step.metadata.verdict.capacity_hours}h</strong></span>
            {step.metadata.verdict.overcommit_hours > 0 && (
              <span style={{ color: '#dc2626' }}>🚨 Over by: <strong>{step.metadata.verdict.overcommit_hours}h</strong></span>
            )}
          </div>
          {step.metadata.verdict.must_cut_hours > 0 && (
            <div style={{ marginTop: '8px', color: '#b45309', fontSize: '12px' }}>
              ✂️ You'll need to cut about <strong>{step.metadata.verdict.must_cut_hours}h</strong> of work to stay realistic.
            </div>
          )}
          {step.metadata.verdict.challenged_estimates?.length > 0 && (
            <div style={{ marginTop: '8px', borderTop: '1px solid var(--border)', paddingTop: '8px' }}>
              <span style={{ color: '#dc2626', fontWeight: '600', fontSize: '12px' }}>⏱ These time estimates might be too optimistic:</span>
              <ul style={{ margin: '4px 0 0 16px', padding: 0, color: 'var(--text-secondary)', fontSize: '12px' }}>
                {step.metadata.verdict.challenged_estimates.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Not enough info warning */}
      {isAbstained && (
        <div style={{
          background: 'rgba(245, 158, 11, 0.08)',
          border: '1px solid rgba(245,158,11,0.3)',
          borderRadius: '8px',
          padding: '10px 14px',
          marginBottom: '8px',
          color: '#b45309',
          fontSize: '13px',
          fontWeight: '500',
          display: 'flex',
          alignItems: 'flex-start',
          gap: '8px',
        }}>
          <span style={{ fontSize: '18px', flexShrink: 0 }}>🤷</span>
          <span>I don't have enough information to answer this confidently. Try giving me more context, or ask something I can check in your tasks or calendar.</span>
        </div>
      )}

      {/* Re-Plan Diff Block */}
      {replanDiff && <ReplanDiffCard diff={replanDiff} />}

      <div style={{
        fontSize: '13px',
        color: 'var(--text-primary)',
        lineHeight: '1.6',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}>
        {formatStepContent(step)}
      </div>

      {/* Plan Breakdown Box */}
      {step.type === 'done' && step.metadata?.artifact_markdown && (
        <div style={{
          marginTop: '12px',
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: '8px',
          padding: '14px 16px',
          boxShadow: 'var(--shadow-sm)'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <span style={{ fontSize: '13px', fontWeight: '700', color: 'var(--primary)', letterSpacing: '0.02em' }}>
              📋 Your Personalized Action Plan
            </span>
            <button
              onClick={() => navigator.clipboard.writeText(step.metadata.artifact_markdown)}
              style={{
                background: 'var(--bg-card-soft)',
                border: '1px solid var(--border)',
                borderRadius: '6px',
                color: 'var(--text-secondary)',
                padding: '4px 10px',
                fontSize: '11px',
                cursor: 'pointer',
              }}
            >
              📋 Copy Plan
            </button>
          </div>
          <div style={{
            fontSize: '13px',
            lineHeight: '1.6',
            color: 'var(--text-primary)',
            whiteSpace: 'pre-wrap',
            fontFamily: 'Inter, system-ui, sans-serif',
          }}>
            {step.metadata.artifact_markdown}
          </div>
        </div>
      )}

      {/* Compact Run Report Card */}
      {step.type === 'done' && reportCard && <ReportCard reportCard={reportCard} />}
    </div>
  )
}

function formatDoneSummary(content) {
  try {
    const data = JSON.parse(content)
    const pendingCount = (data.pending_confirmations || []).length
    const toolsUsed = (data.tools_used || []).map(t => friendlyTool(t)).filter(Boolean)
    let summary = `Finished in ${data.total_steps} step${data.total_steps !== 1 ? 's' : ''}.`
    if (toolsUsed.length > 0) {
      summary += ` Checked: ${toolsUsed.join(', ')}.`
    }
    if (pendingCount > 0) {
      summary += ` ⚠️ ${pendingCount} change${pendingCount !== 1 ? 's' : ''} waiting for your approval below.`
    }
    return summary
  } catch {
    return content
  }
}

export default function AgentPanel({ onTaskMutated, conversationId }) {
  const [goal, setGoal] = useState('')
  const [steps, setSteps] = useState([])
  const [isRunning, setIsRunning] = useState(false)
  const [pendingActions, setPendingActions] = useState([])
  const [currentRunId, setCurrentRunId] = useState(null)
  const [undoStatus, setUndoStatus] = useState(null)
  const [rejectFeedback, setRejectFeedback] = useState('')
  const [showRejectInput, setShowRejectInput] = useState(false)
  const [activityList, setActivityList] = useState([])
  const [critiqueStats, setCritiqueStats] = useState(null)
  const [proactiveBriefing, setProactiveBriefing] = useState(null)
  const [triggeringNightly, setTriggeringNightly] = useState(false)
  const [runsList, setRunsList] = useState([])
  const [showHistory, setShowHistory] = useState(false)
  const [copyFeedback, setCopyFeedback] = useState(false)
  const scrollContainerRef = useRef(null)
  const abortRef = useRef(null)

  const getApiBase = () => {
    return window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
      ? 'http://127.0.0.1:8000'
      : ''
  }

  const fetchRunsHistory = async () => {
    try {
      const res = await fetch(`${getApiBase()}/api/agent/runs?limit=25`, {
        headers: getAuthHeaders(),
      })
      if (res.ok) {
        const data = await res.json()
        setRunsList(data.runs || [])
      }
    } catch {
      // ignore
    }
  }

  const fetchActivity = async () => {
    try {
      const res = await fetch(`${getApiBase()}/api/agent/activity?limit=15`, {
        headers: getAuthHeaders(),
      })
      if (res.ok) {
        const data = await res.json()
        setActivityList(data.activity || [])
      }
    } catch {
      // ignore
    }
  }

  const fetchCritiqueStats = async () => {
    try {
      const res = await fetch(`${getApiBase()}/api/agent/critique-stats`, {
        headers: getAuthHeaders(),
      })
      if (res.ok) {
        const data = await res.json()
        setCritiqueStats(data)
      }
    } catch {
      // ignore
    }
  }

  const fetchProactiveBriefing = async () => {
    try {
      const res = await fetch(`${getApiBase()}/api/agent/proactive-briefing`, {
        headers: getAuthHeaders(),
      })
      if (res.ok) {
        const data = await res.json()
        if (data.found) {
          setProactiveBriefing(data)
        }
      }
    } catch {
      // ignore
    }
  }

  const triggerNightlyJob = async () => {
    setTriggeringNightly(true)
    try {
      const res = await fetch(`${getApiBase()}/api/agent/trigger-nightly`, {
        method: 'POST',
        headers: getAuthHeaders({
          'Content-Type': 'application/json',
        }),
      })
      if (res.ok) {
        await fetchProactiveBriefing()
        await fetchActivity()
      }
    } catch {
      // ignore
    } finally {
      setTriggeringNightly(false)
    }
  }

  const loadProactiveBriefingTrace = () => {
    if (proactiveBriefing && proactiveBriefing.accumulated_steps) {
      setSteps(proactiveBriefing.accumulated_steps)
      setCurrentRunId(proactiveBriefing.run_id)
      setGoal(proactiveBriefing.goal || '')
    }
  }

  useEffect(() => {
    fetchActivity()
    fetchCritiqueStats()
    fetchProactiveBriefing()
    fetchRunsHistory()
  }, [])

  // Smoothly scroll internal container when steps or confirmations pop in
  // Avoid window / parent scroll chaining
  useEffect(() => {
    if (scrollContainerRef.current) {
      requestAnimationFrame(() => {
        if (scrollContainerRef.current) {
          scrollContainerRef.current.scrollTo({
            top: scrollContainerRef.current.scrollHeight,
            behavior: 'smooth',
          })
        }
      })
    }
  }, [steps.length, pendingActions.length])

  const loadPastRun = (run) => {
    setGoal(run.goal || '')
    setCurrentRunId(run.id)
    setSteps(run.steps || [])
    setShowHistory(false)
  }

  const copyTraceAsMarkdown = () => {
    const mdLines = [
      `# 🧭 Compass Plan — ${goal || 'Question'}`,
      `**Total Steps**: ${steps.length}`,
      '',
      '---',
      '',
    ]
    steps.forEach((s) => {
      const icon = STEP_STYLES[s.type]?.icon || '•'
      const label = STEP_STYLES[s.type]?.label || s.type.toUpperCase()
      mdLines.push(`### ${icon} Step ${s.step}: ${label}`)
      if (s.tool) {
        mdLines.push(`**Action**: ${friendlyTool(s.tool)}`)
      }
      if (s.content) {
        mdLines.push(`> ${s.content}`)
      }
      mdLines.push('')
    })
    navigator.clipboard.writeText(mdLines.join('\n'))
    setCopyFeedback(true)
    setTimeout(() => setCopyFeedback(false), 2000)
  }

  const streamFromEndpoint = async (payload) => {
    setIsRunning(true)
    const controller = new AbortController()
    abortRef.current = controller

    try {
      const apiBase = getApiBase()
      const reqPayload = { ...payload }
      if (conversationId && !reqPayload.conversation_id) {
        reqPayload.conversation_id = conversationId
      }

      const isFeasibility = !payload.action && (/feasibility|can i finish|what i drop|what to drop|what should i drop|triage|days left|working \d+ hours/i.test(payload.goal || ''))
      const endpoint = isFeasibility ? `${apiBase}/api/agent/feasibility` : `${apiBase}/api/agent/run`
      let reqBody = reqPayload
      if (isFeasibility) {
        const goalStr = payload.goal || ''
        const daysMatch = goalStr.match(/(\d+)\s*days?/i)
        const hoursMatch = goalStr.match(/(\d+(?:\.\d+)?)\s*hours?/i)
        reqBody = {
          days: daysMatch ? parseInt(daysMatch[1]) : 5,
          hours_per_day: hoursMatch ? parseFloat(hoursMatch[1]) : 4.0,
          domain: null,
        }
      }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(reqBody),
        signal: controller.signal,
      })

      if (!response.ok) {
        throw new Error(`Agent request failed: ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event = JSON.parse(line.slice(6))
              setSteps(prev => [...prev, event])

              if (event.run_id) {
                setCurrentRunId(event.run_id)
              }

              // Collect pending confirmations
              if (event.type === 'confirm_request') {
                setPendingActions(prev => [...prev, { tool: event.tool, args: event.args }])
              } else if (event.type === 'done' && event.metadata?.triage_plan) {
                const tp = event.metadata.triage_plan
                if ((tp.drop && tp.drop.length > 0) || (tp.defer && tp.defer.length > 0)) {
                  setPendingActions([{
                    tool: 'apply_triage_plan',
                    args: {
                      drop_ids: (tp.drop || []).map(t => t.task_id),
                      defer_ids: (tp.defer || []).map(t => t.task_id),
                    },
                    summary: `Adjust workload: drop ${tp.drop?.length || 0} task(s) and reschedule ${tp.defer?.length || 0} task(s)`,
                  }])
                }
              }
            } catch {
              // Skip malformed events
            }
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setSteps(prev => [...prev, {
          type: 'error',
          content: `Connection error: ${err.message}`,
          step: 0,
          elapsed_ms: 0,
        }])
      }
    } finally {
      setIsRunning(false)
      abortRef.current = null
      fetchActivity()
      fetchCritiqueStats()
      fetchRunsHistory()
    }
  }

  const runAgent = async (goalText) => {
    if (!goalText.trim()) return
    setSteps([])
    setPendingActions([])
    setCurrentRunId(null)
    setUndoStatus(null)
    setShowRejectInput(false)

    await streamFromEndpoint({
      goal: goalText,
      max_steps: 8,
      enable_critic: true,
      confirmed_actions: [],
    })
  }

  const stopAgent = () => {
    if (abortRef.current) {
      abortRef.current.abort()
      setIsRunning(false)
    }
  }

  const approveActions = async () => {
    if (pendingActions.length === 0) return
    const actionsToApprove = [...pendingActions]
    setPendingActions([])
    setShowRejectInput(false)

    if (actionsToApprove.some(a => a.tool === 'apply_triage_plan')) {
      try {
        const apiBase = getApiBase()
        await fetch(`${apiBase}/api/agent/confirm`, {
          method: 'POST',
          headers: getAuthHeaders({
            'Content-Type': 'application/json',
          }),
          body: JSON.stringify({ actions: actionsToApprove, run_id: currentRunId }),
        })
        setSteps(prev => [...prev, {
          type: 'observe',
          step: prev.length + 1,
          elapsed_ms: 0,
          content: 'Your workload adjustment has been applied. Selected tasks were updated.',
        }])
        onTaskMutated?.()
      } catch (err) {
        setSteps(prev => [...prev, {
          type: 'error',
          step: prev.length + 1,
          elapsed_ms: 0,
          content: `Failed to apply plan: ${err.message}`,
        }])
      }
      return
    }

    // Resume agent with action='approve' so it executes mutation and finishes
    await streamFromEndpoint({
      run_id: currentRunId,
      goal: goal,
      action: 'approve',
      confirmed_actions: actionsToApprove,
    })
    onTaskMutated?.()
  }

  const rejectActions = async () => {
    const feedback = rejectFeedback.trim() || 'User declined proposed change. Propose an alternative without modifying this task.'
    const wasTriage = pendingActions.some(a => a.tool === 'apply_triage_plan')
    const triageAction = pendingActions.find(a => a.tool === 'apply_triage_plan')
    setPendingActions([])
    setShowRejectInput(false)
    setRejectFeedback('')

    if (wasTriage) {
      const diff = {
        declined_action: triageAction,
        feedback: feedback || 'User chose not to proceed with these changes. All tasks remain unchanged.',
      }
      setSteps(prev => [...prev, {
        type: 'observe',
        step: prev.length + 1,
        elapsed_ms: 0,
        content: 'No changes made: Your tasks, priorities, and deadlines remain unchanged.',
        metadata: { replan_diff: diff },
      }])
      return
    }

    // Resume agent with action='reject' so it re-plans!
    await streamFromEndpoint({
      run_id: currentRunId,
      goal: goal,
      action: 'reject',
      feedback: feedback,
    })
  }

  const undoLastAction = async () => {
    try {
      const apiBase = getApiBase()
      const res = await fetch(`${apiBase}/api/agent/undo`, {
        method: 'POST',
        headers: getAuthHeaders({
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({ run_id: currentRunId }),
      })
      const data = await res.json()
      if (res.ok && data.status === 'ok') {
        setUndoStatus(data.message || 'Action reverted')
        setSteps(prev => [...prev, {
          type: 'observe',
          content: `↩️ ${data.message || 'The previous change has been undone.'}`,
          step: prev.length + 1,
          elapsed_ms: 0,
        }])
        fetchActivity()
        onTaskMutated?.()
      } else {
        setUndoStatus(data.message || 'Nothing to undo')
      }
    } catch (err) {
      setUndoStatus(`Undo failed: ${err.message}`)
    }
  }

  const revertActivityItem = async (auditLogId) => {
    try {
      const apiBase = getApiBase()
      const res = await fetch(`${apiBase}/api/agent/undo`, {
        method: 'POST',
        headers: getAuthHeaders({
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({ audit_log_id: auditLogId }),
      })
      const data = await res.json()
      if (res.ok && data.status === 'ok') {
        setUndoStatus(data.message || 'Action reverted')
        fetchActivity()
        onTaskMutated?.()
      } else {
        setUndoStatus(data.message || 'Failed to revert action')
      }
    } catch (err) {
      setUndoStatus(`Undo failed: ${err.message}`)
    }
  }

  return (
    <div style={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      minHeight: 0,
      overflow: 'hidden',
      padding: '0',
    }}>
      <style>{`
        @keyframes slideIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>

      {/* Goal Input Area */}
      <div style={{
        padding: '16px 20px',
        borderBottom: '1px solid var(--border)',
        flexShrink: 0,
      }}>
        {/* Proactive Autonomous Overnight Briefing Banner */}
        {proactiveBriefing && (
          <div style={{
            background: 'var(--bg-card-soft)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            padding: '10px 14px',
            marginBottom: '12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{ fontSize: '22px' }}>🌅</span>
              <div>
                <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--primary)', letterSpacing: '0.02em' }}>
                  Your Morning Briefing is Ready
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                  Prepared overnight based on your tasks and upcoming deadlines
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                id="load-proactive-briefing-btn"
                onClick={loadProactiveBriefingTrace}
                style={{
                  padding: '6px 14px',
                  background: 'var(--primary)',
                  border: 'none',
                  borderRadius: '6px',
                  color: '#fff',
                  fontSize: '12px',
                  fontWeight: '600',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                }}
              >
                📥 View Briefing
              </button>
              <button
                id="trigger-nightly-btn"
                onClick={triggerNightlyJob}
                disabled={triggeringNightly}
                style={{
                  padding: '6px 12px',
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  borderRadius: '6px',
                  color: 'var(--text-secondary)',
                  fontSize: '12px',
                  cursor: 'pointer',
                }}
                title="Generate an updated briefing right now"
              >
                {triggeringNightly ? '⏳ Updating…' : '↻ Refresh Now'}
              </button>
            </div>
          </div>
        )}

        <div style={{
          display: 'flex',
          gap: '8px',
          marginBottom: '10px',
        }}>
          <input
            id="agent-goal-input"
            type="text"
            value={goal}
            onChange={e => setGoal(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !isRunning && runAgent(goal)}
            placeholder="Ask a question or plan your schedule (e.g. 'What are my top priorities today?')"
            disabled={isRunning}
            style={{
              flex: 1,
              padding: '10px 14px',
              background: 'var(--bg-app)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              color: 'var(--text-primary)',
              fontSize: '14px',
              outline: 'none',
              fontFamily: 'Inter, system-ui, sans-serif',
            }}
          />
          {isRunning ? (
            <button
              id="agent-stop-btn"
              onClick={stopAgent}
              style={{
                padding: '10px 18px',
                background: '#dc2626',
                border: 'none',
                borderRadius: '8px',
                color: '#fff',
                fontSize: '13px',
                fontWeight: '600',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              ⏹ Stop
            </button>
          ) : (
            <button
              id="agent-run-btn"
              onClick={() => runAgent(goal)}
              disabled={!goal.trim()}
              style={{
                padding: '10px 18px',
                background: goal.trim() ? 'var(--primary)' : 'var(--bg-card-soft)',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                color: goal.trim() ? '#fff' : 'var(--text-muted)',
                fontSize: '13px',
                fontWeight: '600',
                cursor: goal.trim() ? 'pointer' : 'not-allowed',
                whiteSpace: 'nowrap',
              }}
            >
              Ask Assistant
            </button>
          )}

          <button
            id="agent-history-toggle-btn"
            onClick={() => { fetchRunsHistory(); setShowHistory(!showHistory) }}
            style={{
              padding: '10px 14px',
              background: showHistory ? 'var(--primary)' : 'var(--bg-card-soft)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              color: showHistory ? '#fff' : 'var(--text-secondary)',
              fontSize: '13px',
              fontWeight: '600',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
            title="View past plans and questions"
          >
            📜 Past Plans ({runsList.length})
          </button>

          {steps.length > 0 && (
            <button
              id="agent-copy-trace-btn"
              onClick={copyTraceAsMarkdown}
              style={{
                padding: '10px 14px',
                background: 'var(--bg-card-soft)',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                color: copyFeedback ? '#059669' : 'var(--text-secondary)',
                fontSize: '13px',
                fontWeight: '600',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
              title="Copy this plan to clipboard"
            >
              {copyFeedback ? '✓ Copied' : '📋 Copy Plan'}
            </button>
          )}
        </div>

        {/* Suggested goals and pre-loaded demo trigger */}
        {steps.length === 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
            <button
              id="agent-demo-reject-btn"
              onClick={() => {
                const demoGoal = "Detect deadline conflicts between hackathon deliverables and coursework and reschedule"
                setGoal(demoGoal)
                setRejectFeedback("Do not move OS Homework 2 deadline")
                runAgent(demoGoal)
              }}
              style={{
                padding: '6px 13px',
                background: 'rgba(239, 68, 68, 0.08)',
                border: '1px solid rgba(239, 68, 68, 0.25)',
                borderRadius: '14px',
                color: '#dc2626',
                fontSize: '11.5px',
                fontWeight: '600',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                transition: 'all 0.2s',
              }}
              title="Resolves conflicting deadlines and allows you to guide the plan"
            >
              ⚡ Resolve Deadline Conflicts
            </button>

            <button
              id="agent-demo-tri-domain-btn"
              onClick={() => {
                const demoGoal = "What should I deprioritize this week, given my code debt and upcoming exams?"
                setGoal(demoGoal)
                runAgent(demoGoal)
              }}
              style={{
                padding: '6px 13px',
                background: 'rgba(59, 130, 246, 0.08)',
                border: '1px solid rgba(59, 130, 246, 0.25)',
                borderRadius: '14px',
                color: '#2563eb',
                fontSize: '11.5px',
                fontWeight: '600',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                transition: 'all 0.2s',
              }}
              title="Balances hackathon, coursework, and code commitments"
            >
              ⚡ Balance My Workload
            </button>

            <button
              id="agent-demo-abstain-btn"
              onClick={() => {
                const demoGoal = "What is the final grade weighting and curve formula for the Quantum Computing midterm?"
                setGoal(demoGoal)
                runAgent(demoGoal)
              }}
              style={{
                padding: '6px 13px',
                background: 'rgba(245, 158, 11, 0.08)',
                border: '1px solid rgba(245, 158, 11, 0.25)',
                borderRadius: '14px',
                color: '#b45309',
                fontSize: '11.5px',
                fontWeight: '600',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                transition: 'all 0.2s',
              }}
              title="Shows how the assistant asks for clarification when info is missing"
            >
              🛡️ Check Missing Info
            </button>

            {SUGGESTED_GOALS.map((sg, i) => (
              <button
                key={i}
                onClick={() => { setGoal(sg); runAgent(sg) }}
                style={{
                  padding: '5px 10px',
                  background: 'var(--bg-card-soft)',
                  border: '1px solid var(--border)',
                  borderRadius: '14px',
                  color: 'var(--text-secondary)',
                  fontSize: '11px',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                }}
                onMouseEnter={e => { e.target.style.background = 'var(--bg-card)'; e.target.style.color = 'var(--text-primary)' }}
                onMouseLeave={e => { e.target.style.background = 'var(--bg-card-soft)'; e.target.style.color = 'var(--text-secondary)' }}
              >
                {sg}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Execution Trace — fills remaining space without page overflow */}
      <div
        ref={scrollContainerRef}
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: 'auto',
          overscrollBehavior: 'contain',
          padding: '16px 20px',
          boxSizing: 'border-box',
        }}
      >
        {/* Run History Flyout Drawer */}
        {showHistory && (
          <div style={{
            marginBottom: '16px',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            padding: '14px',
            boxShadow: 'var(--shadow-md)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
              <span style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary)', letterSpacing: '0.02em' }}>
                📜 Past Plans & Answers ({runsList.length})
              </span>
              <button
                onClick={() => setShowHistory(false)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '15px' }}
              >
                ✕
              </button>
            </div>
            {runsList.length === 0 ? (
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic', padding: '12px 0', textAlign: 'center' }}>
                No past plans yet. Ask a question or run a plan above to see history here.
              </div>
            ) : (
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '6px',
                maxHeight: '220px',
                overflowY: 'auto',
                overscrollBehavior: 'contain',
              }}>
                {runsList.map(r => (
                  <div
                    key={r.id}
                    onClick={() => loadPastRun(r)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '9px 12px',
                      background: currentRunId === r.id ? 'rgba(99, 102, 241, 0.08)' : 'var(--bg-card-soft)',
                      border: `1px solid ${currentRunId === r.id ? 'var(--primary)' : 'var(--border)'}`,
                      borderRadius: '6px',
                      cursor: 'pointer',
                      transition: 'all 0.15s',
                    }}
                  >
                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '70%' }}>
                      <span style={{ fontSize: '13px', color: 'var(--text-primary)', fontWeight: '500' }}>{r.goal || 'Question'}</span>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                        {formatFriendlyTime(r.created_at)}
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{r.steps_count} steps</span>
                      <span style={{
                        fontSize: '11px',
                        fontWeight: '600',
                        padding: '2px 8px',
                        borderRadius: '10px',
                        background: r.status === 'completed' ? 'rgba(16, 185, 129, 0.15)' : r.status === 'paused' ? 'rgba(245, 158, 11, 0.15)' : 'rgba(100, 116, 139, 0.15)',
                        color: r.status === 'completed' ? '#059669' : r.status === 'paused' ? '#b45309' : 'var(--text-muted)',
                      }}>
                        {r.status === 'completed' ? 'Completed' : r.status === 'paused' ? 'Needs approval' : 'In progress'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Animated Step Progress Bar */}
        {(steps.length > 0 || isRunning) && (
          <div style={{
            marginBottom: '14px',
            padding: '10px 14px',
            background: 'var(--bg-card-soft)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: '600', fontSize: '13px', color: isRunning ? 'var(--primary)' : '#059669' }}>
                <span style={{ display: 'inline-block', width: '7px', height: '7px', borderRadius: '50%', background: isRunning ? 'var(--primary)' : '#10b981', animation: isRunning ? 'pulse 1s infinite' : 'none' }} />
                {isRunning ? 'Working on it…' : 'All done ✓'}
              </span>
              <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                {steps.length} action{steps.length !== 1 ? 's' : ''} taken
              </span>
            </div>
            <div style={{ width: '100%', height: '4px', background: 'var(--border)', borderRadius: '2px', overflow: 'hidden' }}>
              <div style={{
                width: `${Math.min(100, (steps.length / 8) * 100)}%`,
                height: '100%',
                background: isRunning ? 'var(--primary)' : '#10b981',
                transition: 'width 0.3s ease',
              }} />
            </div>
          </div>
        )}

        {steps.length === 0 && !isRunning && (
          <div style={{
            textAlign: 'center',
            padding: '60px 20px',
            color: 'var(--text-muted)',
          }}>
            <div style={{ fontSize: '48px', marginBottom: '12px' }}>🧭</div>
            <div style={{ fontSize: '16px', fontWeight: '600', color: 'var(--text-primary)', marginBottom: '8px' }}>
              Your Compass Assistant
            </div>
            <div style={{ fontSize: '13px', lineHeight: '1.8', maxWidth: '400px', margin: '0 auto', color: 'var(--text-secondary)' }}>
              Ask anything about your tasks, deadlines, or schedule — in plain English.
              I'll look through everything and give you a clear answer.
              Before making any changes, I'll always ask for your approval first.
            </div>
          </div>
        )}

        {isRunning && steps.length === 0 && (
          <div style={{
            textAlign: 'center',
            padding: '40px',
            color: 'var(--primary)',
          }}>
            <div style={{ fontSize: '20px', animation: 'pulse 1.5s ease-in-out infinite' }}>
              🧭 Getting started…
            </div>
          </div>
        )}

        {steps.map((step, i) => (
          <StepCard key={i} step={step} index={i} />
        ))}



        {/* Confirmation gate UI */}
        {pendingActions.length > 0 && !isRunning && (
          <div style={{
            background: 'rgba(99, 102, 241, 0.05)',
            border: '1px solid rgba(99, 102, 241, 0.25)',
            borderRadius: '10px',
            padding: '16px',
            marginTop: '8px',
          }}>
            <div style={{ fontSize: '15px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '6px' }}>
              🙋 Ready to make {pendingActions.length} change{pendingActions.length !== 1 ? 's' : ''} — is that ok?
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '14px' }}>
              Nothing has been saved yet. Review below, then say yes or no. You can always undo changes.
            </div>
            {pendingActions.map((action, i) => (
              <div key={i} style={{
                background: 'var(--bg-card)',
                borderRadius: '8px',
                padding: '10px 14px',
                marginBottom: '6px',
                fontSize: '13px',
                color: 'var(--text-primary)',
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                border: '1px solid var(--border)',
              }}>
                <span style={{ fontSize: '16px' }}>📝</span>
                <span style={{ fontWeight: '500' }}>{formatActionDescription(action)}</span>
              </div>
            ))}
            <div style={{ marginTop: '12px' }}>
              <input
                id="agent-reject-input"
                type="text"
                value={rejectFeedback}
                onChange={e => setRejectFeedback(e.target.value)}
                placeholder="Optional: tell me what NOT to change (e.g. 'don't touch my exam date')…"
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  borderRadius: '8px',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  marginBottom: '10px',
                  outline: 'none',
                  boxSizing: 'border-box',
                  fontFamily: 'Inter, system-ui, sans-serif',
                }}
              />
            </div>
            <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
              <button
                id="agent-approve-btn"
                onClick={approveActions}
                style={{
                  padding: '9px 20px',
                  background: '#16a34a',
                  border: 'none',
                  borderRadius: '8px',
                  color: '#fff',
                  fontSize: '14px',
                  fontWeight: '600',
                  cursor: 'pointer',
                }}
              >
                ✅ Yes, go ahead
              </button>
              <button
                id="agent-reject-btn"
                onClick={rejectActions}
                style={{
                  padding: '9px 20px',
                  background: 'transparent',
                  border: '1px solid #ef4444',
                  borderRadius: '8px',
                  color: '#dc2626',
                  fontSize: '14px',
                  fontWeight: '600',
                  cursor: 'pointer',
                }}
              >
                ❌ No, try a different way
              </button>
            </div>
          </div>
        )}

        {/* Global Undo Button when steps or mutations exist */}
        {steps.some(s => s.type === 'observe' && (s.tool === 'add_task' || s.tool === 'edit_task' || s.tool === 'update_task_status' || s.tool === 'delete_task' || (s.content && s.content.includes('applied')))) && (
          <div style={{ marginTop: '12px', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <button
              id="agent-undo-btn"
              onClick={undoLastAction}
              style={{
                padding: '7px 16px',
                background: 'var(--bg-card-soft)',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                color: 'var(--text-primary)',
                fontSize: '13px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              ↩️ Undo last change
            </button>
            {undoStatus && (
              <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                {undoStatus}
              </span>
            )}
          </div>
        )}

        {isRunning && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '8px 0',
            color: 'var(--primary)',
            fontSize: '13px',
          }}>
            <span style={{ animation: 'pulse 1s ease-in-out infinite' }}>●</span>
            Still thinking…
          </div>
        )}

        {/* Activity Feed */}
        <div id="agent-activity-feed" style={{
          marginTop: '24px',
          borderTop: '1px solid var(--border)',
          paddingTop: '16px',
        }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '10px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{
                fontSize: '13px',
                fontWeight: '700',
                color: 'var(--text-primary)',
              }}>
                📋 Recent changes{activityList.length > 0 ? ` (${activityList.length})` : ''}
              </span>
            </div>
            <button
              onClick={() => { fetchActivity(); fetchCritiqueStats() }}
              style={{
                fontSize: '11px',
                background: 'transparent',
                border: 'none',
                color: 'var(--primary)',
                cursor: 'pointer',
              }}
            >
              ↻ Refresh
            </button>
          </div>

          {activityList.length === 0 ? (
            <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic', padding: '8px 0' }}>
              No changes made by the assistant yet.
            </div>
          ) : (
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '6px',
              maxHeight: '260px',
              overflowY: 'auto',
              overscrollBehavior: 'contain',
              paddingRight: '2px',
            }}>
              {activityList.map((item) => (
                <div
                  key={item.id}
                  className="agent-activity-item"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '9px 12px',
                    background: item.is_reverted ? 'var(--bg-card)' : 'var(--bg-card-soft)',
                    border: `1px solid var(--border)`,
                    borderRadius: '8px',
                    fontSize: '12px',
                    opacity: item.is_reverted ? 0.55 : 1,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: '14px' }}>
                      {item.tool === 'add_task' ? '➕' : item.tool === 'delete_task' ? '🗑️' : item.tool?.includes('ingest') ? '📥' : '✏️'}
                    </span>
                    <span style={{ color: 'var(--text-primary)', fontWeight: '600', fontSize: '12.5px' }}>
                      {formatActivityItem(item)}
                    </span>
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      {formatFriendlyTime(item.created_at)}
                    </span>
                    {item.is_reverted && (
                      <span style={{
                        fontSize: '10px',
                        padding: '1px 7px',
                        borderRadius: '10px',
                        fontWeight: '700',
                        background: 'rgba(239, 68, 68, 0.1)',
                        color: '#dc2626',
                        border: '1px solid rgba(239, 68, 68, 0.25)',
                      }}>
                        Undone
                      </span>
                    )}
                  </div>

                  {!item.is_reverted && (
                    <button
                      className="agent-revert-btn"
                      onClick={() => revertActivityItem(item.id)}
                      style={{
                        padding: '4px 10px',
                        background: 'var(--bg-card)',
                        border: '1px solid var(--border)',
                        borderRadius: '6px',
                        color: 'var(--text-secondary)',
                        fontSize: '11px',
                        fontWeight: '600',
                        cursor: 'pointer',
                        whiteSpace: 'nowrap',
                        flexShrink: 0,
                      }}
                    >
                      ↩️ Undo
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
