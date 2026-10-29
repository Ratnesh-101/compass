import React, { useState } from 'react'
import { ExternalLink, CheckCircle2, XCircle, AlertCircle, Info, RefreshCw } from 'lucide-react'
import { cleanOpportunity, cleanText, cleanSource } from '../../utils/jobCardCleaner'
import Dialog from '../Dialog'

const PIPELINE_STATUSES = [
  { id: 'interested', label: 'Interested' },
  { id: 'preparing', label: 'Preparing Application' },
  { id: 'ready_to_apply', label: 'Ready to Apply' },
  { id: 'applied', label: 'Applied' },
  { id: 'assessment_pending', label: 'Assessment Pending' },
  { id: 'interviewing', label: 'Interviewing' },
  { id: 'offer_received', label: 'Offer Received' },
  { id: 'rejected', label: 'Rejected' },
  { id: 'withdrawn', label: 'Withdrawn' },
  { id: 'closed_without_applying', label: 'Closed Without Applying' },
]

function isCleanString(val) {
  if (!val) return false
  const s = String(val).trim().toLowerCase()
  return s !== '' && s !== 'nan' && s !== 'null' && s !== 'undefined' && s !== 'none' && s !== 'n/a'
}

export default function RadarDetailModal({
  opportunity,
  onClose,
  onUpdateApp,
  onVerify,
  isVerifying,
  onNavigateToResumeStudio,
}) {
  const [activeTab, setActiveTab] = useState('overview') // 'overview' | 'eligibility' | 'history' | 'tracking'
  const [appStatus, setAppStatus] = useState(opportunity?.application_status || 'interested')
  const [personalDeadline, setPersonalDeadline] = useState(opportunity?.personal_deadline || '')
  const [privateNotes, setPrivateNotes] = useState(opportunity?.private_notes || '')
  const [isSavingApp, setIsSavingApp] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)

  if (!opportunity) return null

  const handleSaveTracking = async e => {
    e.preventDefault()
    setIsSavingApp(true)
    setSaveSuccess(false)
    try {
      await onUpdateApp(opportunity.id, {
        application_status: appStatus,
        personal_deadline: personalDeadline || null,
        private_notes: privateNotes || null,
      })
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 3000)
    } finally {
      setIsSavingApp(false)
    }
  }

  const {
    work_arrangement,
    official_application_url,
    canonical_url,
    description,
    duration,
    eligibility_classification,
    eligibility_explanation,
    eligibility_reasons = [],
    cycles = [],
    prediction,
    sources = [],
    last_verified_at,
    posted_at,
    confirmed_open_date,
    employer_type,
    verification_evidence,
    source_identifier,
    requirements,
  } = opportunity

  // Data cleansing via unified helper
  const cleaned = cleanOpportunity(opportunity)
  const cleanCompany = cleaned.company
  const cleanRole = cleaned.role
  const cleanLocation = cleaned.locationLine
  const cleanCompensation = cleaned.salary
  const cleanDuration = cleanText(duration)
  const cleanDescription = cleanText(description)

  // Format distinct dates
  const rawPostingDate = posted_at || confirmed_open_date
  const formattedPosted = rawPostingDate
    ? new Date(rawPostingDate).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
    : null

  const formattedVerified = last_verified_at
    ? `${new Date(last_verified_at).toLocaleDateString()} ${new Date(last_verified_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
    : null

  // Validate external application URL
  const originalUrl = official_application_url || canonical_url
  const hasValidExternalUrl = Boolean(
    originalUrl &&
    typeof originalUrl === 'string' &&
    /^https?:\/\//i.test(originalUrl.trim()) &&
    !originalUrl.toLowerCase().includes('javascript:')
  )

  const getStatusLabel = () => cleaned.verificationBadge.label

  return (
    <Dialog onClose={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(20, 22, 29, 0.65)',
        zIndex: 999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px',
        backdropFilter: 'blur(3px)',
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '740px',
          maxHeight: '90vh',
          background: 'var(--bg-card, #ffffff)',
          borderRadius: 'var(--radius-modal, 8px)',
          border: '1px solid var(--border, #e6e1d6)',
          boxShadow: 'var(--shadow-lg)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          boxSizing: 'border-box',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div
          style={{
            padding: '18px 24px',
            borderBottom: '1px solid var(--border, #e6e1d6)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: '16px',
            background: 'var(--bg-card, #ffffff)',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--brand-dark, #b47507)', textTransform: 'uppercase' }}>
                {cleanCompany}
              </span>
              {employer_type && isCleanString(employer_type) && (
                <span
                  style={{
                    fontSize: '11px',
                    fontWeight: 600,
                    padding: '1px 6px',
                    borderRadius: '4px',
                    color: 'var(--text-secondary, #3d3a35)',
                    backgroundColor: 'var(--bg-card-soft, #f2eee6)',
                    border: '1px solid var(--border, #e6e1d6)',
                    textTransform: 'capitalize',
                  }}
                >
                  {employer_type.replace(/_/g, ' ')}
                </span>
              )}
              <span style={{ fontSize: '12px', color: 'var(--text-muted, #5f5a52)' }}>•</span>
              <span style={{ fontSize: '12px', color: 'var(--text-secondary, #3d3a35)' }}>
                Status: <strong>{getStatusLabel()}</strong>
              </span>
            </div>
            <h2 style={{ fontSize: '19px', fontWeight: 700, color: 'var(--text-primary, #1b1a17)', margin: 0, lineHeight: 1.3 }}>
              {cleanRole}
            </h2>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close details"
            style={{
              background: 'transparent',
              border: 'none',
              fontSize: '22px',
              color: 'var(--text-muted, #5f5a52)',
              cursor: 'pointer',
              padding: '4px 8px',
              lineHeight: 1,
            }}
          >
            ✕
          </button>
        </div>

        {/* Modal Sub-tabs */}
        <div
          role="tablist"
          aria-label="Opportunity details sections"
          className="unified-tablist"
          style={{
            borderBottom: '1px solid var(--border)',
            background: 'var(--bg-app)',
            padding: '0 24px',
          }}
        >
          {[
            { id: 'overview', label: 'Overview & Details' },
            { id: 'eligibility', label: 'Eligibility Audit' },
            { id: 'history', label: `Recruitment Cycles (${cycles.length})` },
            { id: 'tracking', label: 'Application Tracker' },
          ].map(tab => {
            const isActive = activeTab === tab.id
            return (
              <button
                key={tab.id}
                role="tab"
                id={`radar-detail-tab-${tab.id}`}
                aria-selected={isActive}
                tabIndex={isActive ? 0 : -1}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`unified-tab ${isActive ? 'active' : ''}`}
              >
                <span>{tab.label}</span>
              </button>
            )
          })}
        </div>

        {/* Modal Scroll Area */}
        <div style={{ padding: '22px 24px', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '18px' }}>
          {/* TAB 1: OVERVIEW */}
          {activeTab === 'overview' && (
            <>
              {/* Metadata Highlights */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '10px' }}>
                <div style={{ padding: '10px 12px', borderRadius: '6px', background: 'var(--bg-app, #f7f5ef)', border: '1px solid var(--border, #e6e1d6)' }}>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted, #5f5a52)', textTransform: 'uppercase', fontWeight: 600 }}>Location</div>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary, #1b1a17)', marginTop: '2px' }}>
                    {cleanLocation || 'Flexible'}
                  </div>
                </div>

                <div style={{ padding: '10px 12px', borderRadius: '6px', background: 'var(--bg-app, #f7f5ef)', border: '1px solid var(--border, #e6e1d6)' }}>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted, #5f5a52)', textTransform: 'uppercase', fontWeight: 600 }}>Arrangement</div>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary, #1b1a17)', marginTop: '2px', textTransform: 'capitalize' }}>
                    {work_arrangement || 'Unspecified'}
                  </div>
                </div>

                {cleanCompensation && (
                  <div style={{ padding: '10px 12px', borderRadius: '6px', background: 'var(--bg-app, #f7f5ef)', border: '1px solid var(--border, #e6e1d6)' }}>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted, #5f5a52)', textTransform: 'uppercase', fontWeight: 600 }}>Compensation</div>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--domain-code, #1c8a62)', marginTop: '2px' }}>
                      {cleanCompensation}
                    </div>
                  </div>
                )}

                {cleanDuration && (
                  <div style={{ padding: '10px 12px', borderRadius: '6px', background: 'var(--bg-app, #f7f5ef)', border: '1px solid var(--border, #e6e1d6)' }}>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted, #5f5a52)', textTransform: 'uppercase', fontWeight: 600 }}>Duration</div>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary, #1b1a17)', marginTop: '2px' }}>
                      {cleanDuration}
                    </div>
                  </div>
                )}
              </div>

              {/* Verified Dates & Provenance */}
              <div
                style={{
                  padding: '12px 14px',
                  borderRadius: '6px',
                  background: 'var(--bg-card-soft, #f2eee6)',
                  border: '1px solid var(--border, #e6e1d6)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  flexWrap: 'wrap',
                  gap: '8px',
                  fontSize: '12px',
                  color: 'var(--text-secondary, #3d3a35)',
                }}
              >
                <div>
                  <strong>Posted:</strong> {formattedPosted || 'Date unrecorded by source'}
                </div>
                <div>
                  <strong>Last Verified:</strong> {formattedVerified || 'Pending verification'}
                </div>
                {source_identifier && (
                  <div>
                    <strong>Requisition ID:</strong> <code>{source_identifier}</code>
                  </div>
                )}
              </div>

              {/* Requirements & Restrictions if available */}
              {requirements && (
                <div>
                  <h4 style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary, #1b1a17)', marginBottom: '8px' }}>
                    Published Requirements & Qualifications
                  </h4>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '8px', fontSize: '12px' }}>
                    {requirements.eligible_graduation_years && requirements.eligible_graduation_years.length > 0 && (
                      <div style={{ padding: '8px 10px', background: 'var(--bg-app, #f7f5ef)', borderRadius: '4px', border: '1px solid var(--border-soft, #eee9de)' }}>
                        <strong>Target Graduation Cohort:</strong> {requirements.eligible_graduation_years.join(', ')}
                      </div>
                    )}
                    {requirements.eligible_academic_years && requirements.eligible_academic_years.length > 0 && (
                      <div style={{ padding: '8px 10px', background: 'var(--bg-app, #f7f5ef)', borderRadius: '4px', border: '1px solid var(--border-soft, #eee9de)' }}>
                        <strong>Accepted Academic Year(s):</strong> {requirements.eligible_academic_years.join(', ')}
                      </div>
                    )}
                    {requirements.eligible_degree_types && requirements.eligible_degree_types.length > 0 && (
                      <div style={{ padding: '8px 10px', background: 'var(--bg-app, #f7f5ef)', borderRadius: '4px', border: '1px solid var(--border-soft, #eee9de)' }}>
                        <strong>Accepted Degree(s):</strong> {requirements.eligible_degree_types.join(', ')}
                      </div>
                    )}
                    {requirements.min_gpa !== null && requirements.min_gpa !== undefined && (
                      <div style={{ padding: '8px 10px', background: 'var(--bg-app, #f7f5ef)', borderRadius: '4px', border: '1px solid var(--border-soft, #eee9de)' }}>
                        <strong>Minimum CGPA:</strong> {requirements.min_gpa} / {requirements.gpa_scale || 10.0}
                      </div>
                    )}
                    {requirements.no_active_backlogs === true && (
                      <div style={{ padding: '8px 10px', background: 'var(--bg-app, #f7f5ef)', borderRadius: '4px', border: '1px solid var(--border-soft, #eee9de)' }}>
                        <strong>Backlogs:</strong> 0 Active Backlogs required
                      </div>
                    )}
                    {requirements.required_skills && requirements.required_skills.length > 0 && (
                      <div style={{ padding: '8px 10px', background: 'var(--bg-app, #f7f5ef)', borderRadius: '4px', border: '1px solid var(--border-soft, #eee9de)' }}>
                        <strong>Mandatory Skills:</strong> {requirements.required_skills.join(', ')}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Source-backed Job Description */}
              <div>
                <h4 style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary, #1b1a17)', marginBottom: '8px' }}>
                  Role Overview
                </h4>
                {cleanDescription ? (
                  <div style={{ fontSize: '13px', color: 'var(--text-secondary, #3d3a35)', lineHeight: 1.6, whiteSpace: 'pre-line' }}>
                    {cleanDescription}
                  </div>
                ) : (
                  <div style={{ fontSize: '13px', color: 'var(--text-muted, #5f5a52)', fontStyle: 'italic' }}>
                    No extended description was published for this listing. Please review the official employer posting.
                  </div>
                )}
              </div>

              {/* Provenance & Verified Sources */}
              {sources.length > 0 && (
                <div>
                  <h4 style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary, #1b1a17)', marginBottom: '8px' }}>
                    Audit & Provenance Sources
                  </h4>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {sources.map((src, i) => (
                      <div
                        key={i}
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          padding: '8px 12px',
                          borderRadius: '6px',
                          border: '1px solid var(--border, #e6e1d6)',
                          background: 'var(--bg-app, #f7f5ef)',
                          fontSize: '12px',
                        }}
                      >
                        <div>
                          <strong>{cleanSource(src.source_name) || src.source_name}</strong> ({src.source_type})
                          {src.source_url && (
                            <div style={{ color: 'var(--text-muted, #5f5a52)', fontSize: '11px' }}>
                              {src.source_url}
                            </div>
                          )}
                        </div>
                        <span style={{ padding: '2px 6px', borderRadius: '4px', background: 'var(--bg-card, #ffffff)', border: '1px solid var(--border-soft, #eee9de)', fontSize: '11px' }}>
                          {src.source_authority}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Verification Evidence */}
              {verification_evidence && (
                <div style={{ padding: '10px 12px', borderRadius: '6px', background: 'var(--bg-app, #f7f5ef)', border: '1px solid var(--border, #e6e1d6)', fontSize: '12px', color: 'var(--text-secondary, #3d3a35)' }}>
                  <strong>Verification Basis: </strong>
                  <span>{verification_evidence}</span>
                </div>
              )}
            </>
          )}

          {/* TAB 2: ELIGIBILITY AUDIT */}
          {activeTab === 'eligibility' && (
            <div>
              {/* Classification Summary Card */}
              <div
                style={{
                  padding: '14px 16px',
                  borderRadius: '6px',
                  marginBottom: '16px',
                  background: 'var(--bg-card-soft, #f2eee6)',
                  border: '1px solid var(--border, #e6e1d6)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                  <div style={{ fontWeight: 700, fontSize: '14px', color: 'var(--text-primary, #1b1a17)' }}>
                    {eligibility_classification === 'ELIGIBLE' && 'Confirmed Match'}
                    {(eligibility_classification === 'POTENTIAL_MATCH' || eligibility_classification === 'POTENTIALLY_ELIGIBLE') && 'Possible Match'}
                    {eligibility_classification === 'INELIGIBLE' && 'Likely Ineligible'}
                    {eligibility_classification === 'INSUFFICIENT_INFORMATION' && 'Eligibility Unconfirmed'}
                  </div>
                </div>
                <div style={{ fontSize: '13px', color: 'var(--text-secondary, #3d3a35)', lineHeight: 1.5 }}>
                  {eligibility_explanation || 'Position requirements evaluated against verified candidate profile.'}
                </div>
              </div>

              {/* Requirement-by-Requirement Evidence Breakdown */}
              <div style={{ marginBottom: '10px', fontSize: '13px', fontWeight: 600, color: 'var(--text-primary, #1b1a17)' }}>
                Requirement Evidence Breakdown:
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {eligibility_reasons.length === 0 ? (
                  <div style={{ fontSize: '13px', color: 'var(--text-muted, #5f5a52)', padding: '12px', background: 'var(--bg-app, #f7f5ef)', borderRadius: '6px' }}>
                    No explicit eligibility constraints found on this listing or candidate profile is incomplete.
                  </div>
                ) : (
                  eligibility_reasons.map((r, i) => {
                    const isPass = r.status === 'pass'
                    const isFail = r.status === 'fail'
                    const isUnknown = r.status === 'unknown'
                    return (
                      <div
                        key={i}
                        style={{
                          display: 'flex',
                          gap: '10px',
                          padding: '10px 12px',
                          borderRadius: '6px',
                          background: 'var(--bg-app, #f7f5ef)',
                          border: '1px solid var(--border, #e6e1d6)',
                          alignItems: 'flex-start',
                        }}
                      >
                        <div style={{ marginTop: '2px' }}>
                          {isPass && <CheckCircle2 size={16} color="var(--domain-code, #1c8a62)" />}
                          {isFail && <XCircle size={16} color="var(--danger-text, #b91c1c)" />}
                          {isUnknown && <AlertCircle size={16} color="var(--brand-dark, #b47507)" />}
                          {!isPass && !isFail && !isUnknown && <Info size={16} color="var(--text-muted, #5f5a52)" />}
                        </div>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontWeight: 600, fontSize: '12px', textTransform: 'capitalize', color: 'var(--text-primary, #1b1a17)' }}>
                            {r.field ? r.field.replace(/_/g, ' ') : 'Requirement'}
                            <span style={{ marginLeft: '8px', fontSize: '11px', fontWeight: 500, color: 'var(--text-muted, #5f5a52)' }}>
                              ({isPass ? 'Satisfied' : isFail ? 'Mandatory Mismatch' : isUnknown ? 'Missing Evidence' : 'Informational'})
                            </span>
                          </div>
                          <div style={{ fontSize: '12px', color: 'var(--text-secondary, #3d3a35)', marginTop: '2px', lineHeight: 1.4 }}>
                            {r.detail}
                          </div>
                        </div>
                      </div>
                    )
                  })
                )}
              </div>

              {/* Navigation prompt to Resume Studio if candidate profile needs attention */}
              {onNavigateToResumeStudio && (
                <div
                  style={{
                    marginTop: '16px',
                    padding: '12px',
                    background: 'var(--bg-card-soft, #f2eee6)',
                    borderRadius: '6px',
                    border: '1px solid var(--border, #e6e1d6)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: '10px',
                  }}
                >
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary, #3d3a35)' }}>
                    Need to update your degree, skills, or graduation cohort? Manage your profile in Resume Studio.
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      onClose()
                      onNavigateToResumeStudio()
                    }}
                    style={{
                      padding: '6px 12px',
                      borderRadius: 'var(--radius-btn, 6px)',
                      background: 'var(--brand, #f5a623)',
                      color: 'var(--accent-text, #1b1a17)',
                      border: 'none',
                      fontSize: '12px',
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    Go to Resume Studio
                  </button>
                </div>
              )}
            </div>
          )}

          {/* TAB 3: RECRUITMENT CYCLES */}
          {activeTab === 'history' && (
            <div>
              {prediction && prediction.estimated_open_window && (
                <div
                  style={{
                    padding: '14px',
                    borderRadius: '6px',
                    background: 'var(--bg-card-soft, #f2eee6)',
                    border: '1px solid var(--border, #e6e1d6)',
                    marginBottom: '16px',
                  }}
                >
                  <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--domain-coursework, #2f64c8)', textTransform: 'uppercase' }}>
                    Historical Recruitment Window Forecast
                  </div>
                  <div style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary, #1b1a17)', margin: '4px 0' }}>
                    {prediction.estimated_open_window} ({prediction.confidence} Confidence)
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary, #3d3a35)' }}>
                    {prediction.evidence_basis}
                  </div>
                </div>
              )}

              <h4 style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary, #1b1a17)', marginBottom: '8px' }}>
                Observed Recruitment Cycles
              </h4>
              {cycles.length === 0 ? (
                <div style={{ fontSize: '13px', color: 'var(--text-muted, #5f5a52)', padding: '12px', background: 'var(--bg-app, #f7f5ef)', borderRadius: '6px' }}>
                  No historical cycle records verified yet for this company. Compass will record observations as cycles open.
                </div>
              ) : (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--border, #e6e1d6)', color: 'var(--text-secondary, #3d3a35)' }}>
                        <th style={{ padding: '8px' }}>Cycle Year</th>
                        <th style={{ padding: '8px' }}>Observed Open</th>
                        <th style={{ padding: '8px' }}>Observed Close</th>
                        <th style={{ padding: '8px' }}>Type</th>
                        <th style={{ padding: '8px' }}>Notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cycles.map((c, idx) => (
                        <tr key={idx} style={{ borderBottom: '1px solid var(--border-soft, #eee9de)' }}>
                          <td style={{ padding: '8px', fontWeight: 600 }}>{c.cycle_year}</td>
                          <td style={{ padding: '8px' }}>{c.observed_open_date || 'N/A'}</td>
                          <td style={{ padding: '8px' }}>{c.observed_close_date || 'N/A'}</td>
                          <td style={{ padding: '8px', textTransform: 'capitalize' }}>{c.observation_type}</td>
                          <td style={{ padding: '8px', color: 'var(--text-muted, #5f5a52)' }}>{c.notes || 'Verified'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* TAB 4: APPLICATION TRACKER */}
          {activeTab === 'tracking' && (
            <form onSubmit={handleSaveTracking} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary, #1b1a17)', marginBottom: '4px' }}>
                  Application Pipeline Status
                </label>
                <select
                  value={appStatus}
                  onChange={e => setAppStatus(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    borderRadius: 'var(--radius-input, 6px)',
                    border: '1px solid var(--border, #e6e1d6)',
                    background: 'var(--bg-app, #f7f5ef)',
                    color: 'var(--text-primary, #1b1a17)',
                    fontSize: '13px',
                  }}
                >
                  {PIPELINE_STATUSES.map(s => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary, #1b1a17)', marginBottom: '4px' }}>
                  Personal Target Deadline
                </label>
                <input
                  type="date"
                  value={personalDeadline}
                  onChange={e => setPersonalDeadline(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    borderRadius: 'var(--radius-input, 6px)',
                    border: '1px solid var(--border, #e6e1d6)',
                    background: 'var(--bg-app, #f7f5ef)',
                    color: 'var(--text-primary, #1b1a17)',
                    fontSize: '13px',
                    boxSizing: 'border-box',
                  }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary, #1b1a17)', marginBottom: '4px' }}>
                  Private Notes & Preparation Topics
                </label>
                <textarea
                  rows={4}
                  value={privateNotes}
                  onChange={e => setPrivateNotes(e.target.value)}
                  placeholder="Record interview notes, referral contacts, or requirements for this role…"
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    borderRadius: 'var(--radius-input, 6px)',
                    border: '1px solid var(--border, #e6e1d6)',
                    background: 'var(--bg-app, #f7f5ef)',
                    color: 'var(--text-primary, #1b1a17)',
                    fontSize: '13px',
                    resize: 'vertical',
                    boxSizing: 'border-box',
                  }}
                />
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <button
                  type="submit"
                  disabled={isSavingApp}
                  style={{
                    padding: '8px 16px',
                    borderRadius: 'var(--radius-btn, 6px)',
                    background: 'var(--brand, #f5a623)',
                    color: 'var(--accent-text, #1b1a17)',
                    border: 'none',
                    fontWeight: 600,
                    fontSize: '13px',
                    cursor: isSavingApp ? 'not-allowed' : 'pointer',
                  }}
                >
                  {isSavingApp ? 'Saving…' : 'Save Application State'}
                </button>
                {saveSuccess && (
                  <span style={{ fontSize: '12px', color: 'var(--domain-code, #1c8a62)', fontWeight: 600 }}>
                    ✓ Application state saved
                  </span>
                )}
              </div>
            </form>
          )}
        </div>

        {/* Modal Footer */}
        <div
          style={{
            padding: '14px 24px',
            borderTop: '1px solid var(--border, #e6e1d6)',
            background: 'var(--bg-card, #ffffff)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '10px',
          }}
        >
          {/* Re-verify Status Button */}
          <button
            type="button"
            onClick={() => onVerify && onVerify(opportunity.id)}
            disabled={isVerifying}
            className="radar-card-btn radar-card-btn-secondary"
          >
            <RefreshCw size={14} className={isVerifying ? 'spin' : ''} strokeWidth={1.8} aria-hidden="true" />
            <span>{isVerifying ? 'Checking Official Status…' : 'Re-verify Status'}</span>
          </button>

          {/* Action: Open original listing (validated external link) */}
          {hasValidExternalUrl ? (
            <a
              href={originalUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="radar-card-btn radar-card-btn-secondary"
              title="Open original listing"
              aria-label="Open original listing"
            >
              <span>Open listing</span>
              <ExternalLink size={14} strokeWidth={1.8} aria-hidden="true" />
            </a>
          ) : (
            <button
              type="button"
              disabled
              className="radar-card-btn radar-card-btn-secondary"
              title="Original listing URL unavailable"
              aria-label="Original listing URL unavailable"
            >
              <span>Original listing unavailable</span>
            </button>
          )}
        </div>
      </div>
    </Dialog>
  )
}
