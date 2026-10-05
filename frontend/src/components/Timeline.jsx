import React, { useState } from 'react'
import {
  deleteTask,
  updateTask,
  seedJudgeDemoPersona,
  verifyAllDeadlines,
} from '../api/client'
import OnboardingTour from './OnboardingTour'
import { getDomainMeta } from './timeline/domainMeta'
import TaskCard from './timeline/TaskCard'
import TaskDetailModal from './timeline/TaskDetailModal'
import AddDeadlineModal from './timeline/AddDeadlineModal'

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
}) {
  const [selectedTask, setSelectedTask] = useState(null)
  const [showAddModal, setShowAddModal] = useState(false)
  const [seedingPersona, setSeedingPersona] = useState(false)
  const [seedSuccess, setSeedSuccess] = useState(false)
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

  const domainMeta = activeDomain !== 'all' ? getDomainMeta(activeDomain) : null
  const filtered = activeDomain === 'all'
    ? tasks
    : tasks.filter(t => (t.domain || 'general').toLowerCase().trim() === activeDomain)
  const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })
  const hasFallbackTasks = Array.isArray(tasks) && tasks.some(t => t.is_fallback)

  return (
    <div className="timeline-container" style={{ background: 'var(--bg-app)' }}>
      {hasFallbackTasks && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 16px',
          background: 'rgba(245, 158, 11, 0.1)',
          border: '1px solid rgba(245, 158, 11, 0.3)',
          borderRadius: '10px',
          marginBottom: '18px',
          fontSize: '12.5px',
          color: '#fbbf24',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '15px' }}>⚡</span>
            <span><strong>Demo / Offline Mode:</strong> Backend server is offline or starting up. Displaying sample tasks. Your local actions will sync once connected.</span>
          </div>
          <span style={{ fontSize: '11px', opacity: 0.9, background: 'rgba(245, 158, 11, 0.2)', padding: '2px 8px', borderRadius: '6px', fontWeight: '600' }}>Demo Data</span>
        </div>
      )}

      {/* Header with Direct Add Deadline Button */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '22px', gap: '16px', flexWrap: 'wrap' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <h2 style={{ fontSize: '24px', fontWeight: '800', color: 'var(--text-primary)', letterSpacing: '-0.4px', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              {domainMeta ? (
                <>
                  <span style={{ fontSize: '22px' }}>{domainMeta.icon}</span>
                  <span>{domainMeta.label} Domain</span>
                </>
              ) : (
                <span>Timeline Feed</span>
              )}
              <span className="serif-accent" style={{ color: 'var(--text-secondary)', fontWeight: '600' }}>— {today}</span>
            </h2>
            {domainMeta && (
              <button
                type="button"
                id="btn-return-all-domains"
                onClick={() => onSelectDomain('all')}
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-secondary)',
                  padding: '3px 10px',
                  borderRadius: '12px',
                  fontSize: '11px',
                  fontWeight: '600',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
                onMouseEnter={e => { e.currentTarget.style.color = 'var(--brand)'; e.currentTarget.style.borderColor = 'var(--brand)' }}
                onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-secondary)'; e.currentTarget.style.borderColor = 'var(--border)' }}
                title="View all domains"
              >
                ← View all
              </button>
            )}
          </div>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginTop: '4px', marginBottom: 0 }}>
            {domainMeta
              ? `Deadlines, context, and focus allocation for ${domainMeta.label}`
              : "What's happening across your workspace today"}
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
          {onToggleTheme && (
            <button
              id="header-theme-toggle"
              type="button"
              role="switch"
              aria-checked={theme === 'dark'}
              aria-label={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`}
              title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`}
              onClick={onToggleTheme}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                background: 'var(--bg-card)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border)',
                padding: '9px 13px',
                borderRadius: '10px',
                fontSize: '13px',
                fontWeight: '600',
                cursor: 'pointer',
                boxShadow: 'var(--shadow-sm)',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.borderColor = 'var(--brand)'
                e.currentTarget.style.transform = 'translateY(-1px)'
              }}
              onMouseLeave={e => {
                e.currentTarget.style.borderColor = 'var(--border)'
                e.currentTarget.style.transform = 'translateY(0)'
              }}
            >
              <span>{theme === 'dark' ? '🌙' : '☀️'}</span>
              <span>{theme === 'dark' ? 'Dark' : 'Light'}</span>
            </button>
          )}

          {onOpenTelemetry && (
            <button
              id="btn-open-telemetry"
              type="button"
              onClick={onOpenTelemetry}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                background: 'rgba(245, 166, 35, 0.1)',
                color: '#fbbf24',
                border: '1px solid rgba(245, 166, 35, 0.35)',
                padding: '9px 14px',
                borderRadius: '10px',
                fontSize: '13px',
                fontWeight: '700',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.background = 'rgba(245, 166, 35, 0.2)'
                e.currentTarget.style.transform = 'translateY(-1px)'
              }}
              onMouseLeave={e => {
                e.currentTarget.style.background = 'rgba(245, 166, 35, 0.1)'
                e.currentTarget.style.transform = 'translateY(0)'
              }}
              title="Inspect live Nebius Token Factory token consumption and NVIDIA model hierarchy"
            >
              <span>⚡</span>
              <span>Nebius & NVIDIA Telemetry</span>
            </button>
          )}

          <button
            id="btn-verify-all-deadlines"
            type="button"
            onClick={handleVerifyAll}
            disabled={verifyingDeadlines}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              background: 'rgba(56, 189, 248, 0.12)',
              color: '#38bdf8',
              border: '1px solid rgba(56, 189, 248, 0.35)',
              padding: '9px 14px',
              borderRadius: '10px',
              fontSize: '13px',
              fontWeight: '700',
              cursor: verifyingDeadlines ? 'wait' : 'pointer',
              transition: 'all 0.15s ease',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.background = 'rgba(56, 189, 248, 0.22)'
              e.currentTarget.style.transform = 'translateY(-1px)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.background = 'rgba(56, 189, 248, 0.12)'
              e.currentTarget.style.transform = 'translateY(0)'
            }}
            title="Proactively verify open deadlines across the live web using Tavily search"
          >
            <span>{verifyingDeadlines ? '⏳' : '🔍'}</span>
            <span>{verifyingDeadlines ? 'Verifying with Tavily...' : 'Verify with Tavily'}</span>
          </button>

          <button
            id="btn-seed-judge-persona"
            type="button"
            onClick={handleSeedJudgePersona}
            disabled={seedingPersona}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              background: seedSuccess ? 'rgba(16, 185, 129, 0.15)' : 'rgba(96, 165, 250, 0.12)',
              color: seedSuccess ? '#34d399' : '#60a5fa',
              border: `1px solid ${seedSuccess ? 'rgba(16, 185, 129, 0.4)' : 'rgba(96, 165, 250, 0.35)'}`,
              padding: '9px 14px',
              borderRadius: '10px',
              fontSize: '13px',
              fontWeight: '700',
              cursor: seedingPersona ? 'wait' : 'pointer',
              transition: 'all 0.15s ease',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.background = seedSuccess ? 'rgba(16, 185, 129, 0.25)' : 'rgba(96, 165, 250, 0.22)'
              e.currentTarget.style.transform = 'translateY(-1px)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.background = seedSuccess ? 'rgba(16, 185, 129, 0.15)' : 'rgba(96, 165, 250, 0.12)'
              e.currentTarget.style.transform = 'translateY(0)'
            }}
            title="1-Click Demo: Populates sample multi-domain tasks and vector memory for hackathon judges"
          >
            <span>{seedSuccess ? '✓' : '🎯'}</span>
            <span>{seedingPersona ? 'Loading...' : seedSuccess ? 'Demo Persona Loaded!' : 'Load Judge Persona'}</span>
          </button>

          <button
            id="btn-add-deadline"
            onClick={() => setShowAddModal(true)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              background: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
              color: '#ffffff',
              border: 'none',
              padding: '10px 18px',
              borderRadius: '10px',
              fontSize: '13.5px',
              fontWeight: '600',
              cursor: 'pointer',
              boxShadow: '0 4px 14px rgba(37, 99, 235, 0.35)',
              transition: 'all 0.15s ease',
              flexShrink: 0
            }}
            onMouseEnter={e => {
              e.currentTarget.style.transform = 'translateY(-1px)'
              e.currentTarget.style.boxShadow = '0 6px 18px rgba(37, 99, 235, 0.45)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.transform = 'translateY(0)'
              e.currentTarget.style.boxShadow = '0 4px 14px rgba(37, 99, 235, 0.35)'
            }}
          >
            <span style={{ fontSize: '16px', fontWeight: '700', lineHeight: 1 }}>+</span> Add deadline
          </button>
        </div>
      </div>

      {/* Verification Feedback Banner */}
      {verificationSummary && (
        <div style={{
          background: verificationSummary.error ? 'rgba(239, 68, 68, 0.12)' : 'rgba(56, 189, 248, 0.12)',
          border: `1px solid ${verificationSummary.error ? 'rgba(239, 68, 68, 0.35)' : 'rgba(56, 189, 248, 0.35)'}`,
          color: verificationSummary.error ? '#fca5a5' : '#bae6fd',
          padding: '12px 18px',
          borderRadius: '12px',
          marginBottom: '20px',
          fontSize: '13px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: '12px',
          boxShadow: '0 4px 16px rgba(0,0,0,0.2)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontSize: '16px' }}>{verificationSummary.error ? '⚠️' : '🔍'}</span>
            <div>
              <span style={{ fontWeight: '700' }}>
                {verificationSummary.error
                  ? 'Verification note: '
                  : 'Schedules verified: '
                }
              </span>
              <span>
                {verificationSummary.error
                  ? verificationSummary.error
                  : `${verificationSummary.total} active deadline(s) checked. ${
                      verificationSummary.drift > 0
                        ? `⚠️ ${verificationSummary.drift} update(s) detected via live web search.`
                        : 'All deadlines confirmed matching official dates.'
                    }`
                }
              </span>
            </div>
          </div>
          <button
            onClick={() => setVerificationSummary(null)}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#94a3b8',
              cursor: 'pointer',
              fontSize: '14px',
              padding: '4px',
            }}
          >✕</button>
        </div>
      )}

      {/* Judge Onboarding & Architectural Tour */}
      <OnboardingTour
        onVerifyDeadlines={handleVerifyAll}
        onOpenTelemetry={onOpenTelemetry}
        onOpenCompass={onOpenCompass}
        onOpenSeed={handleSeedJudgePersona}
      />

      {/* Filter pills */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '22px', flexWrap: 'wrap' }}>
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
            return (
              <button
                key={dom}
                id={`filter-pill-${dom}`}
                onClick={() => onSelectDomain(dom)}
                className={`filter-pill ${activeDomain === dom ? 'active' : ''}`}
              >
                {pillMeta.label}
              </button>
            )
          })
        })()}
      </div>

      {/* Task Stream Feed */}
      <div className="timeline-feed">
        {filtered.length === 0 ? (
          <div style={{
            padding: '48px 20px',
            textAlign: 'center',
            background: 'var(--bg-card)',
            borderRadius: '16px',
            border: '1px dashed var(--border)',
            color: 'var(--text-secondary)',
            marginTop: '10px',
            width: '100%',
            boxSizing: 'border-box'
          }}>
            {!localStorage.getItem('compass_demo_seeded') ? (
              <>
                <div style={{ fontSize: '32px', marginBottom: '12px' }}>🧭</div>
                <div style={{ fontSize: '16px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '6px' }}>
                  Setting up your workspace...
                </div>
                <div style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '12px' }}>
                  Loading demo data with cross-domain tasks, code context, and hackathon deadlines.
                </div>
              </>
            ) : (
              <>
                <div style={{ fontSize: '32px', marginBottom: '12px' }}>📭</div>
                <div style={{ fontSize: '16px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '6px' }}>
                  {activeDomain === 'all' ? 'No deadlines yet' : 'Nothing here yet'}
                </div>
                <div style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '18px' }}>
                  {activeDomain === 'all'
                    ? 'Add one when you have something coming up.'
                    : `No deadlines in ${getDomainMeta(activeDomain).label} yet. Add a deadline and it'll show up here.`}
                </div>
                <button
                  id="btn-empty-add-deadline"
                  onClick={() => setShowAddModal(true)}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    background: 'var(--brand)',
                    border: 'none',
                    color: '#2a1a00',
                    padding: '9px 18px',
                    borderRadius: '8px',
                    fontSize: '13px',
                    fontWeight: '700',
                    cursor: 'pointer',
                    boxShadow: '0 4px 12px rgba(245, 166, 35, 0.25)',
                    transition: 'opacity 0.15s ease'
                  }}
                  onMouseEnter={e => e.currentTarget.style.opacity = '0.9'}
                  onMouseLeave={e => e.currentTarget.style.opacity = '1'}
                >
                  + Add deadline
                </button>
              </>
            )}
          </div>
        ) : filtered.map(task => (
          <TaskCard
            key={task.id}
            task={task}
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
