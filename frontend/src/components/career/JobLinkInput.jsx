import React, { useState } from 'react'
import { Link2, Loader2 } from 'lucide-react'
import { prepareFromLink } from '../../api/careerApi'
import { looksLikeJobLink, jobLinkErrorMessage } from '../../utils/careerFlowText'

/**
 * "Paste a job link": one field, one button. The server reads the page, finds or creates the listing,
 * tailors the resume, writes the cover letter and sets the apply-by date. Then the application opens.
 */
export default function JobLinkInput({ onPrepared }) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async event => {
    event.preventDefault()
    if (busy || !looksLikeJobLink(value)) return
    setBusy(true)
    setError(null)
    try {
      const app = await prepareFromLink(value.trim())
      setValue('')
      if (onPrepared) onPrepared(app)
    } catch (err) {
      setError(jobLinkErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      onSubmit={submit}
      data-testid="job-link-form"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        flexWrap: 'wrap',
        padding: '12px 16px',
        marginBottom: '16px',
        borderRadius: 'var(--radius-card, 8px)',
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
      }}
    >
      <Link2 size={16} color="var(--text-muted)" aria-hidden="true" />
      <label htmlFor="job-link-input" style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
        Paste a job link
      </label>
      <input
        id="job-link-input"
        type="text"
        inputMode="url"
        autoComplete="off"
        placeholder="https://company.com/careers/software-intern"
        value={value}
        onChange={e => setValue(e.target.value)}
        style={{
          flex: '1 1 260px',
          minWidth: '200px',
          padding: '8px 10px',
          borderRadius: '6px',
          border: '1px solid var(--border)',
          background: 'var(--bg-app)',
          color: 'var(--text-primary)',
          fontSize: '13px',
        }}
      />
      <button
        type="submit"
        disabled={busy || !looksLikeJobLink(value)}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '8px',
          padding: '8px 16px',
          borderRadius: 'var(--radius-btn, 6px)',
          background: 'var(--brand)',
          color: 'var(--accent-text, #1b1a17)',
          border: 'none',
          fontWeight: 600,
          fontSize: '13px',
          opacity: busy || !looksLikeJobLink(value) ? 0.6 : 1,
          cursor: busy || !looksLikeJobLink(value) ? 'not-allowed' : 'pointer',
        }}
      >
        {busy ? <Loader2 size={14} className="spin" aria-hidden="true" /> : null}
        <span>{busy ? 'Reading the job page…' : 'Prepare application'}</span>
      </button>
      {error && (
        <div role="alert" style={{ flexBasis: '100%', fontSize: '12px', color: '#b91c1c' }}>
          {error}
        </div>
      )}
    </form>
  )
}
