import React from 'react'

export const STEP_STYLES = {
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

export function friendlyTool(toolName) {
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

export function ReplanDiffCard({ diff }) {
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

export function ReportCard({ reportCard }) {
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

export default function StepCard({ step, index }) {
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
