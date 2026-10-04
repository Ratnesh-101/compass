import React, { useState, useEffect } from 'react'
import { updateTask, verifyTaskDeadline } from '../../api/client'
import { DOMAIN_META, getDomainMeta } from './domainMeta'

const inputStyle = {
  width: '100%',
  padding: '8px 11px',
  borderRadius: '8px',
  border: '1px solid var(--border)',
  background: 'var(--bg-app)',
  color: 'var(--text-primary)',
  fontSize: '13px',
  outline: 'none',
  boxSizing: 'border-box',
}

const labelStyle = {
  display: 'block',
  fontSize: '10px',
  textTransform: 'uppercase',
  letterSpacing: '0.07em',
  color: 'var(--text-secondary)',
  fontWeight: '700',
  marginBottom: '5px'
}

export default function TaskDetailModal({ task, onClose, onDelete, onUpdated }) {
  const [deleting, setDeleting] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)

  const [editTitle, setEditTitle] = useState('')
  const [editDomain, setEditDomain] = useState('general')
  const [editProject, setEditProject] = useState('')
  const [editDueDate, setEditDueDate] = useState('')
  const [editPriority, setEditPriority] = useState('medium')
  const [editStatus, setEditStatus] = useState('open')
  const [editNotes, setEditNotes] = useState('')

  const [verifying, setVerifying] = useState(false)
  const [driftResult, setDriftResult] = useState(null)
  const [driftError, setDriftError] = useState(null)

  const handleVerifyWithTavily = async () => {
    setVerifying(true)
    setDriftError(null)
    try {
      const res = await verifyTaskDeadline(task.id)
      setDriftResult(res)
    } catch (err) {
      setDriftError(err.message || 'Verification failed')
    } finally {
      setVerifying(false)
    }
  }

  useEffect(() => {
    if (task) {
      setEditTitle(task.title || '')
      setEditDomain(task.domain || 'general')
      setEditProject(task.project || '')
      setEditDueDate(task.due_date || '')
      setEditPriority(task.priority || 'medium')
      setEditStatus(task.status || 'open')
      setEditNotes(task.description || task.notes || '')
      setDriftResult(null)
      setDriftError(null)
      setVerifying(false)
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
      if (onUpdated) onUpdated(updated)
      setIsEditing(false)
    } catch (err) {
      setSaveError(err.message || 'Failed to save changes.')
    } finally {
      setSaving(false)
    }
  }

  const handleCancelEdit = () => {
    if (task) {
      setEditTitle(task.title || '')
      setEditDomain(task.domain || 'general')
      setEditProject(task.project || '')
      setEditDueDate(task.due_date || '')
      setEditPriority(task.priority || 'medium')
      setEditStatus(task.status || 'open')
      setEditNotes(task.description || task.notes || '')
    }
    setIsEditing(false)
    setSaveError(null)
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
          maxWidth: '580px',
          maxHeight: '90vh',
          overflowY: 'auto',
          padding: '24px',
          boxShadow: 'var(--shadow-lg)',
          color: 'var(--text-primary)'
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '18px', gap: '10px' }}>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            <span className={`badge-${task.domain}`} style={{ fontSize: '10.5px', padding: '3px 9px', borderRadius: '20px', textTransform: 'uppercase', fontWeight: '700' }}>
              {task.domain}
            </span>
            <span style={{ fontSize: '12px', color: 'var(--text-secondary)', fontWeight: '500' }}>• {task.project}</span>
            <div className={`countdown-badge ${isOverdue ? 'countdown-overdue' : ''}`} style={{ fontSize: '11px' }}>
              {isOverdue && '⚠️ '}{task.countdown}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'var(--bg-card-soft)', border: '1px solid var(--border)', color: 'var(--text-muted)',
              width: '28px', height: '28px', borderRadius: '7px', cursor: 'pointer',
              fontSize: '14px', display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0
            }}
          >✕</button>
        </div>

        {saveError && (
          <div style={{
            background: 'var(--danger-bg)', border: '1px solid #ef4444',
            color: '#b91c1c', padding: '9px 13px', borderRadius: '7px',
            fontSize: '12.5px', marginBottom: '14px'
          }}>
            ⚠️ {saveError}
          </div>
        )}

        {/* Title */}
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
            <div style={{ fontSize: '18px', fontWeight: '800', color: 'var(--text-primary)', lineHeight: '1.4' }}>
              {task.title}
            </div>
          )}
        </div>

        {/* Description / Notes */}
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
              fontSize: '13.5px', color: editNotes ? 'var(--text-primary)' : 'var(--text-muted)',
              lineHeight: '1.65', whiteSpace: 'pre-wrap', fontStyle: editNotes ? 'normal' : 'italic',
              background: 'var(--bg-card-soft)', borderRadius: '8px', padding: '10px 12px',
              border: '1px solid var(--border)', minHeight: '48px'
            }}>
              {editNotes || 'No description added. Click "Edit" to add one.'}
            </div>
          )}
        </div>

        {/* Domain + Project Row */}
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
                {!DOMAIN_META[editDomain] && editDomain && (
                  <option value={editDomain}>🏷️ {editDomain.charAt(0).toUpperCase() + editDomain.slice(1)}</option>
                )}
              </select>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: 'var(--text-primary)', padding: '8px 0' }}>
                <span>{getDomainMeta(task.domain).icon}</span>
                <span style={{ color: getDomainMeta(task.domain).color, fontWeight: '600' }}>{getDomainMeta(task.domain).label}</span>
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
              <div style={{ fontSize: '13px', color: 'var(--text-primary)', padding: '8px 0', fontWeight: '500' }}>{task.project}</div>
            )}
          </div>
        </div>

        {/* Due Date + Priority Row */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '14px' }}>
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <label style={labelStyle}>Deadline Date</label>
              {!isEditing && (
                <button
                  id={`btn-verify-task-${task.id}`}
                  onClick={handleVerifyWithTavily}
                  disabled={verifying}
                  style={{
                    background: 'rgba(56, 189, 248, 0.1)',
                    border: '1px solid rgba(56, 189, 248, 0.3)',
                    color: '#38bdf8',
                    padding: '2px 8px',
                    borderRadius: '6px',
                    fontSize: '11px',
                    fontWeight: '700',
                    cursor: verifying ? 'wait' : 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    marginBottom: '4px',
                    transition: 'all 0.15s ease',
                  }}
                  title="Search live official web sources via Tavily to detect schedule postponements or drift"
                >
                  <span>{verifying ? '⏳' : '🔍'}</span>
                  <span>{verifying ? 'Checking Tavily...' : 'Verify with Tavily'}</span>
                </button>
              )}
            </div>
            {isEditing ? (
              <input
                id="edit-task-due-date"
                type="date"
                value={editDueDate}
                onChange={e => setEditDueDate(e.target.value)}
                style={inputStyle}
              />
            ) : (
              <div style={{ fontSize: '13px', color: 'var(--text-primary)', padding: '6px 0' }}>
                {task.due_date || <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>No date set</span>}
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
                background: task.priority === 'urgent' ? 'var(--danger-bg)' :
                  task.priority === 'high' ? 'var(--hackathon-bg)' : 'var(--bg-card-soft)',
                color: task.priority === 'urgent' ? '#ef4444' :
                  task.priority === 'high' ? 'var(--hackathon-text)' : 'var(--text-secondary)',
                fontWeight: '600'
              }}>
                {task.priority === 'urgent' ? '🔴' : task.priority === 'high' ? '🟠' : task.priority === 'medium' ? '🟡' : '⚪'}
                {task.priority}
              </div>
            )}
          </div>
        </div>

        {/* Tavily Schedule Drift Analysis Card */}
        {driftResult && (
          <div style={{
            background: driftResult.data?.drift_analysis?.has_drift
              ? 'rgba(245, 158, 11, 0.12)'
              : driftResult.data?.drift_analysis?.drift_verdict === 'CONFIRMED_ACCURATE'
              ? 'rgba(16, 185, 129, 0.12)'
              : 'rgba(56, 189, 248, 0.08)',
            border: `1px solid ${
              driftResult.data?.drift_analysis?.has_drift
                ? 'rgba(245, 158, 11, 0.4)'
                : driftResult.data?.drift_analysis?.drift_verdict === 'CONFIRMED_ACCURATE'
                ? 'rgba(16, 185, 129, 0.4)'
                : 'rgba(56, 189, 248, 0.3)'
            }`,
            borderRadius: '10px',
            padding: '12px 14px',
            marginBottom: '16px',
            fontSize: '12.5px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: '700', marginBottom: '6px' }}>
              <span>{driftResult.data?.drift_analysis?.has_drift ? '⚠️' : driftResult.data?.drift_analysis?.drift_verdict === 'CONFIRMED_ACCURATE' ? '✅' : 'ℹ️'}</span>
              <span style={{
                color: driftResult.data?.drift_analysis?.has_drift
                  ? '#fbbf24'
                  : driftResult.data?.drift_analysis?.drift_verdict === 'CONFIRMED_ACCURATE'
                  ? '#34d399'
                  : '#38bdf8'
              }}>
                {driftResult.data?.drift_analysis?.has_drift
                  ? `Schedule Drift Detected: Official source indicates deadline is ${driftResult.data.drift_analysis.live_date} (${driftResult.data.drift_analysis.direction} by ${Math.abs(driftResult.data.drift_analysis.drift_days)} days)`
                  : driftResult.data?.drift_analysis?.drift_verdict === 'CONFIRMED_ACCURATE'
                  ? `Confirmed Accurate: Stored deadline matches live official web source`
                  : `Tavily Search: ${driftResult.summary || 'Checked against live web'}`
                }
              </span>
            </div>
            {driftResult.data?.drift_analysis?.evidence && (
              <div style={{ color: '#cbd5e1', fontSize: '11.5px', lineHeight: '1.45', fontStyle: 'italic', marginBottom: '6px' }}>
                "{driftResult.data.drift_analysis.evidence}"
              </div>
            )}
            {driftResult.data?.drift_analysis?.source_url && (
              <div style={{ fontSize: '11px', color: '#94a3b8' }}>
                Official Web Source:{' '}
                <a
                  href={driftResult.data.drift_analysis.source_url}
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: '#60a5fa', textDecoration: 'underline' }}
                >
                  {driftResult.data.drift_analysis.source_url}
                </a>
              </div>
            )}
          </div>
        )}
        {driftError && (
          <div style={{
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            color: '#f87171',
            padding: '8px 12px',
            borderRadius: '8px',
            fontSize: '12px',
            marginBottom: '14px',
          }}>
            ⚠️ Tavily verification check failed: {driftError}
          </div>
        )}

        {/* Status */}
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
              background: task.status === 'done' ? 'var(--code-bg)' :
                task.status === 'in_progress' ? 'var(--coursework-bg)' : 'var(--bg-card-soft)',
              color: task.status === 'done' ? 'var(--code-text)' :
                task.status === 'in_progress' ? 'var(--coursework-text)' : 'var(--text-secondary)',
              fontWeight: '600', textTransform: 'capitalize'
            }}>
              {task.status === 'done' ? '✓' : task.status === 'in_progress' ? '⏳' : '○'}
              {task.status?.replace('_', ' ') || 'open'}
            </div>
          )}
        </div>

        {/* Meta Row */}
        <div style={{
          display: 'grid', gridTemplateColumns: '110px 1fr', rowGap: '8px', columnGap: '12px',
          fontSize: '12.5px', borderTop: '1px solid var(--border)', paddingTop: '14px', marginBottom: '18px'
        }}>
          <div style={{ color: 'var(--text-muted)' }}>Task ID</div>
          <div style={{ color: 'var(--text-secondary)', fontFamily: "'JetBrains Mono', monospace", fontSize: '11px' }}>{task.id}</div>

          <div style={{ color: 'var(--text-muted)' }}>Logged</div>
          <div style={{ color: 'var(--text-secondary)' }}>{task.timestamp}</div>

          {(task.tags || []).length > 0 && (
            <>
              <div style={{ color: 'var(--text-muted)' }}>Tags</div>
              <div style={{ display: 'flex', gap: '5px', flexWrap: 'wrap' }}>
                {task.tags.map(tag => (
                  <span key={tag} style={{ fontSize: '10.5px', background: 'var(--bg-card-soft)', color: 'var(--text-secondary)', padding: '2px 7px', borderRadius: '4px', border: '1px solid var(--border)' }}>
                    #{tag}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Actions */}
        <div style={{
          paddingTop: '14px', borderTop: '1px solid var(--border)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', flexWrap: 'wrap'
        }}>
          <button
            id="btn-delete-task-modal"
            disabled={deleting || saving}
            onClick={handleDelete}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px',
              padding: '8px 14px', background: 'var(--danger-bg)',
              border: '1px solid rgba(239,68,68,0.3)', color: '#dc2626',
              borderRadius: '8px', fontSize: '12.5px', fontWeight: '600',
              cursor: (deleting || saving) ? 'not-allowed' : 'pointer',
              opacity: (deleting || saving) ? 0.5 : 1, transition: 'all 0.15s ease'
            }}
          >
            🗑️ {deleting ? 'Deleting…' : 'Delete'}
          </button>

          <div style={{ display: 'flex', gap: '8px' }}>
            {isEditing ? (
              <>
                <button
                  onClick={handleCancelEdit}
                  disabled={saving}
                  style={{
                    padding: '8px 16px', background: 'var(--bg-card-soft)',
                    border: '1px solid var(--border)', color: 'var(--text-secondary)',
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
                    padding: '8px 16px', background: 'var(--bg-card-soft)',
                    border: '1px solid var(--border)', color: 'var(--text-secondary)',
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
