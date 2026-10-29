import React, { useRef, useState } from 'react'
import { parseResumeFile } from '../../api/careerApi'
import Dialog from '../Dialog'

export default function ResumeImportModal({
  show,
  onClose,
  importText,
  setImportText,
  onImport,
  importing,
  importSuccess,
  onFileExtracted,
}) {
  const fileInputRef = useRef(null)
  const [fileError, setFileError] = useState(null)
  const [uploadingFile, setUploadingFile] = useState(false)

  if (!show) return null

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setFileError(null)
    setUploadingFile(true)
    try {
      const res = await parseResumeFile(file)
      if (res.success && res.extracted_content) {
        if (onFileExtracted) {
          onFileExtracted(res)
        }
      } else {
        setFileError(res.error_message || 'Failed to extract text from document.')
      }
    } catch (err) {
      setFileError(err.message || 'File upload failed.')
    } finally {
      setUploadingFile(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  return (
    <Dialog onClose={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(15, 23, 42, 0.65)',
        backdropFilter: 'blur(6px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '16px',
      }}
    >
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: '18px',
          maxWidth: '640px',
          width: '100%',
          padding: '28px',
          boxShadow: '0 25px 50px -12px rgba(15, 23, 42, 0.25)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <h3 style={{ margin: 0, fontSize: '18px', fontWeight: '800', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>📥</span>
            <span>Import Resume File or Paste Text</span>
          </h3>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'var(--bg-card-soft)',
              border: '1px solid var(--border)',
              color: 'var(--text-secondary)',
              fontSize: '16px',
              width: '32px',
              height: '32px',
              borderRadius: '8px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            ✕
          </button>
        </div>

        <p style={{ margin: '0 0 16px', fontSize: '13.5px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
          Upload a resume file or paste raw text. Supported formats: <strong style={{ color: 'var(--text-primary)' }}>PDF (.pdf)</strong>, <strong style={{ color: 'var(--text-primary)' }}>Word (.docx)</strong>, <strong style={{ color: 'var(--text-primary)' }}>Plain Text (.txt)</strong>, <strong style={{ color: 'var(--text-primary)' }}>Markdown (.md)</strong>.
        </p>

        {/* File Upload Area */}
        <div
          style={{
            border: '2px dashed var(--primary-border, #bfdbfe)',
            borderRadius: '12px',
            padding: '22px 18px',
            textAlign: 'center',
            background: 'var(--primary-soft, #eff6ff)',
            marginBottom: '18px',
            transition: 'all 0.2s ease',
          }}
        >
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileUpload}
            accept=".pdf,.docx,.txt,.md"
            style={{ display: 'none' }}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadingFile}
            style={{
              background: 'var(--primary, #2563eb)',
              color: '#ffffff',
              border: 'none',
              padding: '10px 22px',
              borderRadius: '10px',
              fontSize: '13.5px',
              fontWeight: '700',
              cursor: uploadingFile ? 'wait' : 'pointer',
              marginBottom: '8px',
              boxShadow: '0 4px 14px rgba(37, 99, 235, 0.35)',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              transition: 'transform 0.15s ease, background 0.15s ease',
            }}
          >
            {uploadingFile ? '⏳ Parsing Document...' : '📎 Choose Resume File (.pdf, .docx, .txt)'}
          </button>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)', fontWeight: '500' }}>
            Max size: 5 MB. Documents are parsed securely in-memory and never silently overwrite master data.
          </div>
        </div>

        {fileError && (
          <div style={{ background: '#fee2e2', border: '1px solid #fecaca', color: '#991b1b', padding: '10px 14px', borderRadius: '8px', marginBottom: '14px', fontSize: '13px', fontWeight: '500' }}>
            ⚠️ {fileError}
          </div>
        )}

        <div style={{ fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '8px' }}>
          Or paste raw resume text:
        </div>

        <textarea
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
          rows={6}
          placeholder="Paste raw resume text here..."
          style={{
            width: '100%',
            padding: '12px',
            borderRadius: '10px',
            border: '1px solid var(--border)',
            background: 'var(--bg-card)',
            color: 'var(--text-primary)',
            boxSizing: 'border-box',
            fontSize: '13px',
            lineHeight: '1.5',
            marginBottom: '16px',
            outline: 'none',
            fontFamily: 'inherit',
          }}
        />

        {importSuccess && (
          <div style={{ background: '#dcfce7', border: '1px solid #bbf7d0', color: '#166534', padding: '10px 14px', borderRadius: '8px', marginBottom: '14px', fontSize: '13px', fontWeight: '600' }}>
            ✓ Structured resume extracted successfully! Populating review fields...
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
              padding: '9px 18px',
              borderRadius: '8px',
              fontSize: '13px',
              fontWeight: '600',
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onImport}
            disabled={!importText.trim() || importing}
            style={{
              background: (!importText.trim() || importing) ? '#94a3b8' : 'var(--primary, #2563eb)',
              color: '#ffffff',
              border: 'none',
              padding: '9px 20px',
              borderRadius: '8px',
              fontSize: '13px',
              fontWeight: '700',
              cursor: (!importText.trim() || importing) ? 'not-allowed' : 'pointer',
              boxShadow: (!importText.trim() || importing) ? 'none' : '0 4px 14px rgba(37, 99, 235, 0.3)',
            }}
          >
            {importing ? 'Extracting...' : 'Extract & Populate Review'}
          </button>
        </div>
      </div>
    </Dialog>
  )
}
