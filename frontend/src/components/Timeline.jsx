import React, { useState, useMemo, useEffect, useRef, useCallback } from 'react'
import { X } from 'lucide-react'
import {
  deleteTask,
  updateTask,
  seedJudgeDemoPersona,
  verifyAllDeadlines,
} from '../api/client'
import { mapPersonaError } from '../utils/personaNotice'
import OnboardingTour from './OnboardingTour'
import { getDomainMeta } from './timeline/domainMeta'
import TaskCard from './timeline/TaskCard'
import TaskDetailModal from './timeline/TaskDetailModal'
import AddDeadlineModal from './timeline/AddDeadlineModal'
import TimelineHeader from './timeline/TimelineHeader'
import Logo from './Logo'
import TimelineFilterBar from './timeline/TimelineFilterBar'
import {
  filterTasksByStatusAndDue,
  calculateFilterCounts,
} from '../utils/deadlineClassifier'

// Re-export for backward compatibility
export { getDomainMeta } from './timeline/domainMeta'

export default function Timeline({
  tasks = [],
  allTasks = [],
  activeDomain,
  onSelectDomain,
  onTasksUpdated,
  onOpenCompass,
  onOpenTelemetry,
  customDomains = [],
  theme = 'light',
  onToggleTheme,
  isDarkMode,
  onToggleDarkMode,
}) {
  const darkMode = typeof isDarkMode === 'boolean' ? isDarkMode : theme === 'dark'
  const toggleDark = onToggleDarkMode || onToggleTheme
  const [selectedTask, setSelectedTask] = useState(null)
  const [showAddModal, setShowAddModal] = useState(false)
  const [seedingPersona, setSeedingPersona] = useState(false)
  const [seedSuccess, setSeedSuccess] = useState(false)
  const [highlightedTaskId, setHighlightedTaskId] = useState(() => {
    try {
      return window.sessionStorage.getItem('compass_highlight_task_id') || null
    } catch {
      return null
    }
  })

  useEffect(() => {
    const handleHighlight = (e) => {
      const tid = e.detail?.taskId
      if (tid) {
        setHighlightedTaskId(String(tid))
      }
    }
    window.addEventListener('compass:highlight-task', handleHighlight)
    return () => window.removeEventListener('compass:highlight-task', handleHighlight)
  }, [])

  useEffect(() => {
    if (highlightedTaskId) {
      const el = document.getElementById(`task-card-${highlightedTaskId}`)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
      const timer = setTimeout(() => {
        setHighlightedTaskId(null)
        try {
          window.sessionStorage.removeItem('compass_highlight_task_id')
        } catch {
          /* ignore storage error */
        }
      }, 3500)
      return () => clearTimeout(timer)
    }
  }, [highlightedTaskId])

  const [verifyingDeadlines, setVerifyingDeadlines] = useState(false)
  const [verificationSummary, setVerificationSummary] = useState(null)

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

  const [seedNotice, setSeedNotice] = useState(null)
  const retryTimeoutRef = useRef(null)

  useEffect(() => {
    return () => {
      if (retryTimeoutRef.current) clearTimeout(retryTimeoutRef.current)
    }
  }, [])

  const handleSeedJudgePersona = useCallback(async (isRetry = false) => {
    if (seedingPersona && !isRetry) return
    if (!isRetry && retryTimeoutRef.current) {
      clearTimeout(retryTimeoutRef.current)
      retryTimeoutRef.current = null
    }
    setSeedingPersona(true)
    if (!isRetry) {
      setSeedNotice(null)
    }
    try {
      await seedJudgeDemoPersona()
      setSeedSuccess(true)
      setSeedNotice({
        type: 'success',
        text: 'Judge Persona loaded successfully! 21 multi-domain tasks & timeline populated.',
        canRetry: false,
      })
      setTimeout(() => setSeedSuccess(false), 3000)
      if (onTasksUpdated) await onTasksUpdated()
    } catch (err) {
      const mapped = mapPersonaError(err)
      if (mapped.is503 && !isRetry) {
        setSeedNotice({
          type: 'info',
          text: mapped.text,
          canRetry: true,
        })
        const delay = (mapped.retryDelay || 5) * 1000
        retryTimeoutRef.current = setTimeout(() => {
          handleSeedJudgePersona(true)
        }, delay)
      } else {
        setSeedNotice({
          type: mapped.type === 'info' ? 'error' : mapped.type,
          text: mapped.is503
            ? 'The server is waking up or temporarily unavailable.'
            : mapped.text,
          canRetry: mapped.canRetry,
        })
      }
    } finally {
      setSeedingPersona(false)
    }
  }, [seedingPersona, onTasksUpdated])

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

  const domainMeta = activeDomain !== 'all' ? getDomainMeta(activeDomain) : null
  const filtered = activeDomain === 'all'
    ? tasks
    : tasks.filter(t => (t.domain || 'general').toLowerCase().trim() === activeDomain)

  const [statusFilter, setStatusFilter] = useState('all')
  const [dueFilter, setDueFilter] = useState('all')

  const filterCounts = useMemo(() => {
    const now = new Date()
    return calculateFilterCounts(filtered, statusFilter, dueFilter, now)
  }, [filtered, statusFilter, dueFilter])

  const displayedTasks = useMemo(() => {
    const now = new Date()
    return filterTasksByStatusAndDue(filtered, statusFilter, dueFilter, now)
  }, [filtered, statusFilter, dueFilter])

  const handleClearFilters = () => {
    setStatusFilter('all')
    setDueFilter('all')
  }

  const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })
  const hasFallbackTasks = Array.isArray(tasks) && tasks.some(t => t.is_fallback)

  return (
    <div className="timeline-container" style={{ background: 'var(--bg-app)' }}>
      {hasFallbackTasks && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 16px',
          background: 'rgba(245, 166, 35, 0.08)',
          border: '1px solid rgba(245, 166, 35, 0.25)',
          borderRadius: 'var(--radius-card, 8px)',
          marginBottom: '18px',
          fontSize: '13px',
          color: 'var(--text-primary)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--accent, #f5a623)' }}>
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
            </svg>
            <span><strong>Demo / Offline Mode:</strong> Backend server is offline or starting up. Displaying sample tasks. Your local actions will sync once connected.</span>
          </div>
          <span style={{ fontSize: '11px', background: 'rgba(245, 166, 35, 0.15)', color: 'var(--text-primary)', padding: '3px 8px', borderRadius: 'var(--radius-btn, 6px)', fontWeight: '600' }}>Demo Data</span>
        </div>
      )}

      {/* Inline Judge Persona Feedback Banner */}
      {seedNotice && (
        <div
          role="status"
          aria-live="polite"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
            padding: '10px 14px',
            marginBottom: '16px',
            borderRadius: '6px',
            background:
              seedNotice.type === 'success'
                ? 'rgba(16, 185, 129, 0.12)'
                : seedNotice.type === 'disabled'
                ? 'rgba(217, 119, 6, 0.12)'
                : seedNotice.type === 'info'
                ? 'rgba(59, 130, 246, 0.12)'
                : 'rgba(239, 68, 68, 0.12)',
            border:
              seedNotice.type === 'success'
                ? '1px solid rgba(16, 185, 129, 0.35)'
                : seedNotice.type === 'disabled'
                ? '1px solid rgba(217, 119, 6, 0.35)'
                : seedNotice.type === 'info'
                ? '1px solid rgba(59, 130, 246, 0.35)'
                : '1px solid rgba(239, 68, 68, 0.35)',
            color:
              seedNotice.type === 'success'
                ? '#059669'
                : seedNotice.type === 'disabled'
                ? '#d97706'
                : seedNotice.type === 'info'
                ? '#2563eb'
                : '#dc2626',
            fontSize: '13px',
            fontWeight: '500',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontWeight: '600' }}>
              {seedNotice.type === 'success' ? '✓' : seedNotice.type === 'disabled' ? '⚠️' : seedNotice.type === 'info' ? 'ℹ️' : '✕'}
            </span>
            <span>{seedNotice.text}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {seedNotice.canRetry && (
              <button
                type="button"
                onClick={() => handleSeedJudgePersona(true)}
                disabled={seedingPersona}
                style={{
                  background: 'transparent',
                  border: '1px solid currentColor',
                  borderRadius: '4px',
                  padding: '2px 8px',
                  fontSize: '12px',
                  fontWeight: '600',
                  color: 'inherit',
                  cursor: seedingPersona ? 'wait' : 'pointer',
                }}
              >
                Retry
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                if (retryTimeoutRef.current) clearTimeout(retryTimeoutRef.current)
                setSeedNotice(null)
              }}
              className="btn-touch-target"
              style={{
                background: 'transparent',
                border: 'none',
                cursor: 'pointer',
                color: 'inherit',
                padding: '4px',
                display: 'flex',
                alignItems: 'center',
              }}
              aria-label="Dismiss message"
            >
              <X size={14} />
            </button>
          </div>
        </div>
      )}

      <TimelineHeader
        today={today}
        domainMeta={domainMeta}
        onSelectDomain={onSelectDomain}
        darkMode={darkMode}
        toggleDark={toggleDark}
        onOpenTelemetry={onOpenTelemetry}
        onVerifyAll={handleVerifyAll}
        verifyingDeadlines={verifyingDeadlines}
        onSeedJudgePersona={() => handleSeedJudgePersona(false)}
        seedingPersona={seedingPersona}
        seedSuccess={seedSuccess}
        onOpenNewTask={() => setShowAddModal(true)}
        verificationSummary={verificationSummary}
        onClearVerificationSummary={() => setVerificationSummary(null)}
      />

      {/* Judge Onboarding & Architectural Tour */}
      <OnboardingTour
        onVerifyDeadlines={handleVerifyAll}
        onOpenTelemetry={onOpenTelemetry}
        onOpenCompass={onOpenCompass}
        onOpenSeed={() => handleSeedJudgePersona(false)}
      />

      {/* Filter pills: horizontal scroll on mobile, 6px radius, min 44px tap target, domain swatch */}
      <div
        className="domain-filter-pills-row quick-prompts-scroll"
        style={{
          display: 'flex',
          gap: '8px',
          marginBottom: '20px',
          overflowX: 'auto',
          overflowY: 'hidden',
          paddingBottom: '4px',
          maxWidth: '100%',
          WebkitOverflowScrolling: 'touch',
        }}
      >
        {(() => {
          const basePills = ['all', 'hackathon', 'coursework', 'code', 'general', 'other']
          const customPills = [
            ...customDomains.map(d => d.key),
            ...tasks.map(t => (t.domain || '').toLowerCase().trim()),
            ...allTasks.map(t => (t.domain || '').toLowerCase().trim()),
          ].filter(d => d && !basePills.includes(d))
          const uniquePills = Array.from(new Set([...basePills, ...customPills]))

          return uniquePills.map(dom => {
            const pillMeta = dom === 'all' ? { label: 'All' } : getDomainMeta(dom)
            const isSelected = activeDomain === dom
            return (
              <button
                key={dom}
                id={`filter-pill-${dom}`}
                onClick={() => onSelectDomain(dom)}
                className={`filter-pill ${isSelected ? 'active' : ''}`}
                style={{
                  flexShrink: 0,
                  minHeight: '44px',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '0 14px',
                  fontSize: '13px',
                  fontWeight: isSelected ? '600' : '400',
                  borderRadius: 'var(--radius-btn, 6px)',
                }}
              >
                {dom !== 'all' && pillMeta.color && (
                  <span
                    className="domain-swatch"
                    style={{ background: pillMeta.color }}
                  />
                )}
                {pillMeta.label}
              </button>
            )
          })
        })()}
      </div>

      {/* Status & Due Filter Bar */}
      <TimelineFilterBar
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
        dueFilter={dueFilter}
        onDueChange={setDueFilter}
        statusCounts={filterCounts.statusCounts}
        dueCounts={filterCounts.dueCounts}
        baseOverdueCount={filterCounts.baseOverdueCount}
        totalCount={filtered.length}
        filteredCount={displayedTasks.length}
        onClearFilters={handleClearFilters}
      />

      {/* Task Stream Feed */}
      <div className="timeline-feed">
        {filtered.length === 0 ? (
          <div style={{
            padding: '48px 20px',
            textAlign: 'center',
            background: 'var(--bg-card)',
            borderRadius: 'var(--radius-card, 8px)',
            border: '1px solid var(--border)',
            color: 'var(--text-secondary)',
            marginTop: '10px',
            width: '100%',
            boxSizing: 'border-box'
          }}>
            <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '12px' }}>
              <Logo size={32} alt="Compass logo" />
            </div>
            <div style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)', marginBottom: '6px' }}>
              {activeDomain === 'all' ? 'No tasks yet' : 'Nothing here yet'}
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)', maxWidth: '480px', margin: '0 auto', lineHeight: 1.5 }}>
              {activeDomain === 'all'
                ? 'Use the Add deadline button in the header above to create your first milestone, or click Load Judge Persona to populate demo multi-domain tasks.'
                : `No deadlines in ${getDomainMeta(activeDomain).label} yet. Use Add deadline in the header above to create one.`}
            </div>
          </div>
        ) : displayedTasks.length === 0 ? (
          <div style={{
            padding: '40px 20px',
            textAlign: 'center',
            background: 'var(--bg-card)',
            borderRadius: 'var(--radius-card, 8px)',
            border: '1px solid var(--border)',
            color: 'var(--text-secondary)',
            marginTop: '10px',
            width: '100%',
            boxSizing: 'border-box'
          }}>
            <p style={{ margin: 0, fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)' }}>
              No tasks match the selected filters
            </p>
            <p style={{ margin: '6px 0 16px 0', fontSize: '13px', color: 'var(--text-muted)' }}>
              Try adjusting your status or due date filters to see more tasks.
            </p>
            <button
              type="button"
              id="timeline-btn-empty-clear-filters"
              onClick={handleClearFilters}
              className="btn-secondary"
              style={{
                minHeight: '44px',
                padding: '0 16px',
                fontSize: '13px',
                fontWeight: '600',
                borderRadius: 'var(--radius-btn, 6px)',
                cursor: 'pointer',
              }}
            >
              Clear filters
            </button>
          </div>
        ) : displayedTasks.map(task => (
          <TaskCard
            key={task.id}
            task={task}
            isHighlighted={String(highlightedTaskId) === String(task.id)}
            onSelectTask={setSelectedTask}
            onDeleteTask={handleDelete}
            onToggleStatus={handleToggleStatus}
          />
        ))}
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
        customDomains={customDomains}
        onOpenCompass={onOpenCompass}
      />
    </div>
  )
}
