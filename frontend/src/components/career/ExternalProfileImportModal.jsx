import React, { useState, useRef, useEffect } from 'react'
import { ingestExternalProfile, ingestExternalProfileFile } from '../../api/careerApi'
import Dialog from '../Dialog'
import LinkedInImportGuide from './LinkedInImportGuide'

const MAX_FILE_SIZE = 25 * 1024 * 1024 // 25 MB
const formatFileSize = (b) => b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1048576).toFixed(1)} MB`
const isAllowedFile = (name) => /\.(pdf|zip|csv|txt)$/i.test(name || '')

export default function ExternalProfileImportModal({
  show,
  onClose,
  onProfileIngested,
}) {
  const [sourceType, setSourceType] = useState('LINKEDIN_PASTED_TEXT')
  const [rawText, setRawText] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [pasteError, setPasteError] = useState(null)
  const [selectedFile, setSelectedFile] = useState(null)
  const [fileUploading, setFileUploading] = useState(false)
  const [uploadError, setUploadError] = useState(null)
  const [uploadSuccess, setUploadSuccess] = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const [isFocusedDropzone, setIsFocusedDropzone] = useState(false)

  const fileInputRef = useRef(null)
  const closeTimerRef = useRef(null)

  useEffect(() => () => { if (closeTimerRef.current) clearTimeout(closeTimerRef.current) }, [])

  if (!show) return null

  const isLinkedInUrl = /(?:https?:\/\/)?(?:www\.)?linkedin\.com\/in\//i.test(sourceUrl.trim())

  const handleProcessFile = async (chosen) => {
    if (!chosen) return
    if (chosen.size > MAX_FILE_SIZE) {
      setUploadError('File is larger than 25 MB. Please choose a smaller file or request only Profile, Positions, Education, Skills, and Certifications from LinkedIn.')
      setSelectedFile(null)
      return
    }
    if (!isAllowedFile(chosen.name)) {
      setUploadError('Unsupported file type. Please upload a LinkedIn profile PDF, export .zip, .csv, or .txt file.')
      setSelectedFile(null)
      return
    }

    setSelectedFile(chosen)
    setUploadError(null)
    setUploadSuccess(null)
    setFileUploading(true)

    try {
      const res = await ingestExternalProfileFile(chosen)
      const summary = res?.evidence_notes?.import_summary ||
        res?.extracted_content?.evidence_notes?.import_summary ||
        'Profile data extracted successfully.'
      setUploadSuccess(summary)
      if (onProfileIngested) {
        onProfileIngested(res, 'linkedin_file')
      }
      closeTimerRef.current = setTimeout(() => {
        onClose()
      }, 1200)
    } catch (err) {
      setUploadError(err.message || 'Failed to ingest file.')
    } finally {
      setFileUploading(false)
    }
  }

  const handleFileInputChange = (e) => {
    const chosen = e.target.files?.[0]
    if (chosen) handleProcessFile(chosen)
    e.target.value = ''
  }

  const handleRemoveFile = (e) => {
    e.stopPropagation()
    setSelectedFile(null)
    setUploadError(null)
    setUploadSuccess(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleIngest = async () => {
    if (!rawText.trim() && !sourceUrl.trim()) return
    setLoading(true)
    setPasteError(null)
    try {
      const res = await ingestExternalProfile(sourceType, rawText, sourceUrl || null)
      if (onProfileIngested) onProfileIngested(res, sourceType)
      onClose()
    } catch (err) {
      setPasteError(err.message || 'Failed to ingest profile information.')
    } finally {
      setLoading(false)
    }
  }

  const inputStyle = {
    width: '100%',
    padding: '10px',
    borderRadius: '8px',
    border: '1px solid var(--border, #e2e8f0)',
    fontSize: '13px',
    background: 'var(--bg-card, #ffffff)',
    color: 'var(--text-primary, #0f172a)',
    boxSizing: 'border-box',
    outline: 'none',
  }

  const labelStyle = {
    display: 'block',
    fontSize: '12px',
    fontWeight: '700',
    color: 'var(--text-muted, #64748b)',
    marginBottom: '6px',
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
              🔗 LinkedIn &amp; External Career Sources
            </h3>
            <p style={{ margin: '4px 0 0', fontSize: '12px', color: 'var(--text-muted, #64748b)' }}>
              Compliant, zero-scraping profile ingestion with transparent evidence attribution.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close modal"
            style={{
              background: 'transparent',
              border: 'none',
              fontSize: '18px',
              color: 'var(--text-muted, #64748b)',
              cursor: 'pointer',
              padding: '4px 8px',
              borderRadius: '6px',
              outline: 'none',
            }}
            onFocus={(e) => { e.currentTarget.style.boxShadow = '0 0 0 2px var(--primary, #2563eb)' }}
            onBlur={(e) => { e.currentTarget.style.boxShadow = 'none' }}
          >
            ✕
          </button>
        </div>

        {/* Form Body */}
        <div style={{ padding: '20px 24px', overflowY: 'auto', flex: 1 }}>
          <LinkedInImportGuide />

          {/* FIRST Section: Upload what LinkedIn gave you (best) */}
          <div style={{ marginBottom: '22px' }}>
            <h4
              id="upload-section-title"
              style={{ margin: '0 0 6px', fontSize: '14px', fontWeight: '800', color: 'var(--text-primary, #0f172a)' }}
            >
              Upload what LinkedIn gave you (best)
            </h4>
            <p style={{ margin: '0 0 10px', fontSize: '12px', color: 'var(--text-muted, #64748b)' }}>
              Upload your LinkedIn profile PDF (Save to PDF) or data export (.zip, .csv, .txt) for instant autofill.
            </p>

            <input
              ref={fileInputRef}
              id="linkedin-file-upload-input"
              type="file"
              accept=".pdf,.zip,.csv,.txt"
              onChange={handleFileInputChange}
              style={{ display: 'none' }}
              aria-label="Upload LinkedIn file"
            />

            <div
              tabIndex={0}
              role="button"
              aria-label="Choose or drop a LinkedIn file"
              onClick={() => { if (!fileUploading) fileInputRef.current?.click() }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  if (!fileUploading) fileInputRef.current?.click()
                }
              }}
              onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setDragOver(true) }}
              onDragLeave={(e) => { e.preventDefault(); e.stopPropagation(); setDragOver(false) }}
              onDrop={(e) => {
                e.preventDefault(); e.stopPropagation(); setDragOver(false)
                if (fileUploading) return
                const files = e.dataTransfer?.files
                if (files && files.length > 0) handleProcessFile(files[0])
              }}
              onFocus={() => setIsFocusedDropzone(true)}
              onBlur={() => setIsFocusedDropzone(false)}
              style={{
                border: `2px dashed ${dragOver || isFocusedDropzone ? 'var(--primary, #2563eb)' : 'var(--border, #cbd5e1)'}`,
                borderRadius: '12px',
                padding: '20px 16px',
                textAlign: 'center',
                background: dragOver ? 'var(--bg-card-soft, #eff6ff)' : 'var(--bg-card, #ffffff)',
                boxShadow: isFocusedDropzone ? '0 0 0 3px rgba(37, 99, 235, 0.25)' : 'none',
                cursor: fileUploading ? 'wait' : 'pointer',
                transition: 'all 0.15s ease',
                outline: 'none',
              }}
            >
              {fileUploading ? (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '6px' }}>
                  <span style={{ fontSize: '24px' }}>⏳</span>
                  <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--primary, #2563eb)' }}>
                    Uploading &amp; extracting profile data...
                  </div>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted, #64748b)' }}>
                    Extracting roles, education, skills, and contact details
                  </div>
                </div>
              ) : selectedFile ? (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px' }}>
                  <span style={{ fontSize: '24px' }}>📄</span>
                  <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary, #0f172a)' }}>
                    {selectedFile.name}
                  </div>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted, #64748b)' }}>
                    {formatFileSize(selectedFile.size)}
                  </div>
                  <button
                    type="button"
                    onClick={handleRemoveFile}
                    aria-label="Remove selected file"
                    style={{
                      marginTop: '4px', background: 'transparent', border: 'none',
                      color: 'var(--error, #ef4444)', fontSize: '12px', fontWeight: '600',
                      textDecoration: 'underline', cursor: 'pointer', padding: '2px 6px', outline: 'none',
                    }}
                    onFocus={(e) => { e.currentTarget.style.boxShadow = '0 0 0 2px var(--error, #ef4444)' }}
                    onBlur={(e) => { e.currentTarget.style.boxShadow = 'none' }}
                  >
                    Remove
                  </button>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '6px' }}>
                  <span style={{ fontSize: '26px' }}>📁</span>
                  <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary, #0f172a)' }}>
                    Drag &amp; drop your LinkedIn file here, or <span style={{ color: 'var(--primary, #2563eb)', textDecoration: 'underline' }}>browse</span>
                  </div>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted, #64748b)' }}>
                    Accepts .pdf (Save to PDF), .zip (archive), .csv, or .txt · Up to 25 MB
                  </div>
                </div>
              )}
            </div>

            {uploadSuccess && (
              <div
                role="status"
                aria-live="polite"
                style={{
                  marginTop: '10px', padding: '10px 14px', borderRadius: '8px',
                  background: '#f0fdf4', border: '1px solid #bbf7d0', color: '#166534',
                  fontSize: '12.5px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px',
                }}
              >
                <span>✓</span>
                <span>{uploadSuccess}</span>
              </div>
            )}

            {uploadError && (
              <div
                role="alert"
                style={{
                  marginTop: '10px', background: '#fee2e2', color: '#991b1b',
                  padding: '10px 14px', borderRadius: '8px', fontSize: '12px',
                }}
              >
                ⚠️ {uploadError}
              </div>
            )}
          </div>

          {/* SECOND Section: Or paste it */}
          <div style={{ borderTop: '1px solid var(--border, #e2e8f0)', paddingTop: '16px' }}>
            <h4 style={{ margin: '0 0 10px', fontSize: '14px', fontWeight: '800', color: 'var(--text-primary, #0f172a)' }}>
              Or paste it
            </h4>

            {/* Source Tabs */}
            <div style={{ display: 'flex', borderBottom: '1px solid var(--border, #e2e8f0)', marginBottom: '14px', flexWrap: 'wrap' }}>
              {[
                { id: 'LINKEDIN_PASTED_TEXT', label: '📋 Paste LinkedIn Text' },
                { id: 'LINKEDIN_DATA_EXPORT', label: '📁 LinkedIn Data Export' },
                { id: 'PORTFOLIO_SITE', label: '🌐 Portfolio Link' },
              ].map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => { setSourceType(tab.id); setPasteError(null) }}
                  style={{
                    padding: '8px 12px', fontSize: '12.5px',
                    fontWeight: sourceType === tab.id ? '700' : '500',
                    color: sourceType === tab.id ? 'var(--primary, #2563eb)' : 'var(--text-muted, #64748b)',
                    border: 'none', background: 'transparent',
                    borderBottom: sourceType === tab.id ? '2px solid var(--primary, #2563eb)' : '2px solid transparent',
                    cursor: 'pointer', outline: 'none',
                  }}
                  onFocus={(e) => { e.currentTarget.style.boxShadow = 'inset 0 -2px 0 var(--primary, #2563eb)' }}
                  onBlur={(e) => { e.currentTarget.style.boxShadow = 'none' }}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {sourceType === 'LINKEDIN_PASTED_TEXT' && (
              <div>
                <label htmlFor="paste-linkedin-text" style={labelStyle}>
                  Paste LinkedIn Profile Text (About, Experience, Education, Skills)
                </label>
                <textarea
                  id="paste-linkedin-text"
                  value={rawText}
                  onChange={(e) => setRawText(e.target.value)}
                  rows={6}
                  placeholder="Copy and paste text from your LinkedIn profile here..."
                  style={inputStyle}
                />
              </div>
            )}

            {sourceType === 'LINKEDIN_DATA_EXPORT' && (
              <div>
                <label htmlFor="paste-linkedin-csv" style={labelStyle}>
                  Paste Content from LinkedIn Export File (Positions.csv or Skills.csv)
                </label>
                <textarea
                  id="paste-linkedin-csv"
                  value={rawText}
                  onChange={(e) => setRawText(e.target.value)}
                  rows={6}
                  placeholder="Paste CSV rows from your LinkedIn data archive download here..."
                  style={{ ...inputStyle, fontFamily: 'monospace', fontSize: '12px' }}
                />
                <p style={{ margin: '6px 0 0', fontSize: '11px', color: 'var(--text-muted, #64748b)' }}>
                  Obtain your official archive at LinkedIn: Settings &gt; Data Privacy &gt; Get a copy of your data.
                </p>
              </div>
            )}

            {sourceType === 'PORTFOLIO_SITE' && (
              <div>
                <label htmlFor="portfolio-site-url" style={labelStyle}>
                  Personal Website, Portfolio, or Technical Blog URL
                </label>
                <input
                  id="portfolio-site-url"
                  type="url"
                  value={sourceUrl}
                  onChange={(e) => setSourceUrl(e.target.value)}
                  placeholder="https://yourportfolio.dev"
                  style={{ ...inputStyle, marginBottom: isLinkedInUrl ? '8px' : '12px' }}
                />
                {isLinkedInUrl && (
                  <div
                    role="note"
                    style={{
                      margin: '0 0 12px', padding: '8px 12px', borderRadius: '8px',
                      background: 'var(--bg-card-soft, #f8fafc)', border: '1px solid var(--border, #e2e8f0)',
                      fontSize: '12px', color: 'var(--text-secondary, #334155)', lineHeight: 1.45,
                    }}
                  >
                    ℹ️ I can't open LinkedIn pages for you (LinkedIn blocks that), but I saved this link on your profile. Use Save to PDF above to fill the rest.
                  </div>
                )}
                <label htmlFor="portfolio-site-notes" style={labelStyle}>
                  Optional Notes or Key Highlights from Portfolio
                </label>
                <textarea
                  id="portfolio-site-notes"
                  value={rawText}
                  onChange={(e) => setRawText(e.target.value)}
                  rows={3}
                  placeholder="E.g. Featured projects, published papers, or live demos..."
                  style={inputStyle}
                />
              </div>
            )}

            {pasteError && (
              <div
                role="alert"
                style={{
                  marginTop: '12px', background: '#fee2e2', color: '#991b1b',
                  padding: '10px 14px', borderRadius: '8px', fontSize: '12px',
                }}
              >
                ⚠️ {pasteError}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '14px 24px',
            borderTop: '1px solid var(--border, #e2e8f0)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: 'var(--bg-card-soft, #f8fafc)',
          }}
        >
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'transparent',
              border: '1px solid var(--border, #e2e8f0)',
              padding: '8px 16px',
              borderRadius: '8px',
              fontSize: '13px',
              cursor: 'pointer',
              color: 'var(--text-muted, #64748b)',
              outline: 'none',
            }}
            onFocus={(e) => { e.currentTarget.style.boxShadow = '0 0 0 2px var(--border, #94a3b8)' }}
            onBlur={(e) => { e.currentTarget.style.boxShadow = 'none' }}
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
              opacity: loading || (!rawText.trim() && !sourceUrl.trim()) ? 0.6 : 1,
              outline: 'none',
            }}
            onFocus={(e) => { e.currentTarget.style.boxShadow = '0 0 0 2px var(--primary-hover, #1d4ed8)' }}
            onBlur={(e) => { e.currentTarget.style.boxShadow = 'none' }}
          >
            {loading ? '⏳ Ingesting...' : 'Parse & Review Profile Data'}
          </button>
        </div>
      </div>
    </Dialog>
  )
}
