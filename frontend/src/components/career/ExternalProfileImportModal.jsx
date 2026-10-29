import React, { useState } from 'react'
import { ingestExternalProfile } from '../../api/careerApi'
import Dialog from '../Dialog'

export default function ExternalProfileImportModal({
  show,
  onClose,
  onProfileIngested,
}) {
  const [sourceType, setSourceType] = useState('LINKEDIN_PASTED_TEXT')
  const [rawText, setRawText] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  if (!show) return null

  const handleIngest = async () => {
    if (!rawText.trim() && !sourceUrl.trim()) return
    setLoading(true)
    setError(null)
    try {
      const res = await ingestExternalProfile(sourceType, rawText, sourceUrl || null)
      if (onProfileIngested) {
        onProfileIngested(res, sourceType)
      }
      onClose()
    } catch (err) {
      setError(err.message || 'Failed to ingest profile information.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog onClose={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.75)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1100,
        padding: '20px',
      }}
    >
      <div
        style={{
          background: 'var(--bg-card, #ffffff)',
          border: '1px solid var(--border, #e2e8f0)',
          borderRadius: '16px',
          maxWidth: '680px',
          width: '100%',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '18px 24px',
            borderBottom: '1px solid var(--border, #e2e8f0)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: 'var(--bg-card-soft, #f8fafc)',
          }}
        >
          <div>
            <h3 style={{ margin: 0, fontSize: '18px', fontWeight: '800', color: 'var(--text-primary, #0f172a)' }}>
              🔗 LinkedIn & External Career Sources
            </h3>
            <p style={{ margin: '4px 0 0', fontSize: '12px', color: 'var(--text-muted, #64748b)' }}>
              Compliant, zero-scraping profile ingestion with transparent evidence attribution.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{ background: 'transparent', border: 'none', fontSize: '18px', color: 'var(--text-muted)', cursor: 'pointer' }}
          >
            ✕
          </button>
        </div>

        {/* Source Tabs */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', padding: '0 24px', background: 'var(--bg-card)' }}>
          {[
            { id: 'LINKEDIN_PASTED_TEXT', label: '📋 Paste LinkedIn Text' },
            { id: 'LINKEDIN_DATA_EXPORT', label: '📁 LinkedIn Data Export' },
            { id: 'PORTFOLIO_SITE', label: '🌐 Portfolio Link' },
          ].map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => {
                setSourceType(tab.id)
                setError(null)
              }}
              style={{
                padding: '12px 14px',
                fontSize: '13px',
                fontWeight: sourceType === tab.id ? '700' : '500',
                color: sourceType === tab.id ? 'var(--primary, #2563eb)' : 'var(--text-muted, #64748b)',
                border: 'none',
                background: 'transparent',
                borderBottom: sourceType === tab.id ? '2px solid var(--primary, #2563eb)' : '2px solid transparent',
                cursor: 'pointer',
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Form Body */}
        <div style={{ padding: '20px 24px', overflowY: 'auto', flex: 1 }}>
          <div
            style={{
              background: '#f8fafc',
              border: '1px solid #e2e8f0',
              borderRadius: '8px',
              padding: '10px 14px',
              marginBottom: '16px',
              fontSize: '12px',
              color: '#334155',
            }}
          >
            🛡️ <strong>Privacy & Security Invariant:</strong> Compass complies with strict privacy policies and never uses automated bots or unauthorized scraping against LinkedIn. All ingested data is explicitly provided by you and verified before saving.
          </div>

          {sourceType === 'LINKEDIN_PASTED_TEXT' && (
            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: '700', color: 'var(--text-muted)', marginBottom: '6px' }}>
                Paste LinkedIn Profile Text (About, Experience, Education, Skills)
              </label>
              <textarea
                value={rawText}
                onChange={(e) => setRawText(e.target.value)}
                rows={8}
                placeholder="Copy and paste text from your LinkedIn profile here..."
                style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid var(--border)', fontSize: '13px' }}
              />
            </div>
          )}

          {sourceType === 'LINKEDIN_DATA_EXPORT' && (
            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: '700', color: 'var(--text-muted)', marginBottom: '6px' }}>
                Paste Content from LinkedIn Export File (Positions.csv or Skills.csv)
              </label>
              <textarea
                value={rawText}
                onChange={(e) => setRawText(e.target.value)}
                rows={8}
                placeholder="Paste CSV rows from your LinkedIn data archive download here..."
                style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid var(--border)', fontSize: '12px', fontFamily: 'monospace' }}
              />
              <p style={{ margin: '6px 0 0', fontSize: '11px', color: 'var(--text-muted)' }}>
                Obtain your official archive at LinkedIn: Settings &gt; Data Privacy &gt; Get a copy of your data.
              </p>
            </div>
          )}

          {sourceType === 'PORTFOLIO_SITE' && (
            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: '700', color: 'var(--text-muted)', marginBottom: '6px' }}>
                Personal Website, Portfolio, or Technical Blog URL
              </label>
              <input
                type="url"
                value={sourceUrl}
                onChange={(e) => setSourceUrl(e.target.value)}
                placeholder="https://yourportfolio.dev"
                style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid var(--border)', fontSize: '13px', marginBottom: '12px' }}
              />
              <label style={{ display: 'block', fontSize: '12px', fontWeight: '700', color: 'var(--text-muted)', marginBottom: '6px' }}>
                Optional Notes or Key Highlights from Portfolio
              </label>
              <textarea
                value={rawText}
                onChange={(e) => setRawText(e.target.value)}
                rows={4}
                placeholder="E.g. Featured projects, published papers, or live demos..."
                style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid var(--border)', fontSize: '13px' }}
              />
            </div>
          )}

          {error && (
            <div style={{ marginTop: '12px', background: '#fee2e2', color: '#991b1b', padding: '10px 14px', borderRadius: '8px', fontSize: '12px' }}>
              ⚠️ {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '14px 24px',
            borderTop: '1px solid var(--border)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: 'var(--bg-card-soft)',
          }}
        >
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'transparent',
              border: '1px solid var(--border)',
              padding: '8px 16px',
              borderRadius: '8px',
              fontSize: '13px',
              cursor: 'pointer',
              color: 'var(--text-muted)',
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleIngest}
            disabled={loading || (!rawText.trim() && !sourceUrl.trim())}
            style={{
              background: 'var(--primary, #2563eb)',
              color: '#fff',
              border: 'none',
              padding: '8px 20px',
              borderRadius: '8px',
              fontSize: '13px',
              fontWeight: '700',
              cursor: loading ? 'wait' : 'pointer',
            }}
          >
            {loading ? '⏳ Ingesting...' : 'Parse & Review Profile Data'}
          </button>
        </div>
      </div>
    </Dialog>
  )
}
