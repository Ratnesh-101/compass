import React, { useRef, useState } from 'react'
import { UploadCloud, Loader2, CheckCircle2 } from 'lucide-react'
import { parseResumeFile, commitExtractedResume } from '../../api/careerApi'
import { summarizeResumeImport, missingContactDetails, SAVED_RESUME_MESSAGE } from '../../utils/careerFlowText'
import ExtractionReviewModal from './ExtractionReviewModal'

const card = {
  padding: '20px 22px',
  borderRadius: 'var(--radius-card, 8px)',
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  marginBottom: '16px',
}
const primary = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: '8px',
  padding: '10px 20px',
  borderRadius: 'var(--radius-btn, 6px)',
  background: 'var(--brand)',
  color: 'var(--accent-text, #1b1a17)',
  border: 'none',
  fontWeight: 600,
  fontSize: '14px',
  cursor: 'pointer',
}
const secondary = { ...primary, background: 'var(--bg-app)', color: 'var(--text-primary)', border: '1px solid var(--border)' }
const input = {
  padding: '8px 10px',
  borderRadius: '6px',
  border: '1px solid var(--border)',
  background: 'var(--bg-app)',
  color: 'var(--text-primary)',
  fontSize: '13px',
  minWidth: '200px',
  boxSizing: 'border-box',
}

/**
 * First thing on the Career page when there is no profile yet: "Upload your resume to begin".
 * Choose file -> we read it -> one confirm click saves it as the master resume. The server then fills
 * the profile (degree, year of study, CGPA, graduation year, country, skills, tracks) from the resume.
 */
export default function CareerStartPanel({ onResumeSaved }) {
  const fileRef = useRef(null)
  const [phase, setPhase] = useState('idle') // idle | reading | review | saving | saved
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [showFullReview, setShowFullReview] = useState(false)
  const [savedTarget, setSavedTarget] = useState('master')

  const extracted = result?.extracted_content || null
  const lines = summarizeResumeImport(extracted)
  const missing = missingContactDetails(extracted)

  const handleFile = async event => {
    const file = event.target.files?.[0]
    if (!file) return
    setError(null)
    setPhase('reading')
    try {
      const parsed = await parseResumeFile(file)
      if (!parsed?.success || !parsed.extracted_content) {
        setError(parsed?.error_message || "We couldn't read that file. Try a PDF, Word or text version of your resume.")
        setPhase('idle')
        return
      }
      setResult(parsed)
      setName(parsed.extracted_content.full_name || '')
      setEmail(parsed.extracted_content.email || '')
      setPhase('review')
    } catch (err) {
      setError(err?.message || "We couldn't read that file. Try again.")
      setPhase('idle')
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const commit = async (content, docId, target = 'master') => {
    setPhase('saving')
    setError(null)
    try {
      await commitExtractedResume(content, docId ?? result?.original_document_id ?? null, target)
      setSavedTarget(target)
      setShowFullReview(false)
      setPhase('saved')
      if (onResumeSaved) onResumeSaved()
    } catch (err) {
      setError(err?.message || "We couldn't save your resume. Try again.")
      setPhase('review')
    }
  }

  const handleConfirm = () => {
    if (!extracted) return
    commit({ ...extracted, full_name: name.trim() || extracted.full_name, email: email.trim() || extracted.email })
  }

  if (phase === 'saved') {
    return (
      <div role="status" aria-live="polite" data-testid="career-start-saved" style={{ ...card, display: 'flex', alignItems: 'center', gap: '10px' }}>
        <CheckCircle2 size={20} color="#16a34a" aria-hidden="true" />
        <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>{savedTarget === 'draft' ? 'Saved as a separate draft. Your main resume has not changed.' : SAVED_RESUME_MESSAGE}</span>
      </div>
    )
  }

  return (
    <section aria-labelledby="career-start-title" data-testid="career-start-panel" style={card}>
      <h2 id="career-start-title" style={{ margin: '0 0 4px 0', fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)' }}>
        Upload your resume to begin
      </h2>
      <p style={{ margin: '0 0 14px 0', fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
        Compass reads your name, degree, year, grades and skills from your resume, so you do not type them again. Then it finds internships you can apply to.
      </p>

      <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md" onChange={handleFile} style={{ display: 'none' }} aria-label="Choose your resume file" />

      {error && (
        <div role="alert" style={{ marginBottom: '12px', padding: '10px 12px', borderRadius: '6px', background: '#fef2f2', color: '#991b1b', fontSize: '13px' }}>
          {error}
        </div>
      )}

      {(phase === 'idle' || phase === 'reading') && (
        <button type="button" style={{ ...primary, opacity: phase === 'reading' ? 0.7 : 1 }} disabled={phase === 'reading'} onClick={() => fileRef.current?.click()}>
          {phase === 'reading' ? <Loader2 size={16} className="spin" aria-hidden="true" /> : <UploadCloud size={16} aria-hidden="true" />}
          <span>{phase === 'reading' ? 'Reading your resume…' : 'Choose your resume (PDF, Word or text)'}</span>
        </button>
      )}

      {(phase === 'review' || phase === 'saving') && extracted && (
        <div data-testid="career-start-review">
          <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}>Here is what we read:</div>
          <ul style={{ margin: '0 0 12px 0', paddingLeft: '18px', fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
            {lines.map(line => (
              <li key={line}>{line}</li>
            ))}
          </ul>

          {missing.length > 0 && (
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '12px', alignItems: 'center' }}>
              <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>We could not find {missing.join(' and ')}:</span>
              <input style={input} type="text" aria-label="Your full name" placeholder="Your full name" value={name} onChange={e => setName(e.target.value)} />
              <input style={input} type="email" aria-label="Your email" placeholder="Your email" value={email} onChange={e => setEmail(e.target.value)} />
            </div>
          )}

          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
            <button type="button" style={{ ...primary, opacity: phase === 'saving' ? 0.7 : 1 }} disabled={phase === 'saving'} onClick={handleConfirm}>
              {phase === 'saving' ? <Loader2 size={16} className="spin" aria-hidden="true" /> : null}
              <span>{phase === 'saving' ? 'Saving…' : 'Looks right, save and find internships'}</span>
            </button>
            <button type="button" style={secondary} disabled={phase === 'saving'} onClick={() => setShowFullReview(true)}>
              Check every detail first
            </button>
          </div>
        </div>
      )}

      {showFullReview && result && (
        <ExtractionReviewModal
          show
          onClose={() => setShowFullReview(false)}
          parseResult={result}
          onCommit={(content, docId, target) => commit(content, docId, target || 'master')}
          committing={phase === 'saving'}
        />
      )}
    </section>
  )
}
