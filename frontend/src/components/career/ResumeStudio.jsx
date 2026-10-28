import React, { useState, useEffect, useCallback } from 'react'
import { FileText, GitCompare, PenLine } from 'lucide-react'
import {
  fetchMasterResume,
  updateMasterResume,
  fetchResumes,
  updateResume,
  validateResume,
  getResumeExportUrl,
  getResumeExportDocxUrl,
  parseUploadResume,
  commitExtractedResume,
  draftCoverLetter,
} from '../../api/careerApi'
import { downloadAuthedFile, openAuthedHtml } from '../../api/baseClient.js'

import ValidationReportCard from './ValidationReportCard'
import ResumeImportModal from './ResumeImportModal'
import ExtractionReviewModal from './ExtractionReviewModal'
import ExternalProfileImportModal from './ExternalProfileImportModal'

const GitHubIntelligenceModal = React.lazy(() => import('./GitHubIntelligenceModal'))

export default function ResumeStudio() {
  const [masterResume, setMasterResume] = useState(null)
  const [resumesList, setResumesList] = useState([])
  const [selectedResume, setSelectedResume] = useState(null)
  const [validationReport, setValidationReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [error, setError] = useState(null)
  const [exportingType, setExportingType] = useState(null) // 'print' | 'docx' | null
  const [exportToast, setExportToast] = useState(null) // { message: string, type: 'error' | 'success' } | null

  // Form edit states
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [location, setLocation] = useState('')
  const [summary, setSummary] = useState('')
  const [skillsText, setSkillsText] = useState('')

  // Modals & Intelligence states
  const [showImportModal, setShowImportModal] = useState(false)
  const [showExtractionModal, setShowExtractionModal] = useState(false)
  const [parseResult, setParseResult] = useState(null)
  const [committingExtraction, setCommittingExtraction] = useState(false)
  const [showGitHubModal, setShowGitHubModal] = useState(false)
  const [showExternalProfileModal, setShowExternalProfileModal] = useState(false)

  // Review & Export customization
  const [resumeTemplate, setResumeTemplate] = useState('ats_classic') // ats_classic | modern | minimal
  const [viewMode, setViewMode] = useState('editor') // 'editor' | 'diff'
  const [activeTab, setActiveTab] = useState('resume') // 'resume' | 'cover_letter'
  const [coverLetterText, setCoverLetterText] = useState('')
  const [draftingLetter, setDraftingLetter] = useState(false)
  const [importText, setImportText] = useState('')
  const [importing, setImporting] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [master, list] = await Promise.all([
        fetchMasterResume(),
        fetchResumes(),
      ])
      setMasterResume(master)
      setResumesList(list)
      setSelectedResume(master)
      populateForm(master)
      setValidationReport(master?.validation_report || null)
    } catch (err) {
      setError(err.message || 'Failed to load resumes')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  const populateForm = (res) => {
    if (!res || !res.content) return
    const c = res.content
    setFullName(c.full_name || '')
    setEmail(c.email || '')
    setPhone(c.phone || '')
    setLocation(c.location || '')
    setSummary(c.summary || '')
    setSkillsText((c.skills || []).join(', '))
    setCoverLetterText(res.cover_letter || '')
  }

  const handleSelectResume = (res) => {
    setSelectedResume(res)
    populateForm(res)
    setValidationReport(res.validation_report || null)
    setSaveSuccess(false)
    setViewMode('editor')
  }

  // Handle uploaded file or pasted text -> opens Extraction Review Screen
  const handleFileExtracted = (result) => {
    setParseResult(result)
    setShowImportModal(false)
    setShowExtractionModal(true)
  }

  const handleImportPastedText = async () => {
    if (!importText.trim()) return
    setImporting(true)
    setError(null)
    try {
      const parsed = await parseUploadResume(importText)
      const fakeResult = {
        success: true,
        filename: 'Pasted Text Document',
        file_type: '.txt',
        raw_text: importText,
        extracted_content: parsed,
        missing_fields: [],
        field_confidence: { overall: 0.85 },
      }
      setParseResult(fakeResult)
      setShowImportModal(false)
      setShowExtractionModal(true)
      setImportText('')
    } catch (err) {
      setError(err.message || 'Failed to parse resume text')
    } finally {
      setImporting(false)
    }
  }

  // Commit from Extraction Review Modal
  const handleCommitExtraction = async (editedContent, docId, target = 'master') => {
    setCommittingExtraction(true)
    setError(null)
    try {
      const saved = await commitExtractedResume(editedContent, docId, target)
      setShowExtractionModal(false)
      setSaveSuccess(true)
      await loadData()
      if (saved) {
        handleSelectResume(saved)
      }
    } catch (err) {
      setError(err.message || 'Failed to commit extracted resume data')
    } finally {
      setCommittingExtraction(false)
    }
  }

  // GitHub Intelligence imports
  const handleImportGitHubRepo = async (repo) => {
    if (!masterResume?.content) return
    try {
      const currentProjects = masterResume.content.projects || []
      const newProject = {
        title: repo.repo_name,
        description: repo.description || 'Open source software repository implementation.',
        technologies: repo.detected_technologies || [],
        project_url: repo.repo_url,
        highlights: repo.implementation_evidence || [],
        evidence_classification: 'REPOSITORY_EVIDENCE',
      }
      const updatedContent = {
        ...masterResume.content,
        projects: [newProject, ...currentProjects.filter(p => p.title !== repo.repo_name)],
      }
      const updated = await updateMasterResume(updatedContent)
      setMasterResume(updated)
      if (selectedResume?.is_master) {
        setSelectedResume(updated)
        populateForm(updated)
      }
      const list = await fetchResumes()
      setResumesList(list)
      setSaveSuccess(true)
      alert(`✓ Repository "${repo.repo_name}" imported into Master Profile projects!`)
    } catch (err) {
      setError(err.message || 'Failed to import repository')
    }
  }

  const handleImportGitHubSkills = async (skills) => {
    if (!masterResume?.content) return
    try {
      const currentSkills = new Set(masterResume.content.skills || [])
      skills.forEach(s => currentSkills.add(s))
      const updatedContent = {
        ...masterResume.content,
        skills: Array.from(currentSkills),
      }
      const updated = await updateMasterResume(updatedContent)
      setMasterResume(updated)
      if (selectedResume?.is_master) {
        setSelectedResume(updated)
        populateForm(updated)
      }
      const list = await fetchResumes()
      setResumesList(list)
      setSaveSuccess(true)
      alert(`✓ Added ${skills.length} verified technologies to Master Profile!`)
    } catch (err) {
      setError(err.message || 'Failed to import skills')
    }
  }

  const handleDraftCoverLetter = async () => {
    if (!selectedResume?.opportunity_id) return
    setDraftingLetter(true)
    setError(null)
    try {
      const res = await draftCoverLetter(selectedResume.opportunity_id)
      setCoverLetterText(res.content)
      setActiveTab('cover_letter')
    } catch (err) {
      setError(err.message || 'Failed to draft cover letter')
    } finally {
      setDraftingLetter(false)
    }
  }

  // Save handler enforcing Master Resume Immutability
  const handleSaveResume = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setSaveSuccess(false)
    try {
      const skillsArray = skillsText
        .split(',')
        .map(s => s.trim())
        .filter(Boolean)

      const updatedContent = {
        ...(selectedResume?.content || {}),
        full_name: fullName,
        email: email,
        phone: phone,
        location: location,
        summary: summary,
        skills: skillsArray,
      }

      if (selectedResume?.is_master) {
        const updated = await updateMasterResume(updatedContent)
        setMasterResume(updated)
        setSelectedResume(updated)
        if (updated?.validation_report) {
          setValidationReport(updated.validation_report)
        }
      } else if (selectedResume) {
        // Tailored variant save - strictly preserves master resume unmodified
        const updated = await updateResume(selectedResume.id, {
          title: selectedResume.title,
          content: updatedContent,
          cover_letter: coverLetterText,
        })
        setSelectedResume(updated)
        if (updated?.validation_report) {
          setValidationReport(updated.validation_report)
        }
      }

      setSaveSuccess(true)
      const list = await fetchResumes()
      setResumesList(list)
    } catch (err) {
      setError(err.message || 'Failed to update resume')
    } finally {
      setSaving(false)
    }
  }

  const handleRunValidation = async () => {
    if (!selectedResume) return
    try {
      const report = await validateResume(selectedResume.id)
      setValidationReport(report)
    } catch (err) {
      setError(err.message || 'Validation failed')
    }
  }

  const handleExportPrint = async () => {
    if (exportingType || !selectedResume?.id) return
    const nameVal = (fullName || selectedResume?.content?.full_name || '').trim()
    const emailVal = (email || selectedResume?.content?.email || '').trim()
    const isPlaceholderName = !nameVal || nameVal.toLowerCase() === 'compass candidate' || nameVal.toLowerCase() === 'candidate'
    const isPlaceholderEmail = !emailVal || emailVal.toLowerCase() === 'candidate@compass.local' || !emailVal.includes('@')
    if (isPlaceholderName || isPlaceholderEmail) {
      const missing = []
      if (isPlaceholderName) missing.push('Candidate Full Name')
      if (isPlaceholderEmail) missing.push('Candidate Email')
      setExportToast({
        message: `Please complete required profile fields with your real information before exporting: ${missing.join(', ')} (placeholder or empty data detected).`,
        type: 'error',
      })
      return
    }

    setExportingType('print')
    setExportToast(null)
    const popup = typeof window !== 'undefined' ? window.open('about:blank', '_blank') : null
    try {
      const url = getResumeExportUrl(selectedResume.id, resumeTemplate)
      await openAuthedHtml(url, { printOnLoad: true, popup })
      setExportToast({ message: 'Opened ATS-compliant printable resume for PDF export.', type: 'success' })
    } catch (err) {
      if (popup && typeof popup.close === 'function' && !popup.closed) {
        try { popup.close() } catch { /* ignore */ }
      }
      setExportToast({ message: err.message || 'Failed to prepare print preview.', type: 'error' })
    } finally {
      setExportingType(null)
    }
  }

  const handleExportDocx = async () => {
    if (exportingType || !selectedResume?.id) return
    const nameVal = (fullName || selectedResume?.content?.full_name || '').trim()
    const emailVal = (email || selectedResume?.content?.email || '').trim()
    const isPlaceholderName = !nameVal || nameVal.toLowerCase() === 'compass candidate' || nameVal.toLowerCase() === 'candidate'
    const isPlaceholderEmail = !emailVal || emailVal.toLowerCase() === 'candidate@compass.local' || !emailVal.includes('@')
    if (isPlaceholderName || isPlaceholderEmail) {
      const missing = []
      if (isPlaceholderName) missing.push('Candidate Full Name')
      if (isPlaceholderEmail) missing.push('Candidate Email')
      setExportToast({
        message: `Please complete required profile fields with your real information before exporting: ${missing.join(', ')} (placeholder or empty data detected).`,
        type: 'error',
      })
      return
    }

    setExportingType('docx')
    setExportToast(null)
    try {
      const url = getResumeExportDocxUrl(selectedResume.id)
      const fallbackName = `${(selectedResume.title || 'resume').replace(/[^\w\s-]/g, '').trim().replace(/\s+/g, '_') || 'resume'}.docx`
      const result = await downloadAuthedFile(url, fallbackName)
      setExportToast({ message: `Successfully downloaded ${result.filename || 'Word (.docx) resume'}.`, type: 'success' })
    } catch (err) {
      setExportToast({ message: err.message || 'Failed to download Word document.', type: 'error' })
    } finally {
      setExportingType(null)
    }
  }

  if (loading) {
    return (
      <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
        <div className="spinner" style={{ margin: '0 auto 12px' }} />
        <p>Loading Evidence-Based Resume Studio...</p>
      </div>
    )
  }

  // Diff comparison data
  const isTailored = selectedResume && !selectedResume.is_master
  const diffSummary = selectedResume?.validation_report?.diff_summary || {}

  return (
    <div style={{ padding: '0 8px 36px', maxWidth: '1240px', margin: '0 auto' }}>
      {/* Header Bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px', marginBottom: '22px' }}>
        <div>
          <h2 style={{ margin: '0 0 6px', fontSize: '22px', fontWeight: '800', color: 'var(--text-primary)', letterSpacing: '-0.02em' }}>
            📄 Evidence-Based Resume Studio
          </h2>
          <p style={{ margin: 0, fontSize: '13.5px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
            Anchor your master career profile to verified evidence and generate tailored ATS resumes without qualification hallucination.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          <button
            type="button"
            onClick={() => setShowImportModal(true)}
            style={{
              background: 'var(--primary, #2563eb)',
              border: 'none',
              color: '#ffffff',
              padding: '9px 16px',
              borderRadius: '9px',
              fontSize: '13px',
              fontWeight: '700',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              boxShadow: '0 4px 12px rgba(37, 99, 235, 0.3)',
              transition: 'transform 0.15s ease, background 0.15s ease',
            }}
          >
            📥 Import Resume (.pdf / .docx)
          </button>
          <button
            type="button"
            onClick={() => setShowGitHubModal(true)}
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
              padding: '9px 15px',
              borderRadius: '9px',
              fontSize: '13px',
              fontWeight: '600',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              boxShadow: '0 1px 3px rgba(15, 23, 42, 0.05)',
            }}
          >
            🐙 GitHub Intelligence
          </button>
          <button
            type="button"
            onClick={() => setShowExternalProfileModal(true)}
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
              padding: '9px 15px',
              borderRadius: '9px',
              fontSize: '13px',
              fontWeight: '600',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              boxShadow: '0 1px 3px rgba(15, 23, 42, 0.05)',
            }}
          >
            🔗 LinkedIn / External
          </button>
        </div>
      </div>

      {error && (
        <div style={{ background: '#fee2e2', color: '#991b1b', padding: '12px 16px', borderRadius: '8px', marginBottom: '16px', fontSize: '13px' }}>
          ⚠️ {error}
        </div>
      )}

      {saveSuccess && (
        <div style={{ background: '#dcfce7', color: '#166534', padding: '12px 16px', borderRadius: '8px', marginBottom: '16px', fontSize: '13px' }}>
          ✅ Resume changes successfully saved and factually anchored!
        </div>
      )}

      {exportToast && (
        <div
          role="alert"
          style={{
            background: exportToast.type === 'error' ? '#fee2e2' : '#dcfce7',
            border: `1px solid ${exportToast.type === 'error' ? '#fca5a5' : '#86efac'}`,
            color: exportToast.type === 'error' ? '#991b1b' : '#166534',
            padding: '12px 16px',
            borderRadius: '8px',
            marginBottom: '16px',
            fontSize: '13px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '8px',
          }}
        >
          <span>{exportToast.type === 'error' ? '⚠️ ' : '✅ '}{exportToast.message}</span>
          <button
            type="button"
            onClick={() => setExportToast(null)}
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'inherit',
              fontWeight: '700',
              padding: '0 4px',
              fontSize: '14px',
            }}
          >
            ✕
          </button>
        </div>
      )}

      {/* Main Grid: Left sidebar versions / validation card, Right editor / diff */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '24px', alignItems: 'start' }}>
        {/* Left Column: Versions & Integrity Card */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
          {/* Versions Selector */}
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '12px', padding: '18px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: 'var(--text-primary)' }}>
                Resume Versions ({resumesList.length})
              </h3>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '250px', overflowY: 'auto' }}>
              {resumesList.map((res) => {
                const isSelected = selectedResume?.id === res.id
                return (
                  <button
                    key={res.id}
                    type="button"
                    onClick={() => handleSelectResume(res)}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '11px 13px',
                      borderRadius: '10px',
                      border: isSelected ? '2px solid var(--primary, #2563eb)' : '1px solid var(--border)',
                      background: isSelected ? 'var(--primary-soft, #eff6ff)' : 'var(--bg-card)',
                      cursor: 'pointer',
                      textAlign: 'left',
                      transition: 'all 0.15s ease',
                      boxShadow: isSelected ? '0 2px 8px rgba(37, 99, 235, 0.15)' : 'none',
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: '700', fontSize: '13.5px', color: 'var(--text-primary)' }}>
                        {res.title}
                      </div>
                      <div style={{ fontSize: '11.5px', color: isSelected ? 'var(--primary, #2563eb)' : 'var(--text-secondary)', fontWeight: isSelected ? '600' : '400', marginTop: '2px' }}>
                        {res.is_master ? '★ Master Source of Truth' : `v${res.version} Tailored`}
                      </div>
                    </div>
                    <span
                      style={{
                        fontSize: '11px',
                        padding: '3px 8px',
                        borderRadius: '12px',
                        fontWeight: '700',
                        background: res.validation_status === 'APPROVED' ? '#dcfce7' : '#fef3c7',
                        color: res.validation_status === 'APPROVED' ? '#166534' : '#92400e',
                      }}
                    >
                      {res.validation_status}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Validation Report Card */}
          <ValidationReportCard validationReport={validationReport} />
        </div>

        {/* Right Column: Editor / Diff Viewer */}
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '14px', padding: '26px', boxShadow: 'var(--shadow-sm)' }}>
          {/* Header & Mode Switcher */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px', marginBottom: '18px' }}>
            <div>
              <h3 style={{ margin: 0, fontSize: '17px', fontWeight: '800', color: 'var(--text-primary)' }}>
                {selectedResume?.is_master ? 'Master Profile Information' : selectedResume?.title}
              </h3>
              {isTailored && (
                <span style={{ fontSize: '11.5px', color: 'var(--primary, #2563eb)', background: 'var(--primary-soft, #eff6ff)', padding: '3px 10px', borderRadius: '6px', fontWeight: '600', display: 'inline-block', marginTop: '4px' }}>
                  Tailored Variant (Master Profile is Immutable)
                </span>
              )}
            </div>

            {/* Template Selector & Export Dropdowns */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <select
                value={resumeTemplate}
                onChange={(e) => setResumeTemplate(e.target.value)}
                style={{ padding: '7px 12px', borderRadius: '8px', border: '1px solid var(--border)', fontSize: '12.5px', background: 'var(--bg-card)', color: 'var(--text-primary)', fontWeight: '500' }}
              >
                <option value="ats_classic">ATS Classic</option>
                <option value="modern">Modern Clean</option>
                <option value="minimal">Minimalist</option>
              </select>

              {selectedResume && (
                <>
                  <button
                    type="button"
                    id="btn-print-pdf"
                    disabled={Boolean(exportingType)}
                    onClick={handleExportPrint}
                    style={{
                      background: 'var(--primary, #2563eb)',
                      color: '#ffffff',
                      padding: '7px 14px',
                      borderRadius: '8px',
                      fontSize: '12.5px',
                      fontWeight: '700',
                      border: 'none',
                      cursor: exportingType ? 'not-allowed' : 'pointer',
                      opacity: exportingType ? 0.7 : 1,
                      boxShadow: '0 2px 8px rgba(37, 99, 235, 0.25)',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '6px',
                    }}
                  >
                    {exportingType === 'print' ? '⏳ Generating PDF…' : '📄 Print / PDF'}
                  </button>
                  <button
                    type="button"
                    id="btn-export-docx"
                    disabled={Boolean(exportingType)}
                    onClick={handleExportDocx}
                    style={{
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      color: 'var(--text-primary)',
                      padding: '7px 14px',
                      borderRadius: '8px',
                      fontSize: '12.5px',
                      fontWeight: '700',
                      cursor: exportingType ? 'not-allowed' : 'pointer',
                      opacity: exportingType ? 0.7 : 1,
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '6px',
                    }}
                  >
                    {exportingType === 'docx' ? '⏳ Preparing Word…' : '📝 Word (.docx)'}
                  </button>
                </>
              )}
            </div>
          </div>

          {/* Sub-tabs: Resume Profile vs Cover Letter vs Diff */}
          <div
            role="tablist"
            aria-label="Resume sections"
            className="unified-tablist"
            style={{
              borderBottom: '1px solid var(--border)',
              marginBottom: '18px',
              paddingLeft: 0,
              paddingRight: 0,
            }}
          >
            <button
              id="resume-tab-editor"
              role="tab"
              aria-selected={activeTab === 'resume' && viewMode === 'editor'}
              tabIndex={activeTab === 'resume' && viewMode === 'editor' ? 0 : -1}
              type="button"
              onClick={() => { setActiveTab('resume'); setViewMode('editor'); }}
              className={`unified-tab ${activeTab === 'resume' && viewMode === 'editor' ? 'active' : ''}`}
            >
              <span className="unified-tab-icon" aria-hidden="true">
                <FileText size={14} strokeWidth={1.8} />
              </span>
              <span>Resume Editor</span>
            </button>

            {isTailored && (
              <button
                id="resume-tab-diff"
                role="tab"
                aria-selected={viewMode === 'diff'}
                tabIndex={viewMode === 'diff' ? 0 : -1}
                type="button"
                onClick={() => setViewMode('diff')}
                className={`unified-tab ${viewMode === 'diff' ? 'active' : ''}`}
              >
                <span className="unified-tab-icon" aria-hidden="true">
                  <GitCompare size={14} strokeWidth={1.8} />
                </span>
                <span>Master vs Tailored Diff</span>
              </button>
            )}

            <button
              id="resume-tab-cover-letter"
              role="tab"
              aria-selected={activeTab === 'cover_letter' && viewMode === 'editor'}
              tabIndex={activeTab === 'cover_letter' && viewMode === 'editor' ? 0 : -1}
              type="button"
              onClick={() => { setActiveTab('cover_letter'); setViewMode('editor'); }}
              className={`unified-tab ${activeTab === 'cover_letter' && viewMode === 'editor' ? 'active' : ''}`}
            >
              <span className="unified-tab-icon" aria-hidden="true">
                <PenLine size={14} strokeWidth={1.8} />
              </span>
              <span>Truthful Cover Letter</span>
            </button>
          </div>

          {/* Body Content */}
          {viewMode === 'diff' && isTailored ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ background: 'var(--bg-card-soft)', padding: '16px', borderRadius: '10px', border: '1px solid var(--border)' }}>
                <h4 style={{ margin: '0 0 10px', fontSize: '13.5px', fontWeight: '800', color: 'var(--text-primary)' }}>Skills Alignment Breakdown</h4>
                <div style={{ marginBottom: '10px' }}>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)', fontWeight: '600', marginBottom: '6px' }}>🎯 Emphasized & Re-ordered for Opportunity:</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    {(diffSummary.highlighted_skills || []).map((s, idx) => (
                      <span key={idx} style={{ background: '#dcfce7', color: '#166534', padding: '4px 10px', borderRadius: '6px', fontSize: '12px', fontWeight: '600' }}>
                        ✓ {s}
                      </span>
                    ))}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)', fontWeight: '600', marginBottom: '6px' }}>💤 Deprioritized / Omitted Master Skills (not required by role):</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    {(diffSummary.omitted_master_skills || []).map((s, idx) => (
                      <span key={idx} style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-secondary)', padding: '3px 8px', borderRadius: '6px', fontSize: '12px' }}>
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              <div style={{ background: 'var(--bg-card-soft)', padding: '16px', borderRadius: '10px', border: '1px solid var(--border)' }}>
                <h4 style={{ margin: '0 0 10px', fontSize: '13.5px', fontWeight: '800', color: 'var(--text-primary)' }}>Targeted Project Relevance Order</h4>
                <ol style={{ margin: 0, paddingLeft: '20px', fontSize: '13px', color: 'var(--text-primary)' }}>
                  {(diffSummary.project_order || []).map((pTitle, idx) => (
                    <li key={idx} style={{ marginBottom: '6px' }}>
                      <strong>{pTitle}</strong>
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          ) : activeTab === 'resume' ? (
            <form onSubmit={handleSaveResume} style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '14px' }}>
                <div>
                  <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '6px' }}>
                    <span>Full Name</span>
                    {fullName.trim().toLowerCase() === 'compass candidate' && (
                      <span style={{ fontSize: '11px', color: '#b45309', background: '#fef3c7', padding: '2px 8px', borderRadius: '4px', fontWeight: '600' }}>
                        ⚠️ Placeholder, please replace
                      </span>
                    )}
                  </label>
                  <input
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    required
                    style={{ width: '100%', padding: '10px 14px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '6px' }}>
                    <span>Contact Email</span>
                    {email.trim().toLowerCase() === 'candidate@compass.local' && (
                      <span style={{ fontSize: '11px', color: '#b45309', background: '#fef3c7', padding: '2px 8px', borderRadius: '4px', fontWeight: '600' }}>
                        ⚠️ Placeholder, please replace
                      </span>
                    )}
                  </label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    style={{ width: '100%', padding: '10px 14px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px' }}
                  />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '14px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '6px' }}>Phone</label>
                  <input
                    type="text"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    placeholder="+91 98765 43210"
                    style={{ width: '100%', padding: '10px 14px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '6px' }}>Location</label>
                  <input
                    type="text"
                    value={location}
                    onChange={(e) => setLocation(e.target.value)}
                    placeholder="Bangalore, India"
                    style={{ width: '100%', padding: '10px 14px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px' }}
                  />
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '6px' }}>Summary</label>
                <textarea
                  value={summary}
                  onChange={(e) => setSummary(e.target.value)}
                  rows={3}
                  style={{ width: '100%', padding: '10px 14px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px', lineHeight: 1.5 }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '6px' }}>
                  Technical Skills (comma-separated, verified against factual grounding)
                </label>
                <textarea
                  value={skillsText}
                  onChange={(e) => setSkillsText(e.target.value)}
                  rows={2}
                  style={{ width: '100%', padding: '10px 14px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px', lineHeight: 1.5 }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '14px' }}>
                <button
                  type="button"
                  onClick={handleRunValidation}
                  style={{
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    padding: '9px 16px',
                    borderRadius: '8px',
                    fontSize: '13px',
                    fontWeight: '600',
                    color: 'var(--text-primary)',
                    cursor: 'pointer',
                    boxShadow: '0 1px 2px rgba(15, 23, 42, 0.05)',
                  }}
                >
                  🔍 Verify Factual Claims
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  style={{
                    background: 'var(--primary, #2563eb)',
                    color: '#ffffff',
                    border: 'none',
                    padding: '10px 24px',
                    borderRadius: '8px',
                    fontSize: '14px',
                    fontWeight: '700',
                    cursor: saving ? 'not-allowed' : 'pointer',
                    boxShadow: '0 4px 14px rgba(37, 99, 235, 0.35)',
                    transition: 'all 0.15s ease',
                  }}
                >
                  {saving ? 'Saving...' : (selectedResume?.is_master ? 'Save Master Anchor' : 'Save Tailored Resume')}
                </button>
              </div>
            </form>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                <div style={{ fontSize: '13.5px', color: 'var(--text-secondary)', fontWeight: '500' }}>
                  Grounded strictly in verified master projects and skills.
                </div>
                {selectedResume?.opportunity_id && (
                  <button
                    type="button"
                    onClick={handleDraftCoverLetter}
                    disabled={draftingLetter}
                    style={{
                      background: 'var(--primary, #2563eb)',
                      color: '#ffffff',
                      border: 'none',
                      padding: '8px 16px',
                      borderRadius: '8px',
                      fontSize: '12.5px',
                      fontWeight: '700',
                      cursor: draftingLetter ? 'not-allowed' : 'pointer',
                      boxShadow: '0 4px 12px rgba(37, 99, 235, 0.3)',
                    }}
                  >
                    {draftingLetter ? 'Drafting...' : '✨ Generate Truthful Cover Letter'}
                  </button>
                )}
              </div>

              <textarea
                value={coverLetterText}
                onChange={(e) => setCoverLetterText(e.target.value)}
                rows={12}
                placeholder="No cover letter drafted yet. Click 'Generate Truthful Cover Letter'..."
                style={{
                  width: '100%',
                  padding: '12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-card-soft)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  lineHeight: '1.6',
                  fontFamily: 'monospace',
                }}
              />

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
                <button
                  type="button"
                  onClick={() => {
                    navigator.clipboard?.writeText(coverLetterText)
                    alert('Cover letter copied to clipboard!')
                  }}
                  style={{
                    background: 'var(--bg-card-soft)',
                    border: '1px solid var(--border)',
                    padding: '8px 16px',
                    borderRadius: '8px',
                    fontSize: '13px',
                    cursor: 'pointer',
                  }}
                >
                  📋 Copy to Clipboard
                </button>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={saving}
                  style={{
                    background: 'var(--primary, #2563eb)',
                    color: '#ffffff',
                    border: 'none',
                    padding: '8px 16px',
                    borderRadius: '8px',
                    fontSize: '13px',
                    fontWeight: '700',
                    cursor: saving ? 'not-allowed' : 'pointer',
                  }}
                >
                  {saving ? 'Saving...' : '💾 Save Cover Letter'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Modals */}
      <ResumeImportModal
        show={showImportModal}
        isOpen={showImportModal}
        onClose={() => setShowImportModal(false)}
        importText={importText}
        setImportText={setImportText}
        onImport={handleImportPastedText}
        importing={importing}
        onFileExtracted={handleFileExtracted}
      />

      <ExtractionReviewModal
        show={showExtractionModal}
        onClose={() => setShowExtractionModal(false)}
        parseResult={parseResult}
        onCommit={handleCommitExtraction}
        committing={committingExtraction}
      />

      {showGitHubModal && (
        <React.Suspense fallback={null}>
          <GitHubIntelligenceModal
            show={showGitHubModal}
            onClose={() => setShowGitHubModal(false)}
            onImportRepoToMaster={handleImportGitHubRepo}
            onImportSkillsToMaster={handleImportGitHubSkills}
          />
        </React.Suspense>
      )}

      <ExternalProfileImportModal
        show={showExternalProfileModal}
        onClose={() => setShowExternalProfileModal(false)}
        onProfileIngested={(content, source) => {
          setParseResult({
            success: true,
            filename: `External Source (${source})`,
            file_type: 'profile_import',
            extracted_content: content,
            missing_fields: [],
            field_confidence: { overall: 0.9 },
          })
          setShowExtractionModal(true)
        }}
      />
    </div>
  )
}
