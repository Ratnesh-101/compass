import React, { useEffect, useState } from 'react'
import Dialog from '../Dialog'
import { fetchMasterResume, updateMasterResume } from '../../api/careerApi'
import { missingContactDetails, SAVED_DETAILS_MESSAGE } from '../../utils/careerFlowText'

const label = { display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }
const field = {
  width: '100%',
  padding: '9px 12px',
  borderRadius: '8px',
  border: '1px solid var(--border)',
  background: 'var(--bg-app)',
  color: 'var(--text-primary)',
  fontSize: '13px',
  boxSizing: 'border-box',
}

/**
 * Candidate Profile, step 0: name, email, phone, LinkedIn and GitHub. Without them the resume cannot be
 * exported and cover letters cannot be signed. They are saved on the master resume, which every
 * tailored resume copies from.
 *
 * Shown only when the master resume has no name or email (a resume upload fills them in, so most
 * students never see this). Otherwise it renders `children` (the academic profile form) straight away.
 */
export default function CandidateDetailsGate({ onClose, onSaved, children }) {
  const [phase, setPhase] = useState('loading') // loading | details | done
  const [content, setContent] = useState(null)
  const [form, setForm] = useState({ full_name: '', email: '', phone: '', linkedin_url: '', github_or_portfolio: '' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    fetchMasterResume()
      .then(master => {
        if (!alive) return
        const c = master?.content || {}
        setContent(c)
        setForm({
          full_name: c.full_name || '',
          email: c.email || '',
          phone: c.phone || '',
          linkedin_url: c.linkedin_url || '',
          github_or_portfolio: c.github_or_portfolio || '',
        })
        setPhase(missingContactDetails(c).length > 0 ? 'details' : 'done')
      })
      .catch(() => {
        if (alive) setPhase('done') // never block the academic form because contact details failed to load
      })
    return () => {
      alive = false
    }
  }, [])

  const set = key => e => setForm(prev => ({ ...prev, [key]: e.target.value }))

  const save = async e => {
    e.preventDefault()
    if (saving) return
    if (!form.full_name.trim() || !form.email.includes('@')) {
      setError('Please add your full name and a valid email. They go on your resume and cover letter.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      await updateMasterResume({
        ...(content || {}),
        full_name: form.full_name.trim(),
        email: form.email.trim(),
        phone: form.phone.trim() || null,
        linkedin_url: form.linkedin_url.trim() || null,
        github_or_portfolio: form.github_or_portfolio.trim() || null,
      })
      if (onSaved) onSaved(SAVED_DETAILS_MESSAGE)
      setPhase('done')
    } catch (err) {
      setError(err?.message || "We couldn't save your details. Try again.")
    } finally {
      setSaving(false)
    }
  }

  if (phase === 'loading') return null
  if (phase === 'done') return children

  return (
    <Dialog
      onClose={onClose}
      aria-labelledby="candidate-details-title"
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.65)',
        zIndex: 999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px',
      }}
    >
      <form
        onSubmit={save}
        onClick={e => e.stopPropagation()}
        style={{
          width: '100%',
          maxWidth: '520px',
          background: 'var(--bg-card)',
          borderRadius: '16px',
          border: '1px solid var(--border)',
          padding: '24px',
          display: 'flex',
          flexDirection: 'column',
          gap: '14px',
          boxSizing: 'border-box',
        }}
      >
        <div>
          <h2 id="candidate-details-title" style={{ margin: 0, fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>
            Your details
          </h2>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>
            These go on your resume and cover letter. Uploading your resume fills them in for you.
          </div>
        </div>
        {error && (
          <div role="alert" style={{ padding: '10px 12px', borderRadius: '8px', background: '#fef2f2', color: '#991b1b', fontSize: '13px' }}>
            {error}
          </div>
        )}
        <div>
          <label htmlFor="details-name" style={label}>Full name *</label>
          <input id="details-name" style={field} value={form.full_name} onChange={set('full_name')} autoComplete="name" required />
        </div>
        <div>
          <label htmlFor="details-email" style={label}>Email *</label>
          <input id="details-email" type="email" style={field} value={form.email} onChange={set('email')} autoComplete="email" required />
        </div>
        <div>
          <label htmlFor="details-phone" style={label}>Phone</label>
          <input id="details-phone" type="tel" style={field} value={form.phone} onChange={set('phone')} autoComplete="tel" />
        </div>
        <div>
          <label htmlFor="details-linkedin" style={label}>LinkedIn link</label>
          <input id="details-linkedin" type="url" style={field} value={form.linkedin_url} onChange={set('linkedin_url')} placeholder="https://www.linkedin.com/in/…" />
        </div>
        <div>
          <label htmlFor="details-github" style={label}>GitHub or portfolio link</label>
          <input id="details-github" type="url" style={field} value={form.github_or_portfolio} onChange={set('github_or_portfolio')} placeholder="https://github.com/…" />
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
          <button type="button" onClick={() => setPhase('done')} style={{ ...field, width: 'auto', cursor: 'pointer', fontWeight: 600 }}>
            Skip for now
          </button>
          <button
            type="submit"
            disabled={saving}
            style={{ padding: '9px 18px', borderRadius: '8px', background: 'var(--brand)', color: '#ffffff', border: 'none', fontWeight: 600, fontSize: '13px', cursor: saving ? 'not-allowed' : 'pointer', opacity: saving ? 0.7 : 1 }}
          >
            {saving ? 'Saving…' : 'Save and continue'}
          </button>
        </div>
      </form>
    </Dialog>
  )
}
