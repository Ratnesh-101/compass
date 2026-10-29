import React from 'react'
import { ShieldCheck } from 'lucide-react'
import Dialog from '../Dialog'

export default function BatchApprovalModal({
  show,
  onClose,
  currentBatch,
  attestationConfirmed,
  setAttestationConfirmed,
  workAuthConfirmed,
  setWorkAuthConfirmed,
  legalAccepted,
  setLegalAccepted,
  onConfirm,
  processing,
  error = null,
}) {
  if (!show || !currentBatch) return null

  const isFormValid = attestationConfirmed && workAuthConfirmed && legalAccepted && !processing

  return (
    <Dialog onClose={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(27, 26, 23, 0.45)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '16px',
        backdropFilter: 'blur(3px)',
      }}
    >
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-card, 8px)',
          maxWidth: '680px',
          width: '100%',
          padding: '24px',
          boxShadow: '0 8px 30px rgba(0, 0, 0, 0.12)',
          maxHeight: '90vh',
          overflowY: 'auto',
        }}
      >
        <h3 style={{ margin: '0 0 8px', fontSize: '18px', fontWeight: '600', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <ShieldCheck size={18} strokeWidth={1.8} />
          <span>Explicit Batch Submission Approval</span>
        </h3>
        <p style={{ margin: '0 0 16px', fontSize: '13px', color: 'var(--text-muted)' }}>
          Compass enforces strict user authorization before any external application action.
          Review the {currentBatch.total_count} selected opportunities and confirm your attestations.
        </p>

        {/* Opportunities in batch */}
        <div style={{ background: 'var(--bg-card-soft)', border: '1px solid var(--border)', borderRadius: 'var(--radius-card, 8px)', padding: '12px', marginBottom: '16px' }}>
          <div style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-muted)', marginBottom: '6px' }}>
            Included Applications ({currentBatch.applications.length}):
          </div>
          <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '13px', color: 'var(--text-primary)' }}>
            {currentBatch.applications.map((a, i) => (
              <li key={i}>
                <strong>{a.opportunity?.company_name || `Opp #${a.opportunity_id}`}</strong>: {a.opportunity?.role_title}
              </li>
            ))}
          </ul>
        </div>

        {/* Mandatory Attestation Checkboxes */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '20px' }}>
          <label style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', fontSize: '13px', color: 'var(--text-primary)', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={attestationConfirmed}
              onChange={(e) => setAttestationConfirmed(e.target.checked)}
              style={{ marginTop: '2px' }}
            />
            <span>
              <strong>Factual Integrity Attestation:</strong> I attest that all candidate qualifications, degree dates, and resume statements in this batch are truthful and verified.
            </span>
          </label>

          <label style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', fontSize: '13px', color: 'var(--text-primary)', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={workAuthConfirmed}
              onChange={(e) => setWorkAuthConfirmed(e.target.checked)}
              style={{ marginTop: '2px' }}
            />
            <span>
              <strong>Work Authorization:</strong> I confirm my eligibility to undertake these internships in India / remotely.
            </span>
          </label>

          <label style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', fontSize: '13px', color: 'var(--text-primary)', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={legalAccepted}
              onChange={(e) => setLegalAccepted(e.target.checked)}
              style={{ marginTop: '2px' }}
            />
            <span>
              <strong>Legal Acceptance:</strong> I authorize Compass to prepare and package these applications for submission under my explicit instruction.
            </span>
          </label>
        </div>

        {error && (
          <div
            role="alert"
            style={{ background: '#fee2e2', color: '#991b1b', padding: '10px 12px', borderRadius: '8px', marginBottom: '14px', fontSize: '13px', whiteSpace: 'pre-wrap' }}
          >
            {error}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <button
            type="button"
            onClick={onClose}
            className="btn-touch-target btn-secondary"
            style={{
              padding: '8px 16px',
              borderRadius: 'var(--radius-btn, 6px)',
              fontSize: '13px',
              fontWeight: '500',
              cursor: 'pointer',
              minHeight: '44px',
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!isFormValid}
            className={`btn-touch-target ${isFormValid ? 'btn-primary-amber' : 'btn-secondary'}`}
            style={{
              padding: '8px 18px',
              borderRadius: 'var(--radius-btn, 6px)',
              fontSize: '13px',
              fontWeight: '600',
              cursor: !isFormValid ? 'not-allowed' : 'pointer',
              minHeight: '44px',
            }}
          >
            {processing ? 'Processing...' : 'Approve & prepare kits'}
          </button>
        </div>
      </div>
    </Dialog>
  )
}
