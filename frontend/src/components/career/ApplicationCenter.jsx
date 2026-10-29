import React, { useState, useEffect, useCallback, useMemo } from 'react'
import {
  fetchApplications,
  updateApplication,
  prepareBatch,
  approveBatch,
  submitBatch,
  draftCoverLetter,
  setApplicationCoverLetter,
} from '../../api/careerApi'
import BatchApprovalModal from './BatchApprovalModal'
import HandoffKitModal from './HandoffKitModal'
import HandoffKitDrawer from './HandoffKitDrawer'
import ReturnSubmissionPrompt from './ReturnSubmissionPrompt'
import CoverLetterModal from './CoverLetterModal'
import { cleanOpportunity } from '../../utils/jobCardCleaner'
import { buildStatusOptions, summarizeBatchResults } from '../../utils/careerUiHelpers'

export default function ApplicationCenter({ onNavigateToResumeStudio }) {
  const [applications, setApplications] = useState([])
  const [selectedAppIds, setSelectedAppIds] = useState(new Set())
  const [currentBatch, setCurrentBatch] = useState(null)
  const [showApprovalModal, setShowApprovalModal] = useState(false)
  const [activeKit, setActiveKit] = useState(null)
  const [activeDrawerApp, setActiveDrawerApp] = useState(null)
  const [activeLetterApp, setActiveLetterApp] = useState(null)
  const [letterDraftingId, setLetterDraftingId] = useState(null)
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [loading, setLoading] = useState(true)
  const [processing, setProcessing] = useState(false)
  const [submitResult, setSubmitResult] = useState(null)
  const [error, setError] = useState(null)

  // Explicit approval check states (Section 3.3)
  const [attestationConfirmed, setAttestationConfirmed] = useState(false)
  const [workAuthConfirmed, setWorkAuthConfirmed] = useState(false)
  const [legalAccepted, setLegalAccepted] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const apps = await fetchApplications()
      setApplications(apps)
    } catch (err) {
      setError(err.message || 'Failed to load applications')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  const toggleSelectApp = (id) => {
    setSelectedAppIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const visibleApps = useMemo(() => {
    return applications.filter(a => {
      if (statusFilter === 'ALL') return true
      if (statusFilter === 'HANDOFF_READY') return a.status === 'HANDOFF_KIT_READY'
      if (statusFilter === 'NEEDS_REVIEW') return ['READY_FOR_REVIEW', 'READY_FOR_APPROVAL', 'PREPARING'].includes(a.status)
      if (statusFilter === 'APPROVED') return a.status === 'APPROVED_FOR_SUBMISSION'
      if (statusFilter === 'SUBMITTED') return ['SUBMITTED', 'MANUAL_SUBMISSION_REQUIRED'].includes(a.status)
      if (statusFilter === 'INTERVIEWS') return ['INTERVIEW', 'OFFER_RECEIVED'].includes(a.status)
      return true
    })
  }, [applications, statusFilter])

  const handleSelectAll = () => {
    setSelectedAppIds(prev => {
      const next = new Set(prev)
      const allSelected = visibleApps.length > 0 && visibleApps.every(a => next.has(a.id))
      if (allSelected) {
        visibleApps.forEach(a => next.delete(a.id))
      } else {
        visibleApps.forEach(a => next.add(a.id))
      }
      return next
    })
  }

  const handlePrepareBatchReview = async () => {
    if (selectedAppIds.size === 0) return
    setProcessing(true)
    setError(null)
    try {
      const selectedApps = applications.filter(a => selectedAppIds.has(a.id))
      const oppIds = selectedApps.map(a => a.opportunity_id)
      const batch = await prepareBatch(oppIds)
      setCurrentBatch(batch)
      setShowApprovalModal(true)
      // Reset attestations
      setAttestationConfirmed(false)
      setWorkAuthConfirmed(false)
      setLegalAccepted(false)
    } catch (err) {
      setError(err.message || 'Failed to prepare batch')
    } finally {
      setProcessing(false)
    }
  }

  const handleExecuteApprovalAndSubmit = async () => {
    if (!currentBatch) return
    setProcessing(true)
    setError(null)
    try {
      // 1. Explicit approval gate (Section 3.3)
      await approveBatch(currentBatch.batch_id, {
        attestation_confirmed: attestationConfirmed,
        work_auth_confirmed: workAuthConfirmed,
        legal_statements_accepted: legalAccepted,
      })

      // 2. Submit approved batch
      const res = await submitBatch(currentBatch.batch_id, 'manual_handoff')
      setSubmitResult(res)
      setShowApprovalModal(false)
      setSelectedAppIds(new Set())
      await loadData()
    } catch (err) {
      setError(err.message || 'Batch execution failed')
    } finally {
      setProcessing(false)
    }
  }

  const handleStatusChange = async (appId, newStatus) => {
    try {
      await updateApplication(appId, { status: newStatus })
      setApplications(prev =>
        prev.map(a => (a.id === appId ? { ...a, status: newStatus } : a))
      )
    } catch (err) {
      setError(err.message || 'Failed to update status')
    }
  }

  const handleDraftCoverLetter = async (app) => {
    setLetterDraftingId(app.id)
    setError(null)
    try {
      const res = await draftCoverLetter(app.opportunity_id)
      await setApplicationCoverLetter(app.id, res.content)
      setApplications(prev => prev.map(a => a.id === app.id ? { ...a, cover_letter: res.content } : a))
      setActiveLetterApp({ ...app, cover_letter: res.content })
    } catch (err) {
      setError(err.message || 'Failed to draft cover letter')
    } finally {
      setLetterDraftingId(null)
    }
  }

  const handleSaveCoverLetter = async (appId, text) => {
    setError(null)
    try {
      await setApplicationCoverLetter(appId, text)
      setApplications(prev => prev.map(a => a.id === appId ? { ...a, cover_letter: text } : a))
      setActiveLetterApp(prev => prev ? { ...prev, cover_letter: text } : null)
      alert('Cover letter saved!')
    } catch (err) {
      setError(err.message || 'Failed to save cover letter')
    }
  }

  if (loading) {
    return (
      <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
        <div className="spinner" style={{ margin: '0 auto 12px' }} />
        <p>Loading Application Center...</p>
      </div>
    )
  }

  const batchSummary = summarizeBatchResults(submitResult?.results)

  return (
    <div style={{ padding: '0 8px 32px', maxWidth: '1200px', margin: '0 auto' }}>
      {/* Header bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px', marginBottom: '24px' }}>
        <div>
          <h2 style={{ margin: '0 0 6px', fontSize: '22px', fontWeight: '800', color: 'var(--text-primary)' }}>
            🚀 Application Center
          </h2>
          <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-muted)' }}>
            Track application pipelines, review batches, enforce explicit submission approvals, and access verified handoff kits.
          </p>
        </div>

        {selectedAppIds.size > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span style={{ fontSize: '13px', fontWeight: '700', color: 'var(--primary)' }}>
              {selectedAppIds.size} Selected
            </span>
            <button
              type="button"
              onClick={handlePrepareBatchReview}
              disabled={processing}
              style={{
                background: 'var(--primary)',
                color: '#fff',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '8px',
                fontSize: '13px',
                fontWeight: '700',
                cursor: 'pointer',
              }}
            >
              📋 Review & Approve Batch
            </button>
          </div>
        )}
      </div>

      {error && (
        <div style={{ background: '#fee2e2', color: '#991b1b', padding: '12px 16px', borderRadius: '8px', marginBottom: '20px', fontSize: '13px' }}>
          ⚠️ {error}
        </div>
      )}

      {submitResult && (
        <div style={{ background: 'var(--bg-card-soft)', border: '1px solid var(--border)', borderRadius: '12px', padding: '16px', marginBottom: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <h4 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '15px', fontWeight: '800' }}>
              {batchSummary.message}
            </h4>
            <button
              type="button"
              onClick={() => setSubmitResult(null)}
              style={{ background: 'transparent', border: 'none', color: 'var(--text-primary)', cursor: 'pointer', fontWeight: 'bold' }}
            >
              ✕
            </button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {submitResult.results.map((r, idx) => (
              <div key={idx} style={{ fontSize: '13px', color: 'var(--text-secondary)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>• <strong>{r.company_name}</strong> ({r.role_title}): {r.message}</span>
                {r.manual_package && (
                  <button
                    type="button"
                    onClick={() => setActiveKit(r.manual_package)}
                    style={{
                      background: '#15803d',
                      color: '#fff',
                      border: 'none',
                      padding: '4px 8px',
                      borderRadius: '4px',
                      fontSize: '11px',
                      cursor: 'pointer',
                    }}
                  >
                    View Application Kit
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Pipeline Filter Tabs */}
      <div
        role="tablist"
        aria-label="Application pipeline stages"
        className="unified-tablist"
        style={{
          borderBottom: '1px solid var(--border)',
          marginBottom: '16px',
          paddingLeft: 0,
          paddingRight: 0,
        }}
      >
        {[
          { id: 'ALL', label: `All (${applications.length})` },
          { id: 'HANDOFF_READY', label: `Handoff Ready (${applications.filter(a => a.status === 'HANDOFF_KIT_READY').length})` },
          { id: 'NEEDS_REVIEW', label: `Needs Review (${applications.filter(a => ['READY_FOR_REVIEW', 'READY_FOR_APPROVAL', 'PREPARING'].includes(a.status)).length})` },
          { id: 'APPROVED', label: `Approved (${applications.filter(a => a.status === 'APPROVED_FOR_SUBMISSION').length})` },
          { id: 'SUBMITTED', label: `Submitted (${applications.filter(a => ['SUBMITTED', 'MANUAL_SUBMISSION_REQUIRED'].includes(a.status)).length})` },
          { id: 'INTERVIEWS', label: `Interviews & Offers (${applications.filter(a => ['INTERVIEW', 'OFFER_RECEIVED'].includes(a.status)).length})` },
        ].map(tab => {
          const isActive = statusFilter === tab.id
          return (
            <button
              key={tab.id}
              id={`app-tab-${tab.id.toLowerCase()}`}
              role="tab"
              aria-selected={isActive}
              tabIndex={isActive ? 0 : -1}
              type="button"
              onClick={() => setStatusFilter(tab.id)}
              className={`unified-tab ${isActive ? 'active' : ''}`}
            >
              <span>{tab.label}</span>
            </button>
          )
        })}
      </div>

      {/* Applications Table / Cards */}
      {applications.length === 0 ? (
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '12px', padding: '48px 24px', textAlign: 'center' }}>
          <span style={{ fontSize: '40px', display: 'block', marginBottom: '12px' }}>📁</span>
          <h3 style={{ margin: '0 0 8px', fontSize: '17px', color: 'var(--text-primary)' }}>No Applications Tracked Yet</h3>
          <p style={{ margin: '0 0 16px', fontSize: '13px', color: 'var(--text-muted)' }}>
            Discover verified openings in Internship Radar and click &quot;Prepare Application&quot; to begin your personalized pipeline.
          </p>
        </div>
      ) : (
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '12px', overflow: 'hidden' }}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
              <thead>
                <tr style={{ background: 'var(--bg-card-soft)', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                  <th style={{ padding: '12px 16px', width: '36px' }}>
                    <input
                      type="checkbox"
                      checked={visibleApps.length > 0 && visibleApps.every(a => selectedAppIds.has(a.id))}
                      onChange={handleSelectAll}
                    />
                  </th>
                  <th style={{ padding: '12px 16px' }}>Opportunity</th>
                  <th style={{ padding: '12px 16px' }}>Status</th>
                  <th style={{ padding: '12px 16px' }}>Tailored Resume</th>
                  <th style={{ padding: '12px 16px' }}>Cover Letter</th>
                  <th style={{ padding: '12px 16px' }}>Method</th>
                  <th style={{ padding: '12px 16px' }}>Deadline</th>
                  <th style={{ padding: '12px 16px', textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {visibleApps.map((app) => {
                    const isSelected = selectedAppIds.has(app.id)
                    const opp = app.opportunity || {}
                    const cleanedOpp = cleanOpportunity(opp)
                    const resume = app.resume || {}

                    return (
                      <tr
                        key={app.id}
                        style={{
                          borderBottom: '1px solid var(--border)',
                          background: isSelected ? 'var(--primary-soft, #eff6ff)' : 'transparent',
                        }}
                      >
                        <td style={{ padding: '12px 16px' }}>
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelectApp(app.id)}
                          />
                        </td>
                        <td style={{ padding: '12px 16px' }}>
                          <div style={{ fontWeight: '700', color: 'var(--text-primary)' }}>
                            {cleanedOpp.company !== 'Company' ? cleanedOpp.company : (opp.company_name || `Opportunity #${app.opportunity_id}`)}
                          </div>
                          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                            {cleanedOpp.role} {cleanedOpp.locationLine && cleanedOpp.locationLine !== 'Location unspecified' ? `• ${cleanedOpp.locationLine}` : ''}
                          </div>
                          {app.missing_fields && app.missing_fields.length > 0 && (
                            <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: '#b91c1c', background: '#fee2e2', padding: '1px 6px', borderRadius: '4px', marginTop: '4px' }}>
                              <span>⚠️ Missing: {app.missing_fields.join(', ')}</span>
                              <button
                                type="button"
                                onClick={() => onNavigateToResumeStudio?.()}
                                style={{
                                  background: 'transparent',
                                  border: 'none',
                                  color: '#b91c1c',
                                  fontWeight: '700',
                                  cursor: 'pointer',
                                  padding: '0',
                                  fontSize: '11px',
                                  textDecoration: 'underline'
                                }}
                              >
                                Fix now
                              </button>
                            </div>
                          )}
                        </td>
                        <td style={{ padding: '12px 16px' }}>
                          <select
                            value={app.status}
                            onChange={(e) => handleStatusChange(app.id, e.target.value)}
                            style={{
                              padding: '4px 8px',
                              borderRadius: '6px',
                              border: '1px solid var(--border)',
                              background: 'var(--bg-card-soft)',
                              color: 'var(--text-primary)',
                              fontSize: '12px',
                              fontWeight: '600',
                            }}
                          >
                            {buildStatusOptions(app.status).map(opt => (
                              <option key={opt.value} value={opt.value}>{opt.label}</option>
                            ))}
                          </select>
                        </td>
                        <td style={{ padding: '12px 16px' }}>
                          {resume.title ? (
                            <span style={{ fontSize: '12px', color: 'var(--primary)', fontWeight: '600' }}>
                              ✓ {resume.title}
                            </span>
                          ) : (
                            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Drafting</span>
                          )}
                        </td>
                        <td style={{ padding: '12px 16px' }}>
                          {app.cover_letter ? (
                            <button
                              type="button"
                              onClick={() => setActiveLetterApp(app)}
                              style={{
                                background: 'var(--bg-card-soft)',
                                border: '1px solid var(--border)',
                                color: 'var(--text-primary)',
                                padding: '3px 8px',
                                borderRadius: '6px',
                                fontSize: '11px',
                                fontWeight: '600',
                                cursor: 'pointer',
                              }}
                            >
                              ✍️ View Letter
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() => handleDraftCoverLetter(app)}
                              disabled={letterDraftingId === app.id}
                              style={{
                                background: 'transparent',
                                border: '1px dashed var(--border)',
                                color: 'var(--text-muted)',
                                padding: '3px 8px',
                                borderRadius: '6px',
                                fontSize: '11px',
                                cursor: 'pointer',
                              }}
                            >
                              {letterDraftingId === app.id ? 'Drafting...' : '+ Draft Letter'}
                            </button>
                          )}
                        </td>
                        <td style={{ padding: '12px 16px' }}>
                          <span style={{ fontSize: '11px', background: 'var(--bg-card-soft)', padding: '2px 8px', borderRadius: '4px', border: '1px solid var(--border)' }}>
                            {app.submission_method ? app.submission_method.replace('_', ' ') : 'Manual'}
                          </span>
                        </td>
                        <td style={{ padding: '12px 16px', color: 'var(--text-muted)', fontSize: '12px' }}>
                          {app.target_deadline || opp.confirmed_close_date || 'Rolling'}
                        </td>
                        <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                          <div style={{ display: 'flex', gap: '6px', justifyContent: 'flex-end', alignItems: 'center' }}>
                            <button
                              type="button"
                              onClick={() => setActiveDrawerApp(app)}
                              style={{
                                background: 'var(--brand, #3b82f6)',
                                color: '#ffffff',
                                border: 'none',
                                padding: '4px 10px',
                                borderRadius: '6px',
                                fontSize: '12px',
                                fontWeight: '600',
                                cursor: 'pointer',
                              }}
                            >
                              📋 Handoff Kit
                            </button>
                            {opp.official_application_url && (
                              <a
                                href={opp.official_application_url}
                                target="_blank"
                                rel="noreferrer"
                                style={{
                                  color: 'var(--primary)',
                                  fontSize: '12px',
                                  fontWeight: '600',
                                  textDecoration: 'none',
                                }}
                              >
                                ↗
                              </a>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Explicit Batch Approval Modal (Sections 3.3 & 9.1) */}
      <BatchApprovalModal
        show={showApprovalModal}
        onClose={() => setShowApprovalModal(false)}
        currentBatch={currentBatch}
        attestationConfirmed={attestationConfirmed}
        setAttestationConfirmed={setAttestationConfirmed}
        workAuthConfirmed={workAuthConfirmed}
        setWorkAuthConfirmed={setWorkAuthConfirmed}
        legalAccepted={legalAccepted}
        setLegalAccepted={setLegalAccepted}
        onConfirm={handleExecuteApprovalAndSubmit}
        processing={processing}
        error={error}
      />

      {/* Manual Handoff Application Kit Drawer (Section 10.1) */}
      <HandoffKitModal
        activeKit={activeKit}
        onClose={() => setActiveKit(null)}
      />

      {/* Standalone Cover Letter View / Edit Modal */}
      <CoverLetterModal
        activeLetterApp={activeLetterApp}
        onClose={() => setActiveLetterApp(null)}
        onSave={handleSaveCoverLetter}
      />

      {/* Comprehensive Tenant-Scoped Handoff Kit Drawer */}
      <HandoffKitDrawer
        isOpen={Boolean(activeDrawerApp)}
        onClose={() => setActiveDrawerApp(null)}
        applicationId={activeDrawerApp?.id}
        opportunity={activeDrawerApp?.opportunity}
        onNavigateToResumeStudio={onNavigateToResumeStudio}
        onMarkApplied={async () => {
          await loadData()
          setActiveDrawerApp(null)
        }}
      />

      {/* Dismissible Post-External-Return Prompt */}
      <ReturnSubmissionPrompt
        onSubmissionConfirmed={async () => {
          await loadData()
        }}
      />
    </div>
  )
}
