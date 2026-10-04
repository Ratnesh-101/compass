import React from 'react'

const SUGGESTED_GOALS = [
  "I have 5 days left and I'm working 4 hours a day. Go through everything I have open across the hackathon, my coursework, and my code debt, and tell me honestly whether I can finish it — and if I can't, decide what I drop.",
  "Plan my week considering all hackathon deadlines and coursework",
  "Flag any deadline conflicts this week and suggest resolutions",
  "Write a retrospective for the Compass project",
  "What are my most urgent tasks across all domains?",
  "Summarize my open tasks and suggest what to tackle first",
]

export default function AgentHeader({
  goal,
  setGoal,
  isRunning,
  onRunAgent,
  onStopAgent,
  proactiveBriefing,
  onLoadProactiveBriefing,
  triggeringNightly,
  onTriggerNightly,
  showHistory,
  setShowHistory,
  runsListCount = 0,
  onFetchRunsHistory,
  steps = [],
  onCopyTrace,
  copyFeedback,
  setRejectFeedback,
}) {
  return (
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
              onClick={onLoadProactiveBriefing}
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
              onClick={onTriggerNightly}
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

      <div style={{ display: 'flex', gap: '8px', marginBottom: '10px' }}>
        <input
          id="agent-goal-input"
          type="text"
          value={goal}
          onChange={e => setGoal(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !isRunning && onRunAgent(goal)}
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
            onClick={onStopAgent}
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
            onClick={() => onRunAgent(goal)}
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
          onClick={() => { onFetchRunsHistory(); setShowHistory(!showHistory) }}
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
          📜 Past Plans ({runsListCount})
        </button>

        {steps.length > 0 && (
          <button
            id="agent-copy-trace-btn"
            onClick={onCopyTrace}
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
              onRunAgent(demoGoal)
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
              onRunAgent(demoGoal)
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
              onRunAgent(demoGoal)
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
              onClick={() => { setGoal(sg); onRunAgent(sg) }}
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
  )
}
