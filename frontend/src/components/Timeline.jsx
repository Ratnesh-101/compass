import React, { useState, useMemo } from 'react'
import {
  deleteTask,
  updateTask,
  seedJudgeDemoPersona,
  verifyAllDeadlines,
} from '../api/client'
import OnboardingTour from './OnboardingTour'
import TaskCard from './timeline/TaskCard'
import TaskDetailModal from './timeline/TaskDetailModal'
import AddDeadlineModal from './timeline/AddDeadlineModal'
import TimelineHeader from './timeline/TimelineHeader'
import TimelineMetrics from './timeline/TimelineMetrics'
import TimelineAiPlanner from './timeline/TimelineAiPlanner'
import TimelineFilters from './timeline/TimelineFilters'
import { Plus, Zap } from 'lucide-react'

// Re-export for backward compatibility
export { getDomainMeta } from './timeline/domainMeta'

export default function Timeline({
  tasks = [],
  activeDomain,
  onSelectDomain,
  onTasksUpdated,
  onOpenCompass,
  onOpenTelemetry,
}) {
  const handleOpenCompass = onOpenCompass
  const [selectedTask, setSelectedTask] = useState(null)
  const [showAddModal, setShowAddModal] = useState(false)
  const [seedingPersona, setSeedingPersona] = useState(false)
  const [seedSuccess, setSeedSuccess] = useState(false)
  const [verifyingDeadlines, setVerifyingDeadlines] = useState(false)
  const [verificationSummary, setVerificationSummary] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all') // 'all' | 'open' | 'completed' | 'urgent'
  const [quickAiPrompt, setQuickAiPrompt] = useState('')

  const handleVerifyAll = async () => {
    setVerifyingDeadlines(true)
    setVerificationSummary(null)
    try {
      const res = await verifyAllDeadlines()
      if (res && res.verifications) {
        const driftCount = res.verifications.filter(v => v.result?.data?.drift_analysis?.has_drift).length
        const accurateCount = res.verifications.filter(v => v.result?.data?.drift_analysis?.drift_verdict === 'CONFIRMED_ACCURATE').length
        setVerificationSummary({
          total: res.verifications.length,
          drift: driftCount,
          accurate: accurateCount,
          details: res.verifications,
        })
      }
      if (onTasksUpdated) onTasksUpdated()
    } catch (err) {
      setVerificationSummary({ error: err.message || 'Verification failed' })
    } finally {
      setVerifyingDeadlines(false)
    }
  }

  const handleSeedJudgePersona = async () => {
    setSeedingPersona(true)
    try {
      await seedJudgeDemoPersona()
      setSeedSuccess(true)
      setTimeout(() => setSeedSuccess(false), 3000)
      if (onTasksUpdated) onTasksUpdated()
    } catch (err) {
      alert(`Could not load judge persona: ${err.message}`)
    } finally {
      setSeedingPersona(false)
    }
  }

  const handleDelete = async (taskId) => {
    try {
      await deleteTask(taskId)
      if (onTasksUpdated) {
        onTasksUpdated()
      }
    } catch (err) {
      alert(`Failed to delete deadline: ${err.message}`)
      throw err
    }
  }

  const handleToggleStatus = async (taskId, isCompleted) => {
    try {
      await updateTask(taskId, { status: isCompleted ? 'open' : 'completed' })
      if (onTasksUpdated) onTasksUpdated()
    } catch (err) {
      console.warn('Failed to toggle status:', err)
    }
  }

  // Executive Metric Calculations
  const metrics = useMemo(() => {
    const total = tasks.length
    const completed = tasks.filter(t => t.status === 'completed' || t.status === 'done').length
    const open = total - completed
    const progressPct = total > 0 ? Math.round((completed / total) * 100) : 0
    const overdue = tasks.filter(t => (t.countdown || '').toLowerCase().includes('overdue')).length
    const urgent = tasks.filter(t => {
      const prio = String(t.priority || '').toLowerCase()
      const cd = String(t.countdown || '').toLowerCase()
      return prio === 'urgent' || cd.includes('today') || cd.includes('hour') || cd.includes('overdue')
    }).length

    const openTasks = tasks.filter(t => t.status !== 'completed' && t.status !== 'done')
    const focusMinutes = openTasks.reduce((sum, t) => sum + (Number(t.duration_minutes) || 45), 0)
    const focusHours = (focusMinutes / 60).toFixed(1)

    return { total, completed, open, progressPct, overdue, urgent, focusHours }
  }, [tasks])

  // Multi-dimensional Filtering: Domain + Search Query + Status Filter
  const filteredTasks = useMemo(() => {
    return tasks.filter(t => {
      // Domain filter
      if (activeDomain !== 'all' && t.domain !== activeDomain) return false

      // Status filter
      const isComp = t.status === 'completed' || t.status === 'done'
      if (statusFilter === 'open' && isComp) return false
      if (statusFilter === 'completed' && !isComp) return false
      if (statusFilter === 'urgent') {
        const isUrg = String(t.priority || '').toLowerCase() === 'urgent' ||
                      (t.countdown || '').toLowerCase().includes('overdue') ||
                      (t.countdown || '').toLowerCase().includes('today')
        if (!isUrg) return false
      }

      // Search Query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        const matchTitle = (t.title || '').toLowerCase().includes(q)
        const matchDesc = (t.description || '').toLowerCase().includes(q)
        const matchProj = (t.project || '').toLowerCase().includes(q)
        const matchTags = Array.isArray(t.tags) && t.tags.some(tag => tag.toLowerCase().includes(q))
        if (!matchTitle && !matchDesc && !matchProj && !matchTags) return false
      }

      return true
    })
  }, [tasks, activeDomain, statusFilter, searchQuery])

  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
  })

  const hasFallbackTasks = Array.isArray(tasks) && tasks.some(t => t.is_fallback)

  const handleQuickAiSubmit = (e) => {
    e.preventDefault()
    if (!quickAiPrompt.trim()) return
    if (handleOpenCompass) {
      handleOpenCompass(quickAiPrompt)
      setQuickAiPrompt('')
    }
  }

  return (
    <div className="timeline-container" style={{ background: '#f8fafc', padding: '28px 32px' }}>
      {/* Offline / Demo Warning if applicable */}
      {hasFallbackTasks && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 16px',
            background: 'rgba(245, 158, 11, 0.1)',
            border: '1px solid rgba(245, 158, 11, 0.3)',
            borderRadius: '10px',
            marginBottom: '20px',
            fontSize: '12.5px',
            color: '#b45309',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Zap size={16} color="#f59e0b" />
            <span>
              <strong>Demo Mode:</strong> Backend server is connecting. Displaying sample tasks.
            </span>
          </div>
          <span
            style={{
              fontSize: '11px',
              background: 'rgba(245, 158, 11, 0.2)',
              padding: '2px 8px',
              borderRadius: '6px',
              fontWeight: '700',
            }}
          >
            Demo Context
          </span>
        </div>
      )}

      {/* Top Header Bar */}
      <TimelineHeader
        today={today}
        onOpenTelemetry={onOpenTelemetry}
        onVerifyAll={handleVerifyAll}
        verifyingDeadlines={verifyingDeadlines}
        onSeedJudgePersona={handleSeedJudgePersona}
        seedingPersona={seedingPersona}
        seedSuccess={seedSuccess}
        onOpenNewTask={() => setShowAddModal(true)}
        verificationSummary={verificationSummary}
        onClearVerificationSummary={() => setVerificationSummary(null)}
      />

      {/* Metric Cards Row */}
      <TimelineMetrics metrics={metrics} />

      {/* AI Planning & Copilot Quick Panel */}
      <TimelineAiPlanner
        quickAiPrompt={quickAiPrompt}
        setQuickAiPrompt={setQuickAiPrompt}
        onQuickAiSubmit={handleQuickAiSubmit}
        onOpenCompass={handleOpenCompass}
      />

      {/* Onboarding Tour */}
      <OnboardingTour
        onVerifyDeadlines={handleVerifyAll}
        onOpenTelemetry={onOpenTelemetry}
        onOpenCompass={handleOpenCompass}
        onOpenSeed={handleSeedJudgePersona}
      />

      {/* Filter and Search Bar */}
      <TimelineFilters
        tasks={tasks}
        activeDomain={activeDomain}
        onSelectDomain={onSelectDomain}
        statusFilter={statusFilter}
        setStatusFilter={setStatusFilter}
        searchQuery={searchQuery}
        setSearchQuery={setSearchQuery}
      />

      {/* Task Stream Feed */}
      <div className="timeline-feed">
        {filteredTasks.length === 0 ? (
          <div
            style={{
              padding: '48px 20px',
              textAlign: 'center',
              background: '#ffffff',
              borderRadius: '16px',
              border: '1px dashed #cbd5e1',
              color: '#64748b',
              marginTop: '10px',
              width: '100%',
              boxSizing: 'border-box',
            }}
          >
            <div style={{ fontSize: '36px', marginBottom: '12px' }}>📭</div>
            <div style={{ fontSize: '16px', fontWeight: '700', color: '#0f172a', marginBottom: '6px' }}>
              No tasks found
            </div>
            <div style={{ fontSize: '13px', color: '#94a3b8', marginBottom: '18px', maxWidth: '420px', margin: '0 auto 18px auto' }}>
              {searchQuery
                ? `No tasks matched your search query "${searchQuery}". Try clearing search or resetting filters.`
                : activeDomain === 'all'
                ? 'Your task queue is completely clear. Add your first goal below or ask Compass to draft one.'
                : `No active tasks found in the ${activeDomain.toUpperCase()} domain.`}
            </div>
            <button
              id="btn-empty-add-deadline"
              onClick={() => setShowAddModal(true)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                background: 'linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)',
                border: 'none',
                color: '#ffffff',
                padding: '9px 18px',
                borderRadius: '8px',
                fontSize: '13px',
                fontWeight: '600',
                cursor: 'pointer',
                boxShadow: '0 4px 12px rgba(37, 99, 235, 0.25)',
              }}
            >
              <Plus size={15} />
              <span>Create Task</span>
            </button>
          </div>
        ) : (
          filteredTasks.map(task => (
            <TaskCard
              key={task.id}
              task={task}
              onSelectTask={setSelectedTask}
              onDeleteTask={handleDelete}
              onToggleStatus={handleToggleStatus}
            />
          ))
        )}
      </div>

      <TaskDetailModal
        task={selectedTask}
        onClose={() => setSelectedTask(null)}
        onDelete={handleDelete}
        onUpdated={() => {
          setSelectedTask(null)
          if (onTasksUpdated) onTasksUpdated()
        }}
      />

      <AddDeadlineModal
        isOpen={showAddModal}
        onClose={() => setShowAddModal(false)}
        onCreated={onTasksUpdated}
        defaultDomain={activeDomain}
        tasks={tasks}
        onOpenCompass={handleOpenCompass}
      />
    </div>
  )
}
