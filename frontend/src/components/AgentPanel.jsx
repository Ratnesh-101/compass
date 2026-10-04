import React, { useState, useRef, useEffect, useCallback } from 'react'
import { getAuthHeaders } from '../api/client'
import StepCard, { STEP_STYLES, friendlyTool } from './agent/StepCard'
import ConfirmationGate from './agent/ConfirmationGate'
import ActivityFeed from './agent/ActivityFeed'
import RunHistoryDrawer from './agent/RunHistoryDrawer'
import AgentHeader from './agent/AgentHeader'

export default function AgentPanel({ onTaskMutated, conversationId }) {
  const [goal, setGoal] = useState('')
  const [steps, setSteps] = useState([])
  const [isRunning, setIsRunning] = useState(false)
  const [pendingActions, setPendingActions] = useState([])
  const [currentRunId, setCurrentRunId] = useState(null)
  const [undoStatus, setUndoStatus] = useState(null)
  const [rejectFeedback, setRejectFeedback] = useState('')
  const [activityList, setActivityList] = useState([])
  const [_critiqueStats, setCritiqueStats] = useState(null)
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

  const fetchRunsHistory = useCallback(async () => {
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
  }, [])

  const fetchActivity = useCallback(async () => {
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
  }, [])

  const fetchCritiqueStats = useCallback(async () => {
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
  }, [])

  const fetchProactiveBriefing = useCallback(async () => {
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
  }, [])

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
  }, [fetchActivity, fetchCritiqueStats, fetchProactiveBriefing, fetchRunsHistory])

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

      {/* Goal Input & Header Area */}
      <AgentHeader
        goal={goal}
        setGoal={setGoal}
        isRunning={isRunning}
        onRunAgent={runAgent}
        onStopAgent={stopAgent}
        proactiveBriefing={proactiveBriefing}
        onLoadProactiveBriefing={loadProactiveBriefingTrace}
        triggeringNightly={triggeringNightly}
        onTriggerNightly={triggerNightlyJob}
        showHistory={showHistory}
        setShowHistory={setShowHistory}
        runsListCount={runsList.length}
        onFetchRunsHistory={fetchRunsHistory}
        steps={steps}
        onCopyTrace={copyTraceAsMarkdown}
        copyFeedback={copyFeedback}
        setRejectFeedback={setRejectFeedback}
      />

      {/* Execution Trace */}
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
        <RunHistoryDrawer
          isOpen={showHistory}
          onClose={() => setShowHistory(false)}
          runsList={runsList}
          currentRunId={currentRunId}
          onLoadPastRun={loadPastRun}
        />

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

        <ConfirmationGate
          pendingActions={pendingActions}
          rejectFeedback={rejectFeedback}
          setRejectFeedback={setRejectFeedback}
          onApprove={approveActions}
          onReject={rejectActions}
        />

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

        <ActivityFeed
          activityList={activityList}
          onRefresh={() => { fetchActivity(); fetchCritiqueStats() }}
          onRevertItem={revertActivityItem}
        />
      </div>
    </div>
  )
}
