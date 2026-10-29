import React, { useState, useEffect } from 'react'
import { downloadAuthedFile, openAuthedHtml, API_BASE } from '../../api/baseClient.js'
import { fetchHandoffKit } from '../../api/careerApi.js'
import { copyTextSafely, displayKitValue } from '../../utils/careerUiHelpers.js'
import Dialog from '../Dialog'

const withApiBase = url => (url && url.startsWith('/') ? `${API_BASE}${url}` : url)

export default function HandoffKitDrawer({
  isOpen,
  onClose,
  applicationId,
  opportunity,
  onNavigateToResumeStudio,
  onMarkApplied: _onMarkApplied,
}) {
  const [kit, setKit] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [copiedKey, setCopiedKey] = useState(null)
  const [checklist, setChecklist] = useState({
    resumeAttached: false,
    coverLetterReviewed: false,
    questionsAnswered: false,
  })

  useEffect(() => {
    if (!isOpen || !applicationId) return
    let isMounted = true
    setLoading(true)
    setError(null)

    async function loadKit() {
      try {
        const data = await fetchHandoffKit(applicationId)
        if (isMounted) {
          setKit(data)
          setChecklist(prev => ({
            ...prev,
            resumeAttached: Boolean(data.tailored_resume_id && !data.is_export_blocked),
          }))
        }
      } catch (err) {
        if (isMounted) setError(err.message)
      } finally {
        if (isMounted) setLoading(false)
      }
    }

    loadKit()
    return () => { isMounted = false }
  }, [isOpen, applicationId])

  if (!isOpen) return null

  const copyToClipboard = async (key, text) => {
    if (!text) return
    const ok = await copyTextSafely(text)
    setCopiedKey(ok ? key : `failed:${key}`)
    setTimeout(() => setCopiedKey(null), 2000)
  }

  const handleOpenEmployerPortal = () => {
    if (!kit?.portal_url) return
    // Record external opening in sessionStorage for the focus/visibility prompt
    try {
      window.sessionStorage?.setItem('pending_submission_check', JSON.stringify({
        applicationId: kit.application_id,
        opportunityId: kit.opportunity_id,
        companyName: kit.company_name,
        openedAt: Date.now(),
        status: 'pending_return',
      }))
    } catch {
      // Ignore storage errors
    }
    window.open(kit.portal_url, '_blank', 'noopener,noreferrer')
  }

  return (
    <Dialog onClose={onClose}
      id="handoff-kit-drawer-overlay"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1100,
        background: 'rgba(15, 23, 42, 0.65)',
        backdropFilter: 'blur(4px)',
        display: 'flex',
        justifyContent: 'flex-end',
      }}
    >
      <div
        id="handoff-kit-drawer"
        style={{
          width: '100%',
          maxWidth: '560px',
          height: '100%',
          background: 'var(--bg-card, #ffffff)',
          borderLeft: '1px solid var(--border, #e2e8f0)',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '-8px 0 24px rgba(0, 0, 0, 0.15)',
          overflowY: 'auto',
          animation: 'slideInRight 0.25s ease-out',
        }}
      >
        {/* Drawer Header */}
        <div
          style={{
            padding: '20px 24px',
            borderBottom: '1px solid var(--border, #e2e8f0)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: 'var(--bg-app, #f8fafc)',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '18px' }}>🚀</span>
              <h3 style={{ margin: 0, fontSize: '17px', fontWeight: 800, color: 'var(--text-primary, #0f172a)' }}>
                Application Handoff Kit
              </h3>
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-muted, #64748b)', marginTop: '4px' }}>
              {kit?.company_name || opportunity?.company_name} — {kit?.role_title || opportunity?.role_title}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close Handoff Kit"
            style={{
              background: 'transparent',
              border: 'none',
              fontSize: '20px',
              color: 'var(--text-muted, #64748b)',
              cursor: 'pointer',
              padding: '4px 8px',
            }}
          >
            ✕
          </button>
        </div>

        {/* Drawer Content */}
        <div style={{ padding: '24px', flex: 1, display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {loading && (
            <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted, #64748b)' }}>
              <div>Loading Handoff Kit…</div>
            </div>
          )}

          {error && (
            <div style={{ padding: '12px 16px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '8px', color: '#991b1b', fontSize: '13px' }}>
              ⚠️ {error}
            </div>
          )}

          {kit && !loading && (
            <>
              {/* 1. Tailored Resume Download Section */}
              <div style={{ border: '1px solid var(--border, #e2e8f0)', borderRadius: '12px', padding: '16px', background: 'var(--bg-card, #ffffff)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary, #0f172a)' }}>
                    📄 Tailored Resume
                  </span>
                  <span style={{ fontSize: '11px', fontWeight: 600, padding: '2px 8px', borderRadius: '4px', background: kit.is_export_blocked ? '#fee2e2' : '#dcfce7', color: kit.is_export_blocked ? '#991b1b' : '#166534' }}>
                    {kit.is_export_blocked ? 'Export Blocked' : 'Ready'}
                  </span>
                </div>

                {kit.is_export_blocked ? (
                  <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '8px', padding: '10px 12px', fontSize: '12px', color: '#991b1b', lineHeight: 1.5, marginTop: '8px' }}>
                    ⛔ {kit.block_reason}
                  </div>
                ) : (
                  <div style={{ display: 'flex', gap: '8px', marginTop: '10px', flexWrap: 'wrap' }}>
                    <button
                      type="button"
                      onClick={() => openAuthedHtml(withApiBase(kit.export_html_url))}
                      style={{
                        padding: '6px 14px',
                        borderRadius: '6px',
                        background: 'var(--brand, #3b82f6)',
                        color: '#ffffff',
                        border: 'none',
                        fontSize: '12px',
                        fontWeight: 600,
                        cursor: 'pointer',
                      }}
                    >
                      Print ATS Resume (PDF)
                    </button>
                    <button
                      type="button"
                      onClick={() => downloadAuthedFile(withApiBase(kit.export_docx_url), `${kit.company_name}_Resume.docx`)}
                      style={{
                        padding: '6px 14px',
                        borderRadius: '6px',
                        background: 'transparent',
                        border: '1px solid var(--border, #cbd5e1)',
                        color: 'var(--text-primary, #0f172a)',
                        fontSize: '12px',
                        fontWeight: 600,
                        cursor: 'pointer',
                      }}
                    >
                      Download Word (.docx)
                    </button>
                  </div>
                )}
              </div>

              {/* 2. Cover Letter Section */}
              {kit.cover_letter && (
                <div style={{ border: '1px solid var(--border, #e2e8f0)', borderRadius: '12px', padding: '16px', background: 'var(--bg-card, #ffffff)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary, #0f172a)' }}>
                      ✍️ Truthful Cover Letter
                    </span>
                    <button
                      type="button"
                      onClick={() => copyToClipboard('cover_letter', kit.cover_letter)}
                      style={{
                        padding: '3px 10px',
                        borderRadius: '4px',
                        background: copiedKey === 'cover_letter' ? '#dcfce7' : 'transparent',
                        border: '1px solid var(--border, #cbd5e1)',
                        fontSize: '11px',
                        fontWeight: 600,
                        color: copiedKey === 'cover_letter' ? '#166534' : 'var(--text-primary, #0f172a)',
                        cursor: 'pointer',
                      }}
                    >
                      {copiedKey === 'cover_letter' ? '✓ Copied!' : copiedKey === 'failed:cover_letter' ? 'Copy failed' : 'Copy Letter'}
                    </button>
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted, #475569)', maxHeight: '110px', overflowY: 'auto', background: 'var(--bg-app, #f8fafc)', padding: '10px', borderRadius: '6px', whiteSpace: 'pre-wrap', lineHeight: 1.5, fontFamily: 'monospace' }}>
                    {kit.cover_letter}
                  </div>
                </div>
              )}

              {/* 3. Common Answers (Copy buttons strictly from profile) */}
              <div style={{ border: '1px solid var(--border, #e2e8f0)', borderRadius: '12px', padding: '16px', background: 'var(--bg-card, #ffffff)' }}>
                <div style={{ marginBottom: '12px' }}>
                  <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary, #0f172a)' }}>
                    📋 Common Answers (Profile Verified)
                  </span>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted, #64748b)', marginTop: '2px' }}>
                    Values generated strictly from your master profile. Missing fields are never guessed.
                  </div>
                </div>

                {Array.isArray(kit.missing_fields) && kit.missing_fields.length > 0 && (
                  <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '8px', padding: '8px 10px', marginBottom: '10px', fontSize: '12px', color: '#991b1b' }}>
                    Missing from your profile: {kit.missing_fields.join(', ')}
                  </div>
                )}

                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {[
                    { label: 'Graduation Year', key: 'graduation_year' },
                    { label: 'Degree & Major', key: 'degree' },
                    { label: 'LinkedIn Profile', key: 'linkedin_url' },
                    { label: 'GitHub Profile', key: 'github_url' },
                    { label: 'Portfolio Link', key: 'portfolio_url' },
                    { label: 'Work Authorization', key: 'work_authorization' },
                    { label: 'Notice / Availability', key: 'notice_or_availability' },
                  ].map(item => {
                    const val = kit.common_answers?.[item.key]
                    const isCopied = copiedKey === item.key

                    return (
                      <div key={item.key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', fontSize: '12px' }}>
                        <span style={{ color: 'var(--text-secondary, #475569)', fontWeight: 500, minWidth: '130px' }}>
                          {item.label}:
                        </span>
                        {val ? (
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, justifyContent: 'flex-end' }}>
                            <span style={{ fontWeight: 600, color: 'var(--text-primary, #0f172a)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '240px' }} title={val}>
                              {val}
                            </span>
                            <button
                              type="button"
                              onClick={() => copyToClipboard(item.key, val)}
                              style={{
                                padding: '3px 8px',
                                borderRadius: '4px',
                                background: isCopied ? '#dcfce7' : 'transparent',
                                border: '1px solid var(--border, #cbd5e1)',
                                fontSize: '11px',
                                fontWeight: 600,
                                color: isCopied ? '#166534' : 'var(--text-primary, #0f172a)',
                                cursor: 'pointer',
                              }}
                            >
                              {isCopied ? '✓' : copiedKey === `failed:${item.key}` ? 'Copy failed' : 'Copy'}
                            </button>
                          </div>
                        ) : (
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, justifyContent: 'flex-end' }}>
                            <span style={{ fontStyle: 'italic', color: 'var(--text-muted, #64748b)' }}>{displayKitValue(val)}</span>
                          <button
                            type="button"
                            onClick={() => onNavigateToResumeStudio?.()}
                            style={{
                              padding: '2px 8px',
                              borderRadius: '4px',
                              background: '#fffbeb',
                              border: '1px solid #fde68a',
                              color: '#92400e',
                              fontSize: '11px',
                              fontWeight: 600,
                              cursor: 'pointer',
                            }}
                          >
                            + Add to profile
                          </button>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* 4. Optional Application Email / Draft */}
              {kit.application_email && (
                <div style={{ border: '1px solid var(--border, #e2e8f0)', borderRadius: '12px', padding: '16px', background: 'var(--bg-app, #f8fafc)' }}>
                  <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary, #0f172a)' }}>
                    ✉️ Application Email Detected
                  </span>
                  <p style={{ margin: '4px 0 10px', fontSize: '12px', color: 'var(--text-muted, #64748b)' }}>
                    Send application directly to: <strong>{kit.application_email}</strong>. (Direct Gmail send integration is not configured; using secure mailto client fallback).
                  </p>
                  <a
                    href={`mailto:${kit.application_email}?subject=${encodeURIComponent(`Application: ${kit.role_title} - ${kit.common_answers?.degree || 'Candidate'}`)}&body=${encodeURIComponent(kit.cover_letter || 'Please find attached my resume for the position.')}`}
                    style={{
                      display: 'inline-block',
                      padding: '6px 14px',
                      borderRadius: '6px',
                      background: 'var(--brand, #3b82f6)',
                      color: '#ffffff',
                      textDecoration: 'none',
                      fontSize: '12px',
                      fontWeight: 600,
                    }}
                  >
                    Open Mail Client ↗
                  </a>
                </div>
              )}

              {/* 5. Pre-Submission Checklist */}
              <div style={{ border: '1px solid var(--border, #e2e8f0)', borderRadius: '12px', padding: '16px', background: 'var(--bg-card, #ffffff)' }}>
                <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary, #0f172a)' }}>
                  ✅ Handoff Checklist
                </span>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '10px' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={checklist.resumeAttached}
                      onChange={e => setChecklist(prev => ({ ...prev, resumeAttached: e.target.checked }))}
                    />
                    <span>Tailored ATS resume generated & attached</span>
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={checklist.coverLetterReviewed}
                      onChange={e => setChecklist(prev => ({ ...prev, coverLetterReviewed: e.target.checked }))}
                    />
                    <span>Truthful cover letter reviewed</span>
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={checklist.questionsAnswered}
                      onChange={e => setChecklist(prev => ({ ...prev, questionsAnswered: e.target.checked }))}
                    />
                    <span>Common application questions answered</span>
                  </label>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Drawer Footer Actions */}
        <div
          style={{
            padding: '16px 24px',
            borderTop: '1px solid var(--border, #e2e8f0)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: 'var(--bg-app, #f8fafc)',
            gap: '12px',
            flexWrap: 'wrap',
          }}
        >
          <button
            type="button"
            onClick={onClose}
            style={{
              padding: '8px 16px',
              borderRadius: '6px',
              border: '1px solid var(--border, #cbd5e1)',
              background: 'transparent',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              color: 'var(--text-primary, #0f172a)',
            }}
          >
            Close
          </button>

          <div style={{ display: 'flex', gap: '10px' }}>
            {kit?.portal_url && (
              <button
                type="button"
                onClick={handleOpenEmployerPortal}
                style={{
                  padding: '9px 18px',
                  borderRadius: '6px',
                  background: 'var(--brand, #3b82f6)',
                  color: '#ffffff',
                  border: 'none',
                  fontSize: '13px',
                  fontWeight: 700,
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                }}
              >
                <span>Open Employer Portal</span>
                <span>↗</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </Dialog>
  )
}
