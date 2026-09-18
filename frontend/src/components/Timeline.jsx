import React, { useState, useEffect } from 'react'
import { createTask, deleteTask, updateTask } from '../api/client'

const KNOWN_FIELDS = new Set([
  'id', 'domain', 'project', 'timestamp', 'title', 'tags',
  'countdown', 'vector_dim', 'description'
])

const DOMAIN_META = {
  hackathon: { label: 'Hackathon', icon: '🚀', color: '#fbbf24', border: 'rgba(245, 158, 11, 0.4)' },
  coursework: { label: 'Coursework', icon: '📚', color: '#60a5fa', border: 'rgba(59, 130, 246, 0.4)' },
  code: { label: 'Code', icon: '💻', color: '#34d399', border: 'rgba(16, 185, 129, 0.4)' },
  general: { label: 'General', icon: '🌐', color: '#94a3b8', border: 'rgba(100, 116, 139, 0.4)' },
}

function formatFieldLabel(key) {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
}

function formatFieldValue(value) {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

function AddDeadlineModal({ isOpen, onClose, onCreated, defaultDomain }) {
  const [title, setTitle] = useState('')
  const [domain, setDomain] = useState('general')
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

  const handleSubmit = async (e) => {
    e.preventDefault()
    const cleanTitle = title.trim()
    if (!cleanTitle) {
      setError('Please enter a deadline title.')
      return
    }

    setLoading(true)
    setError(null)
    try {
      await createTask({
        title: cleanTitle,
        domain,
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
        background: 'rgba(2, 6, 15, 0.78)',
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
          background: '#0d131f',
          borderRadius: '14px',
          border: '1px solid #1e293b',
          width: '100%',
          maxWidth: '540px',
          maxHeight: '90vh',
          overflowY: 'auto',
          padding: '24px',
          boxShadow: '0 25px 60px rgba(0, 0, 0, 0.65)',
          color: '#f8fafc'
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <div>
            <h3 style={{ fontSize: '18px', fontWeight: '800', color: '#f8fafc', margin: 0, letterSpacing: '-0.3px' }}>
              ➕ Add New Deadline
            </h3>
            <p style={{ fontSize: '12.5px', color: '#94a3b8', margin: '4px 0 0' }}>
              Create a standalone deadline without relying on AI chat
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              background: '#1e293b',
              border: '1px solid #334155',
              color: '#94a3b8',
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
            background: 'rgba(239, 68, 68, 0.12)',
            border: '1px solid rgba(239, 68, 68, 0.35)',
            color: '#fca5a5',
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
            <label style={{ display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#94a3b8', fontWeight: '700', marginBottom: '8px' }}>
              Domain
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }}>
              {Object.entries(DOMAIN_META).map(([domKey, meta]) => {
                const isSelected = domain === domKey
                return (
                  <button
                    key={domKey}
                    type="button"
                    onClick={() => setDomain(domKey)}
                    style={{
                      padding: '8px 6px',
                      borderRadius: '8px',
                      border: isSelected ? `1.5px solid ${meta.color}` : '1px solid #1e293b',
                      background: isSelected ? 'rgba(30, 41, 59, 0.9)' : '#111827',
                      color: isSelected ? meta.color : '#94a3b8',
                      fontSize: '12px',
                      fontWeight: isSelected ? '700' : '500',
                      cursor: 'pointer',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      gap: '4px',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    <span style={{ fontSize: '15px' }}>{meta.icon}</span>
                    <span>{meta.label}</span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Title */}
          <div>
            <label style={{ display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#94a3b8', fontWeight: '700', marginBottom: '6px' }}>
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
                border: '1px solid #334155',
                background: '#111827',
                color: '#f8fafc',
                fontSize: '13.5px',
                outline: 'none',
                boxSizing: 'border-box'
              }}
            />
          </div>

          {/* Project & Due Date Row */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#94a3b8', fontWeight: '700', marginBottom: '6px' }}>
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
                  border: '1px solid #334155',
                  background: '#111827',
                  color: '#f8fafc',
                  fontSize: '13px',
                  outline: 'none',
                  boxSizing: 'border-box'
                }}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#94a3b8', fontWeight: '700', marginBottom: '6px' }}>
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
                  border: '1px solid #334155',
                  background: '#111827',
                  color: '#f8fafc',
                  fontSize: '13px',
                  outline: 'none',
                  boxSizing: 'border-box',
                  colorScheme: 'dark'
                }}
              />
            </div>
          </div>

          {/* Priority & Duration Row */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#94a3b8', fontWeight: '700', marginBottom: '6px' }}>
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
                  border: '1px solid #334155',
                  background: '#111827',
                  color: '#f8fafc',
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
              <label style={{ display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#94a3b8', fontWeight: '700', marginBottom: '6px' }}>
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
                  border: '1px solid #334155',
                  background: '#111827',
                  color: '#f8fafc',
                  fontSize: '13px',
                  outline: 'none',
                  boxSizing: 'border-box'
                }}
              />
            </div>
          </div>

          {/* Notes / Description */}
          <div>
            <label style={{ display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#94a3b8', fontWeight: '700', marginBottom: '6px' }}>
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
                border: '1px solid #334155',
                background: '#111827',
                color: '#f8fafc',
                fontSize: '13px',
                outline: 'none',
                resize: 'vertical',
                boxSizing: 'border-box'
              }}
            />
          </div>

          {/* Form Actions */}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
            <button
              type="button"
              onClick={onClose}
              style={{
                padding: '9px 16px',
                borderRadius: '8px',
                border: '1px solid #334155',
                background: '#1e293b',
                color: '#cbd5e1',
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
              disabled={loading}
              style={{
                padding: '9px 20px',
                borderRadius: '8px',
                border: 'none',
                background: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
                color: '#ffffff',
                fontSize: '13px',
                fontWeight: '700',
                cursor: loading ? 'not-allowed' : 'pointer',
                opacity: loading ? 0.7 : 1,
                boxShadow: '0 4px 12px rgba(37, 99, 235, 0.4)',
                display: 'flex',
                alignItems: 'center',
                gap: '8px'
              }}
            >
              {loading ? 'Creating...' : '+ Create Deadline'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// Shared form input style
const inputStyle = {
  width: '100%',
  padding: '8px 11px',
  borderRadius: '7px',
  border: '1px solid #334155',
  background: '#0d131f',
  color: '#f8fafc',
  fontSize: '13px',
  outline: 'none',
  boxSizing: 'border-box',
  colorScheme: 'dark',
}

function TaskDetailModal({ task, onClose, onDelete, onUpdated }) {
  const [deleting, setDeleting] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)

  // Edit state mirrors all editable fields
  const [editTitle, setEditTitle] = useState('')
  const [editDomain, setEditDomain] = useState('general')
  const [editProject, setEditProject] = useState('')
  const [editDueDate, setEditDueDate] = useState('')
  const [editPriority, setEditPriority] = useState('medium')
  const [editStatus, setEditStatus] = useState('open')
  const [editNotes, setEditNotes] = useState('')

  useEffect(() => {
    if (task) {
      setEditTitle(task.title || '')
      setEditDomain(task.domain || 'general')
      setEditProject(task.project || '')
      // Convert "Xd left (Day)" countdown back to ISO date if we have due_date field
      setEditDueDate(task.due_date || '')
      setEditPriority(task.priority || 'medium')
      setEditStatus(task.status || 'open')
      setEditNotes(task.description || task.notes || '')
    }
    setIsEditing(false)
    setSaveError(null)
  }, [task])

  if (!task) return null

  const isOverdue = (task.countdown || '').toLowerCase().includes('overdue')

  const handleDelete = async () => {
    if (window.confirm(`Delete deadline "${task.title}"? This cannot be undone.`)) {
      setDeleting(true)
      try {
        await onDelete(task.id)
        onClose()
      } catch (err) {
        alert(`Failed to delete deadline: ${err.message}`)
        setDeleting(false)
      }
    }
  }

  const handleSave = async () => {
    const cleanTitle = editTitle.trim()
    if (!cleanTitle) {
      setSaveError('Title cannot be empty.')
      return
    }
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await updateTask(task.id, {
        title: cleanTitle,
        domain: editDomain,
        project: editProject.trim() || 'General',
        due_date: editDueDate || null,
        priority: editPriority,
        status: editStatus,
        notes: editNotes.trim() || null,
      })
      setIsEditing(false)
      if (onUpdated) onUpdated(updated)
    } catch (err) {
      setSaveError(err.message || 'Failed to save changes.')
    } finally {
      setSaving(false)
    }
  }

  const handleCancelEdit = () => {
    // Reset to task values
    setEditTitle(task.title || '')
    setEditDomain(task.domain || 'general')
    setEditProject(task.project || '')
    setEditDueDate(task.due_date || '')
    setEditPriority(task.priority || 'medium')
    setEditStatus(task.status || 'open')
    setEditNotes(task.description || task.notes || '')
    setSaveError(null)
    setIsEditing(false)
  }

  const labelStyle = {
    display: 'block',
    fontSize: '10px',
    textTransform: 'uppercase',
    letterSpacing: '0.07em',
    color: '#64748b',
    fontWeight: '700',
    marginBottom: '5px'
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(2, 6, 15, 0.78)',
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
          background: '#0d1320',
          borderRadius: '14px',
          border: '1px solid #1e293b',
          width: '100%',
          maxWidth: '580px',
          maxHeight: '90vh',
          overflowY: 'auto',
          padding: '24px',
          boxShadow: '0 25px 70px rgba(0,0,0,0.7)',
          color: '#f8fafc'
        }}
      >
        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '18px', gap: '10px' }}>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            <span className={`badge-${task.domain}`} style={{ fontSize: '10.5px', padding: '3px 9px', borderRadius: '20px', textTransform: 'uppercase', fontWeight: '700' }}>
              {task.domain}
            </span>
            <span style={{ fontSize: '12px', color: '#94a3b8', fontWeight: '500' }}>• {task.project}</span>
            <div className={`countdown-badge ${isOverdue ? 'countdown-overdue' : ''}`} style={{ fontSize: '11px' }}>
              {isOverdue && '⚠️ '}{task.countdown}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: '#1e293b', border: '1px solid #334155', color: '#94a3b8',
              width: '28px', height: '28px', borderRadius: '7px', cursor: 'pointer',
              fontSize: '14px', display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0
            }}
          >✕</button>
        </div>

        {/* ── Error Banner ────────────────────────────────────────────────── */}
        {saveError && (
          <div style={{
            background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.35)',
            color: '#fca5a5', padding: '9px 13px', borderRadius: '7px',
            fontSize: '12.5px', marginBottom: '14px'
          }}>
            ⚠️ {saveError}
          </div>
        )}

        {/* ── Title ───────────────────────────────────────────────────────── */}
        <div style={{ marginBottom: '16px' }}>
          <label style={labelStyle}>Title {isEditing && <span style={{ color: '#ef4444' }}>*</span>}</label>
          {isEditing ? (
            <input
              id="edit-task-title"
              type="text"
              value={editTitle}
              onChange={e => setEditTitle(e.target.value)}
              style={inputStyle}
              placeholder="Deadline title..."
            />
          ) : (
            <div style={{ fontSize: '18px', fontWeight: '700', color: '#f8fafc', lineHeight: '1.4' }}>
              {task.title}
            </div>
          )}
        </div>

        {/* ── Description / Notes ─────────────────────────────────────────── */}
        <div style={{ marginBottom: '16px' }}>
          <label style={labelStyle}>Description / Notes</label>
          {isEditing ? (
            <textarea
              id="edit-task-notes"
              rows={4}
              value={editNotes}
              onChange={e => setEditNotes(e.target.value)}
              placeholder="Add context, links, requirements, or objectives..."
              style={{ ...inputStyle, resize: 'vertical', lineHeight: '1.5' }}
            />
          ) : (
            <div style={{
              fontSize: '13.5px', color: editNotes ? '#cbd5e1' : '#475569',
              lineHeight: '1.65', whiteSpace: 'pre-wrap', fontStyle: editNotes ? 'normal' : 'italic',
              background: '#111827', borderRadius: '8px', padding: '10px 12px',
              border: '1px solid #1e293b', minHeight: '48px'
            }}>
              {editNotes || 'No description added. Click "Edit" to add one.'}
            </div>
          )}
        </div>

        {/* ── Domain + Project Row ─────────────────────────────────────────── */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '14px' }}>
          <div>
            <label style={labelStyle}>Domain</label>
            {isEditing ? (
              <select
                id="edit-task-domain"
                value={editDomain}
                onChange={e => setEditDomain(e.target.value)}
                style={inputStyle}
              >
                {Object.entries(DOMAIN_META).map(([k, m]) => (
                  <option key={k} value={k}>{m.icon} {m.label}</option>
                ))}
              </select>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: '#e2e8f0', padding: '8px 0' }}>
                <span>{DOMAIN_META[task.domain]?.icon || '🌐'}</span>
                <span style={{ color: DOMAIN_META[task.domain]?.color }}>{DOMAIN_META[task.domain]?.label || task.domain}</span>
              </div>
            )}
          </div>
          <div>
            <label style={labelStyle}>Project</label>
            {isEditing ? (
              <input
                id="edit-task-project"
                type="text"
                value={editProject}
                onChange={e => setEditProject(e.target.value)}
                style={inputStyle}
                placeholder="e.g. HackMIT, Compass"
              />
            ) : (
              <div style={{ fontSize: '13px', color: '#e2e8f0', padding: '8px 0' }}>{task.project}</div>
            )}
          </div>
        </div>

        {/* ── Due Date + Priority Row ──────────────────────────────────────── */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '14px' }}>
          <div>
            <label style={labelStyle}>Deadline Date</label>
            {isEditing ? (
              <input
                id="edit-task-due-date"
                type="date"
                value={editDueDate}
                onChange={e => setEditDueDate(e.target.value)}
                style={inputStyle}
              />
            ) : (
              <div style={{ fontSize: '13px', color: '#e2e8f0', padding: '8px 0' }}>
                {task.due_date || <span style={{ color: '#475569', fontStyle: 'italic' }}>No date set</span>}
              </div>
            )}
          </div>
          <div>
            <label style={labelStyle}>Priority</label>
            {isEditing ? (
              <select
                id="edit-task-priority"
                value={editPriority}
                onChange={e => setEditPriority(e.target.value)}
                style={inputStyle}
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="urgent">Urgent ⚠️</option>
              </select>
            ) : (
              <div style={{
                display: 'inline-flex', alignItems: 'center', gap: '5px',
                fontSize: '12.5px', padding: '4px 10px', borderRadius: '6px', marginTop: '6px',
                background: task.priority === 'urgent' ? 'rgba(239,68,68,0.18)' :
                  task.priority === 'high' ? 'rgba(251,146,60,0.18)' : 'rgba(100,116,139,0.18)',
                color: task.priority === 'urgent' ? '#f87171' :
                  task.priority === 'high' ? '#fb923c' : '#94a3b8',
                fontWeight: '600'
              }}>
                {task.priority === 'urgent' ? '🔴' : task.priority === 'high' ? '🟠' : task.priority === 'medium' ? '🟡' : '⚪'}
                {task.priority}
              </div>
            )}
          </div>
        </div>

        {/* ── Status ──────────────────────────────────────────────────────── */}
        <div style={{ marginBottom: '18px' }}>
          <label style={labelStyle}>Status</label>
          {isEditing ? (
            <select
              id="edit-task-status"
              value={editStatus}
              onChange={e => setEditStatus(e.target.value)}
              style={{ ...inputStyle, maxWidth: '200px' }}
            >
              <option value="open">Open</option>
              <option value="in_progress">In Progress</option>
              <option value="done">Done ✓</option>
              <option value="overdue">Overdue</option>
            </select>
          ) : (
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: '5px',
              fontSize: '12px', padding: '3px 10px', borderRadius: '6px',
              background: task.status === 'done' ? 'rgba(52,211,153,0.18)' :
                task.status === 'in_progress' ? 'rgba(96,165,250,0.18)' : 'rgba(100,116,139,0.18)',
              color: task.status === 'done' ? '#34d399' :
                task.status === 'in_progress' ? '#60a5fa' : '#94a3b8',
              fontWeight: '600', textTransform: 'capitalize'
            }}>
              {task.status === 'done' ? '✓' : task.status === 'in_progress' ? '⏳' : '○'}
              {task.status?.replace('_', ' ') || 'open'}
            </div>
          )}
        </div>

        {/* ── Meta Row ────────────────────────────────────────────────────── */}
        <div style={{
          display: 'grid', gridTemplateColumns: '110px 1fr', rowGap: '8px', columnGap: '12px',
          fontSize: '12.5px', borderTop: '1px solid #1e293b', paddingTop: '14px', marginBottom: '18px'
        }}>
          <div style={{ color: '#4b5563' }}>Task ID</div>
          <div style={{ color: '#94a3b8', fontFamily: "'JetBrains Mono', monospace", fontSize: '11px' }}>{task.id}</div>

          <div style={{ color: '#4b5563' }}>Logged</div>
          <div style={{ color: '#94a3b8' }}>{task.timestamp}</div>

          {(task.tags || []).length > 0 && (
            <>
              <div style={{ color: '#4b5563' }}>Tags</div>
              <div style={{ display: 'flex', gap: '5px', flexWrap: 'wrap' }}>
                {task.tags.map(tag => (
                  <span key={tag} style={{ fontSize: '10.5px', background: '#1e293b', color: '#94a3b8', padding: '2px 7px', borderRadius: '4px' }}>
                    #{tag}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>

        {/* ── Actions ─────────────────────────────────────────────────────── */}
        <div style={{
          paddingTop: '14px', borderTop: '1px solid #1e293b',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', flexWrap: 'wrap'
        }}>
          {/* Left: Delete */}
          <button
            id="btn-delete-task-modal"
            disabled={deleting || saving}
            onClick={handleDelete}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px',
              padding: '8px 14px', background: 'rgba(239,68,68,0.1)',
              border: '1px solid rgba(239,68,68,0.3)', color: '#f87171',
              borderRadius: '8px', fontSize: '12.5px', fontWeight: '600',
              cursor: (deleting || saving) ? 'not-allowed' : 'pointer',
              opacity: (deleting || saving) ? 0.5 : 1, transition: 'all 0.15s ease'
            }}
          >
            🗑️ {deleting ? 'Deleting…' : 'Delete'}
          </button>

          {/* Right: Edit / Save / Cancel */}
          <div style={{ display: 'flex', gap: '8px' }}>
            {isEditing ? (
              <>
                <button
                  onClick={handleCancelEdit}
                  disabled={saving}
                  style={{
                    padding: '8px 16px', background: '#1e293b',
                    border: '1px solid #334155', color: '#cbd5e1',
                    borderRadius: '8px', fontSize: '12.5px', fontWeight: '500',
                    cursor: saving ? 'not-allowed' : 'pointer', opacity: saving ? 0.6 : 1
                  }}
                >
                  Cancel
                </button>
                <button
                  id="btn-save-task-changes"
                  onClick={handleSave}
                  disabled={saving}
                  style={{
                    padding: '8px 20px',
                    background: saving ? '#1d4ed8' : 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
                    border: 'none', color: '#fff',
                    borderRadius: '8px', fontSize: '12.5px', fontWeight: '700',
                    cursor: saving ? 'not-allowed' : 'pointer', opacity: saving ? 0.7 : 1,
                    boxShadow: '0 4px 12px rgba(37,99,235,0.35)',
                    display: 'flex', alignItems: 'center', gap: '6px'
                  }}
                >
                  {saving ? '⏳ Saving…' : '✓ Save Changes'}
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={onClose}
                  style={{
                    padding: '8px 16px', background: '#1e293b',
                    border: '1px solid #334155', color: '#cbd5e1',
                    borderRadius: '8px', fontSize: '12.5px', fontWeight: '500', cursor: 'pointer'
                  }}
                >
                  Close
                </button>
                <button
                  id="btn-edit-task"
                  onClick={() => setIsEditing(true)}
                  style={{
                    padding: '8px 18px',
                    background: 'linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%)',
                    border: 'none', color: '#fff',
                    borderRadius: '8px', fontSize: '12.5px', fontWeight: '700',
                    cursor: 'pointer',
                    boxShadow: '0 4px 12px rgba(109,40,217,0.35)',
                    display: 'flex', alignItems: 'center', gap: '6px'
                  }}
                >
                  ✏️ Edit
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function Timeline({ tasks, activeDomain, onSelectDomain, onTasksUpdated }) {
  const [selectedTask, setSelectedTask] = useState(null)
  const [showAddModal, setShowAddModal] = useState(false)
  const filtered = activeDomain === 'all' ? tasks : tasks.filter(t => t.domain === activeDomain)
  const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })

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

  return (
    <div className="timeline-container" style={{ background: 'var(--bg-app)' }}>
      {/* Header with Direct Add Deadline Button */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '22px', gap: '16px', flexWrap: 'wrap' }}>
        <div>
          <h2 style={{ fontSize: '24px', fontWeight: '800', color: 'var(--text-primary)', letterSpacing: '-0.4px', margin: 0 }}>
            Timeline Feed <span className="serif-accent" style={{ color: 'var(--text-secondary)', fontWeight: '600' }}>— {today}</span>
          </h2>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginTop: '4px', marginBottom: 0 }}>
            What's happening across your workspace today
          </p>
        </div>

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
          <span style={{ fontSize: '16px', fontWeight: '700', lineHeight: 1 }}>+</span> Add Deadline
        </button>
      </div>

      {/* Filter pills */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '22px', flexWrap: 'wrap' }}>
        {['all', 'hackathon', 'coursework', 'code', 'general'].map(dom => (
          <button
            key={dom}
            onClick={() => onSelectDomain(dom)}
            className={`filter-pill ${activeDomain === dom ? 'active' : ''}`}
          >
            {dom}
          </button>
        ))}
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
            <div style={{ fontSize: '32px', marginBottom: '12px' }}>📭</div>
            <div style={{ fontSize: '16px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '6px' }}>
              No deadlines found
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '18px' }}>
              {activeDomain === 'all'
                ? "Your memory stream is clear. You can add deadlines directly below without needing AI chat."
                : `No active deadlines found under ${activeDomain.toUpperCase()} domain.`}
            </div>
            <button
              id="btn-empty-add-deadline"
              onClick={() => setShowAddModal(true)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                background: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
                border: 'none',
                color: '#ffffff',
                padding: '9px 18px',
                borderRadius: '8px',
                fontSize: '13px',
                fontWeight: '600',
                cursor: 'pointer',
                boxShadow: '0 4px 12px rgba(37, 99, 235, 0.3)'
              }}
            >
              + Add Your First Deadline
            </button>
          </div>
        ) : filtered.map(task => {
          const isOverdue = (task.countdown || '').toLowerCase().includes('overdue')
          const meta = DOMAIN_META[task.domain] || DOMAIN_META.general

          return (
            <div
              key={task.id}
              className={`timeline-card card-${task.domain}`}
              onClick={() => setSelectedTask(task)}
              role="button"
              tabIndex={0}
              onKeyDown={e => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  setSelectedTask(task)
                }
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '14px', marginBottom: '10px', flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div style={{
                    width: '36px',
                    height: '36px',
                    borderRadius: '10px',
                    background: 'var(--bg-card-soft)',
                    border: '1px solid var(--border)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '17px',
                    flexShrink: 0
                  }}>
                    {meta.icon}
                  </div>
                  <div>
                    <div style={{ fontSize: '13.5px', fontWeight: '700', color: 'var(--text-primary)' }}>{task.project}</div>
                    <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>{task.timestamp}</div>
                  </div>
                </div>

                {/* Badge & Quick Delete Action */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span className={`badge-${task.domain}`} style={{ fontSize: '10.5px', padding: '3px 9px', borderRadius: '20px', textTransform: 'uppercase', fontWeight: '700', flexShrink: 0 }}>
                    {meta.label}
                  </span>
                  <button
                    className="btn-delete-deadline"
                    id={`btn-delete-task-${task.id}`}
                    title="Delete deadline"
                    onClick={async (e) => {
                      e.stopPropagation()
                      if (window.confirm(`Delete deadline "${task.title}"?`)) {
                        await handleDelete(task.id)
                      }
                    }}
                    style={{
                      background: 'transparent',
                      border: '1px solid transparent',
                      color: '#64748b',
                      width: '26px',
                      height: '26px',
                      borderRadius: '6px',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '13px',
                      lineHeight: 1,
                      transition: 'all 0.15s ease'
                    }}
                    onMouseEnter={e => {
                      e.currentTarget.style.color = '#ef4444'
                      e.currentTarget.style.background = 'rgba(239, 68, 68, 0.15)'
                      e.currentTarget.style.borderColor = 'rgba(239, 68, 68, 0.3)'
                    }}
                    onMouseLeave={e => {
                      e.currentTarget.style.color = '#64748b'
                      e.currentTarget.style.background = 'transparent'
                      e.currentTarget.style.borderColor = 'transparent'
                    }}
                  >
                    🗑️
                  </button>
                </div>
              </div>

              <div style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)', marginBottom: '12px', lineHeight: '1.4' }}>
                {task.title}
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                  {(task.tags || []).map(tag => (
                    <span key={tag} style={{ fontSize: '10.5px', background: 'var(--bg-card-soft)', color: 'var(--text-secondary)', padding: '2px 8px', borderRadius: '20px', border: '1px solid var(--border)' }}>
                      #{tag}
                    </span>
                  ))}
                </div>
                <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexShrink: 0 }}>
                  <div className={`countdown-badge ${isOverdue ? 'countdown-overdue' : ''}`}>
                    {isOverdue && '⚠️ '}
                    {task.countdown}
                  </div>
                  <div className="vector-tag">
                    {task.vector_dim || 768}-dim
                  </div>
                </div>
              </div>
            </div>
          )
        })}
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
      />
    </div>
  )
}
