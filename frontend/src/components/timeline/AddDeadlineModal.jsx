import React, { useState, useEffect } from 'react'
import { createTask, updateTask } from '../../api/client'
import { DOMAIN_META } from './domainMeta'

export default function AddDeadlineModal({ isOpen, onClose, onCreated, defaultDomain, tasks = [], customDomains = [], onOpenCompass }) {
  const [title, setTitle] = useState('')
  const [domain, setDomain] = useState('general')
  const [customDomain, setCustomDomain] = useState('')
  const [project, setProject] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [priority, setPriority] = useState('medium')
  const [duration, setDuration] = useState(60)
  const [notes, setNotes] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (isOpen) {
      setTitle('')
      setDomain(defaultDomain && defaultDomain !== 'all' ? defaultDomain : 'general')
      setCustomDomain('')
      setProject('')
      setDueDate('')
      setPriority('medium')
      setDuration(60)
      setNotes('')
      setError(null)
      setLoading(false)
    }
  }, [isOpen, defaultDomain])

  if (!isOpen) return null

  const cleanTitle = title.trim().toLowerCase()
  const cleanDate = dueDate || null

  // Exact duplicate: same title (case-insensitive) AND exact same date (or both unscheduled), not done
  const exactMatch = cleanTitle ? (tasks || []).find(t =>
    (t.title || '').trim().toLowerCase() === cleanTitle &&
    (t.status || 'open') !== 'done' &&
    ((t.due_date || null) === cleanDate)
  ) : null

  // Same name match: same title, but different date or unscheduled, not done
  const sameNameMatch = (!exactMatch && cleanTitle) ? (tasks || []).find(t =>
    (t.title || '').trim().toLowerCase() === cleanTitle &&
    (t.status || 'open') !== 'done'
  ) : null

  const handleAskCompass = (customPrompt) => {
    const trimmedTitle = title.trim()
    const defaultPrompt = trimmedTitle
      ? `Look into my schedules and check if adding deadline "${trimmedTitle}"${dueDate ? ` due ${dueDate}` : ''} conflicts with existing commitments or if schedules need adjusting.`
      : `Look into my schedules and upcoming deadlines, check for any conflicts or overloaded days, and suggest optimizations.`
    const promptToSend = customPrompt || defaultPrompt
    onClose()
    if (onOpenCompass) {
      onOpenCompass(promptToSend)
    }
  }

  const handleShiftDeadline = async () => {
    if (!sameNameMatch) return
    if (!dueDate) {
      setError('Please select a deadline date above to shift this deadline to.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      await updateTask(sameNameMatch.id, {
        due_date: dueDate,
        priority: priority || sameNameMatch.priority,
        notes: notes.trim() ? `${sameNameMatch.description || ''}\n${notes.trim()}`.trim() : sameNameMatch.description
      })
      if (onCreated) onCreated()
      onClose()
    } catch (err) {
      setError(err.message || 'Failed to shift existing deadline.')
      setLoading(false)
    }
  }

  const handleCreateDifferentThing = async () => {
    const trimmedTitle = title.trim()
    if (!trimmedTitle) {
      setError('Please enter a deadline title.')
      return
    }
    let finalDomain = domain
    if (domain === 'other') {
      const cleanCustom = customDomain.trim().toLowerCase().replace(/\s+/g, '-')
      finalDomain = cleanCustom || 'other'
    }
    setLoading(true)
    setError(null)
    try {
      await createTask({
        title: trimmedTitle,
        domain: finalDomain,
        project: project.trim() || 'General',
        due_date: dueDate || null,
        priority,
        duration_minutes: Number(duration) || 60,
        notes: notes.trim() ? `${notes.trim()} (Distinct item)` : '(Distinct item)',
        allow_different_thing: true,
      })
      if (onCreated) onCreated()
      onClose()
    } catch (err) {
      setError(err.message || 'Failed to create separate deadline.')
      setLoading(false)
    }
  }

  const handleSubmit = async (e) => {
    if (e) e.preventDefault()
    const trimmedTitle = title.trim()
    if (!trimmedTitle) {
      setError('Please enter a deadline title.')
      return
    }

    if (exactMatch) {
      setError(`Cannot add duplicate deadline: An identical deadline titled "${exactMatch.title}" scheduled for ${exactMatch.due_date || 'unscheduled'} already exists.`)
      return
    }

    if (sameNameMatch) {
      setError(`A deadline titled "${sameNameMatch.title}" already exists. Please choose whether to shift the deadline or if it is for a completely different thing below.`)
      return
    }

    let finalDomain = domain
    if (domain === 'other') {
      const cleanCustom = customDomain.trim().toLowerCase().replace(/\s+/g, '-')
      finalDomain = cleanCustom || 'other'
    }

    setLoading(true)
    setError(null)
    try {
      await createTask({
        title: trimmedTitle,
        domain: finalDomain,
        project: project.trim() || 'General',
        due_date: dueDate || null,
        priority,
        duration_minutes: Number(duration) || 60,
        notes: notes.trim() || null,
      })
      if (onCreated) onCreated()
      onClose()
    } catch (err) {
      setError(err.message || 'Failed to create deadline. Please try again.')
      setLoading(false)
    }
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(22, 21, 42, 0.45)',
        backdropFilter: 'blur(4px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '20px'
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: 'var(--bg-card)',
          borderRadius: '16px',
          border: '1px solid var(--border)',
          width: '100%',
          maxWidth: '540px',
          maxHeight: '90vh',
          overflowY: 'auto',
          padding: '24px',
          boxShadow: 'var(--shadow-lg)',
          color: 'var(--text-primary)'
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <div>
            <h3 style={{ fontSize: '18px', fontWeight: '800', color: 'var(--text-primary)', margin: 0, letterSpacing: '-0.3px' }}>
              Add a deadline
            </h3>
            <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', margin: '4px 0 0' }}>
              Set a due date or let Compass organize your schedule.
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'var(--bg-card-soft)',
              border: '1px solid var(--border)',
              color: 'var(--text-muted)',
              width: '28px',
              height: '28px',
              borderRadius: '7px',
              cursor: 'pointer',
              fontSize: '14px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}
          >
            ✕
          </button>
        </div>

        {error && (
          <div style={{
            background: 'var(--danger-bg)',
            border: '1px solid #ef4444',
            color: '#b91c1c',
            padding: '10px 14px',
            borderRadius: '8px',
            fontSize: '13px',
            marginBottom: '16px'
          }}>
            ⚠️ {error}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Domain Selection */}
          <div>
            <label style={{ display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-secondary)', fontWeight: '700', marginBottom: '8px' }}>
              Domain / Category
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(78px, 1fr))', gap: '6px' }}>
              {[
                ...Object.entries(DOMAIN_META).map(([domKey, meta]) => ({
                  key: domKey,
                  label: meta.label,
                  icon: meta.icon,
                  color: meta.color,
                })),
                ...customDomains.filter(cd => !DOMAIN_META[cd.key]).map(cd => ({
                  key: cd.key,
                  label: cd.label,
                  icon: cd.icon || '🎯',
                  color: cd.color || '#c084fc',
                }))
              ].map((opt) => {
                const isSelected = domain === opt.key
                return (
                  <button
                    key={opt.key}
                    id={`btn-select-domain-${opt.key}`}
                    type="button"
                    onClick={() => setDomain(opt.key)}
                    style={{
                      padding: '8px 4px',
                      borderRadius: '8px',
                      border: isSelected ? `1.5px solid ${opt.color}` : '1px solid var(--border)',
                      background: isSelected ? 'var(--bg-card-soft)' : 'var(--bg-app)',
                      color: isSelected ? opt.color : 'var(--text-secondary)',
                      fontSize: '11.5px',
                      fontWeight: isSelected ? '700' : '500',
                      cursor: 'pointer',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      gap: '4px',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    <span style={{ fontSize: '15px' }}>{opt.icon}</span>
                    <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '70px' }}>{opt.label}</span>
                  </button>
                )
              })}
            </div>

            {domain === 'other' && (
              <div style={{ marginTop: '10px' }}>
                <label style={{ display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--coursework-text)', fontWeight: '700', marginBottom: '6px' }}>
                  Custom Category Name
                </label>
                <input
                  id="input-custom-domain"
                  type="text"
                  placeholder="e.g. Personal, Research, Fitness, Design (or leave as Other)"
                  value={customDomain}
                  onChange={e => setCustomDomain(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '8px',
                    border: '1px solid var(--border)',
                    background: 'var(--bg-app)',
                    color: 'var(--text-primary)',
                    fontSize: '13px',
                    outline: 'none',
                    boxSizing: 'border-box'
                  }}
                />
              </div>
            )}
          </div>

          {/* Title */}
          <div>
            <label style={{ display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-secondary)', fontWeight: '700', marginBottom: '6px' }}>
              Title <span style={{ color: '#ef4444' }}>*</span>
            </label>
            <input
              id="input-deadline-title"
              type="text"
              required
              placeholder="e.g. Submit CS106B Project or Finish Auth Flow"
              value={title}
              onChange={e => setTitle(e.target.value)}
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: '8px',
                border: '1px solid var(--border)',
                background: 'var(--bg-app)',
                color: 'var(--text-primary)',
                fontSize: '13.5px',
                outline: 'none',
                boxSizing: 'border-box'
              }}
            />
          </div>

          {/* Project & Due Date Row */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-secondary)', fontWeight: '700', marginBottom: '6px' }}>
                Project
              </label>
              <input
                id="input-deadline-project"
                type="text"
                placeholder="e.g. HackMIT, Compass"
                value={project}
                onChange={e => setProject(e.target.value)}
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-app)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  outline: 'none',
                  boxSizing: 'border-box'
                }}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-secondary)', fontWeight: '700', marginBottom: '6px' }}>
                Deadline Date
              </label>
              <input
                id="input-deadline-date"
                type="date"
                value={dueDate}
                onChange={e => setDueDate(e.target.value)}
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-app)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  outline: 'none',
                  boxSizing: 'border-box'
                }}
              />
            </div>
          </div>

          {/* Priority & Duration Row */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-secondary)', fontWeight: '700', marginBottom: '6px' }}>
                Priority
              </label>
              <select
                id="select-deadline-priority"
                value={priority}
                onChange={e => setPriority(e.target.value)}
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-app)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  outline: 'none',
                  boxSizing: 'border-box'
                }}
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="urgent">Urgent ⚠️</option>
              </select>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-secondary)', fontWeight: '700', marginBottom: '6px' }}>
                Duration (minutes)
              </label>
              <input
                id="input-deadline-duration"
                type="number"
                min="15"
                max="720"
                step="15"
                value={duration}
                onChange={e => setDuration(e.target.value)}
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-app)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  outline: 'none',
                  boxSizing: 'border-box'
                }}
              />
            </div>
          </div>

          {/* Notes / Description */}
          <div>
            <label style={{ display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-secondary)', fontWeight: '700', marginBottom: '6px' }}>
              Notes & Details
            </label>
            <textarea
              id="input-deadline-notes"
              rows={3}
              placeholder="Additional requirements, notes, links or objectives..."
              value={notes}
              onChange={e => setNotes(e.target.value)}
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: '8px',
                border: '1px solid var(--border)',
                background: 'var(--bg-app)',
                color: 'var(--text-primary)',
                fontSize: '13px',
                outline: 'none',
                resize: 'vertical',
                boxSizing: 'border-box'
              }}
            />
          </div>

          {/* Exact Duplicate Warning */}
          {exactMatch && (
            <div style={{
              padding: '12px 14px',
              borderRadius: '10px',
              background: 'rgba(239, 68, 68, 0.12)',
              border: '1px solid rgba(239, 68, 68, 0.35)',
              display: 'flex',
              flexDirection: 'column',
              gap: '8px',
              marginTop: '4px'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#f87171', fontWeight: '700', fontSize: '13px' }}>
                <span>🚫</span>
                <span>Exact Duplicate Deadline</span>
              </div>
              <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                A deadline titled <strong>"{exactMatch.title}"</strong> is already scheduled for <strong>{exactMatch.due_date || 'unscheduled'}</strong> ({exactMatch.domain}). You cannot add the exact same deadline multiple times.
              </p>
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '2px' }}>
                <button
                  type="button"
                  id="btn-compass-fix-exact"
                  onClick={() => handleAskCompass(`I have an existing deadline titled "${exactMatch.title}" scheduled for ${exactMatch.due_date || 'unscheduled'}. Can you look into my schedules, check for duplicate commitments or conflicts, and tell me how to resolve this?`)}
                  style={{
                    padding: '7px 13px',
                    borderRadius: '8px',
                    background: 'linear-gradient(135deg, rgba(139, 92, 246, 0.25) 0%, rgba(99, 102, 241, 0.25) 100%)',
                    border: '1px solid rgba(139, 92, 246, 0.5)',
                    color: '#c084fc',
                    fontSize: '12px',
                    fontWeight: '700',
                    cursor: 'pointer',
                    display: 'flex', alignItems: 'center', gap: '6px'
                  }}
                >
                  <span>🧭</span>
                  <span>Ask Compass to Look into Schedules & Fix It</span>
                </button>
              </div>
            </div>
          )}

          {/* Same Name Warning */}
          {sameNameMatch && (
            <div style={{
              padding: '12px 14px',
              borderRadius: '10px',
              background: 'rgba(245, 166, 35, 0.1)',
              border: '1px solid rgba(245, 166, 35, 0.35)',
              display: 'flex',
              flexDirection: 'column',
              gap: '8px',
              marginTop: '4px'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#fbbf24', fontWeight: '700', fontSize: '13px' }}>
                <span>⚠️</span>
                <span>Existing Deadline with Same Name Found</span>
              </div>
              <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                You already have a deadline titled <strong>"{sameNameMatch.title}"</strong> scheduled for <strong>{sameNameMatch.due_date || 'unscheduled'}</strong> ({sameNameMatch.domain}).
                <br />
                Would you like to <strong>shift your existing deadline</strong> to <strong>{dueDate || '(choose date)'}</strong>, or is this for a <strong>completely different thing</strong>?
              </p>
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '4px' }}>
                <button
                  type="button"
                  id="btn-shift-deadline"
                  onClick={handleShiftDeadline}
                  disabled={loading || !dueDate}
                  style={{
                    padding: '7px 13px',
                    borderRadius: '8px',
                    background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
                    color: '#fff',
                    border: 'none',
                    fontSize: '12px',
                    fontWeight: '700',
                    cursor: (!dueDate || loading) ? 'not-allowed' : 'pointer',
                    opacity: !dueDate ? 0.6 : 1,
                    display: 'flex', alignItems: 'center', gap: '6px'
                  }}
                  title={!dueDate ? "Please pick a new deadline date above first" : `Shift existing deadline to ${dueDate}`}
                >
                  <span>📅</span>
                  <span>Shift Existing Deadline {dueDate ? `to ${dueDate}` : '(Pick Date First)'}</span>
                </button>

                <button
                  type="button"
                  id="btn-different-thing"
                  onClick={handleCreateDifferentThing}
                  disabled={loading}
                  style={{
                    padding: '7px 13px',
                    borderRadius: '8px',
                    background: 'var(--bg-card-soft)',
                    border: '1px solid var(--border)',
                    color: 'var(--text-primary)',
                    fontSize: '12px',
                    fontWeight: '600',
                    cursor: loading ? 'not-allowed' : 'pointer',
                    display: 'flex', alignItems: 'center', gap: '6px'
                  }}
                  title="Add as a separate deadline for a completely different item"
                >
                  <span>🔀</span>
                  <span>Completely Different Thing</span>
                </button>

                <button
                  type="button"
                  id="btn-compass-fix-samename"
                  onClick={() => handleAskCompass(`I have an existing deadline titled "${sameNameMatch.title}" scheduled for ${sameNameMatch.due_date || 'unscheduled'}, and I want to add another deadline with the same name for ${dueDate || 'upcoming'}. Can you look into my schedules, check for conflicts, and help me decide whether to shift it or schedule it as a separate deliverable?`)}
                  style={{
                    padding: '7px 13px',
                    borderRadius: '8px',
                    background: 'rgba(139, 92, 246, 0.15)',
                    border: '1px solid rgba(139, 92, 246, 0.4)',
                    color: '#c084fc',
                    fontSize: '12px',
                    fontWeight: '700',
                    cursor: 'pointer',
                    display: 'flex', alignItems: 'center', gap: '6px'
                  }}
                >
                  <span>🧭</span>
                  <span>Ask Compass to Fix It</span>
                </button>
              </div>
            </div>
          )}

          {/* Form Actions */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', marginTop: '12px', flexWrap: 'wrap' }}>
            <button
              type="button"
              id="btn-ask-compass-schedule"
              onClick={() => handleAskCompass()}
              style={{
                padding: '9px 14px',
                borderRadius: '8px',
                background: 'rgba(139, 92, 246, 0.12)',
                border: '1px solid rgba(139, 92, 246, 0.35)',
                color: '#c084fc',
                fontSize: '12.5px',
                fontWeight: '700',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
              title="Ask Compass to analyze schedules and resolve conflicts before adding"
            >
              <span>🧭</span>
              <span>Ask Compass to Look into Schedules</span>
            </button>

            <div style={{ display: 'flex', gap: '10px' }}>
              <button
                type="button"
                onClick={onClose}
                style={{
                  padding: '9px 16px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-card-soft)',
                  color: 'var(--text-secondary)',
                  fontSize: '13px',
                  fontWeight: '500',
                  cursor: 'pointer'
                }}
              >
                Cancel
              </button>
              <button
                id="btn-submit-create-deadline"
                type="submit"
                disabled={loading || Boolean(exactMatch)}
                style={{
                  padding: '9px 20px',
                  borderRadius: '8px',
                  border: 'none',
                  background: exactMatch
                    ? 'var(--bg-card-soft)'
                    : 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
                  color: exactMatch ? 'var(--text-muted)' : '#ffffff',
                  fontSize: '13px',
                  fontWeight: '700',
                  cursor: (loading || exactMatch) ? 'not-allowed' : 'pointer',
                  opacity: loading || exactMatch ? 0.6 : 1,
                  boxShadow: exactMatch ? 'none' : '0 4px 12px rgba(37, 99, 235, 0.4)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px'
                }}
              >
                {loading ? 'Creating…' : exactMatch ? 'Duplicate Blocked' : 'Create deadline'}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}
