import React, { useState, useEffect } from 'react'
import { resolveOverallConfidence, computeMissingFields } from '../../utils/careerUiHelpers'
import Dialog from '../Dialog'

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const FULL_MONTHS = { january: 'Jan', february: 'Feb', march: 'Mar', april: 'Apr', may: 'May', june: 'Jun', july: 'Jul', august: 'Aug', september: 'Sep', october: 'Oct', november: 'Nov', december: 'Dec' }

function resolveParsedGradMonth(edu, idx, evidenceNotes) {
  const candidate = edu?.grad_month || edu?.graduation_month || edu?.end_month ||
    evidenceNotes?.[`grad_month_${idx + 1}`] || evidenceNotes?.[`grad_month_${idx}`] || evidenceNotes?.[`education_month_${idx + 1}`] || null
  if (!candidate) return ''
  const str = String(candidate).trim(), num = parseInt(str, 10)
  if (!isNaN(num) && num >= 1 && num <= 12) return MONTH_NAMES[num - 1]
  const lower = str.toLowerCase()
  if (FULL_MONTHS[lower]) return FULL_MONTHS[lower]
  const matched = MONTH_NAMES.find(m => m.toLowerCase() === str.slice(0, 3).toLowerCase())
  return matched || str
}

export default function ExtractionReviewModal({
  show,
  onClose,
  parseResult,
  onCommit,
  committing = false,
}) {
  const [content, setContent] = useState(null)
  const [activeTab, setActiveTab] = useState('contact') // contact | skills | education | projects | additional
  const [skillsText, setSkillsText] = useState('')
  const [awardsText, setAwardsText] = useState('')
  const [certificationsText, setCertificationsText] = useState('')

  useEffect(() => {
    if (parseResult?.extracted_content) {
      const extracted = JSON.parse(JSON.stringify(parseResult.extracted_content))
      setContent(extracted)
      setSkillsText((extracted.skills || []).join(', '))
      setAwardsText((extracted.awards || []).join('\n'))
      setCertificationsText((extracted.certifications || []).join('\n'))
    }
  }, [parseResult])

  if (!show || !content) return null

  const diag = parseResult || {}
  const missing = Array.isArray(diag.missing_fields) ? diag.missing_fields : computeMissingFields(content)
  const ambiguous = diag.ambiguous_fields || []
  const conflicts = diag.field_conflicts || []
  const confidence = resolveOverallConfidence(diag)
  // External profile imports (LinkedIn / portfolio) must never replace the master by accident.
  const preferDraft = diag.file_type === 'profile_import'

  const handleSkillsBlur = () => {
    setContent(prev => ({
      ...prev,
      skills: skillsText.split(',').map((s) => s.trim()).filter(Boolean),
    }))
  }

  const handleAwardsBlur = () => {
    setContent(prev => ({
      ...prev,
      awards: awardsText.split('\n').map((s) => s.trim()).filter(Boolean),
    }))
  }

  const handleCertificationsBlur = () => {
    setContent(prev => ({
      ...prev,
      certifications: certificationsText.split('\n').map((s) => s.trim()).filter(Boolean),
    }))
  }

  const handleCommit = (target = 'master') => {
    if (onCommit) {
      // Backend ResumeEducationItem (backend/models_career.py) schema does not have a grad_month field.
      // Omit grad_month from education items in commit payload to strictly conform to backend model.
      const sanitizedEducation = (content.education || []).map(edu => ({
        institution: edu.institution || '',
        degree: edu.degree || '',
        field_of_study: edu.field_of_study || null,
        start_year: edu.start_year ?? null,
        end_year: edu.end_year ?? null,
        cgpa_or_grade: edu.cgpa_or_grade || null,
        ...(edu.evidence_classification ? { evidence_classification: edu.evidence_classification } : {}),
      }))

      const finalContent = {
        ...content,
        education: sanitizedEducation,
        skills: skillsText.split(',').map((s) => s.trim()).filter(Boolean),
        awards: awardsText.split('\n').map((s) => s.trim()).filter(Boolean),
        ...(content.certifications !== undefined
          ? { certifications: certificationsText.split('\n').map((s) => s.trim()).filter(Boolean) }
          : {}),
      }
      onCommit(finalContent, diag.original_document_id, target)
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
        zIndex: 1100,
        padding: '20px',
      }}
    >
      <div
        style={{
          background: 'var(--bg-card, #ffffff)',
          border: '1px solid var(--border, #e2e8f0)',
          borderRadius: '18px',
          maxWidth: '840px',
          width: '100%',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 25px 50px -12px rgba(15, 23, 42, 0.25)',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '20px 26px',
            borderBottom: '1px solid var(--border, #e2e8f0)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: 'var(--bg-card-soft, #f8fafc)',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <h3 style={{ margin: 0, fontSize: '18px', fontWeight: '800', color: 'var(--text-primary, #0f172a)' }}>
                🔍 Review Extracted Resume Data
              </h3>
              {confidence !== null && (
                <span
                  style={{
                    fontSize: '11.5px',
                    fontWeight: '700',
                    padding: '3px 9px',
                    borderRadius: '12px',
                    background: confidence >= 0.8 ? '#dcfce7' : '#fef9c3',
                    color: confidence >= 0.8 ? '#166534' : '#854d0e',
                  }}
                >
                  {Math.round(confidence * 100)}% Confidence
                </span>
              )}
            </div>
            <p style={{ margin: '4px 0 0', fontSize: '13px', color: 'var(--text-secondary, #334155)' }}>
              Source: <strong style={{ color: 'var(--text-primary)' }}>{diag.filename || 'Uploaded Document'}</strong> ({diag.file_type || 'file'}). Please verify accuracy before committing.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              width: '32px',
              height: '32px',
              borderRadius: '8px',
              fontSize: '16px',
              color: 'var(--text-secondary, #334155)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            ✕
          </button>
        </div>

        {/* Diagnostics Alerts */}
        {(missing.length > 0 || conflicts.length > 0 || ambiguous.length > 0) && (
          <div style={{ padding: '12px 26px', background: '#fffbeb', borderBottom: '1px solid #fef3c7' }}>
            {missing.length > 0 && (
              <div style={{ fontSize: '12.5px', color: '#92400e', marginBottom: conflicts.length ? '4px' : '0', fontWeight: '500' }}>
                ⚠️ <strong>Missing Fields:</strong> {missing.join(', ')}: you can complete these below.
              </div>
            )}
            {conflicts.map((conf, idx) => (
              <div key={idx} style={{ fontSize: '12.5px', color: '#92400e', fontWeight: '500' }}>
                ⚡ <strong>Conflict:</strong> {conf.message} (Selected: {conf.selected})
              </div>
            ))}
            {ambiguous.map((amb, idx) => (
              <div key={idx} style={{ fontSize: '12.5px', color: '#78350f', fontWeight: '500' }}>
                ℹ️ {amb}
              </div>
            ))}
          </div>
        )}

        {/* Navigation Tabs */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border, #e2e8f0)', padding: '0 26px', background: 'var(--bg-card, #ffffff)' }}>
          {[
            { id: 'contact', label: '👤 Contact & Summary' },
            { id: 'skills', label: '🛠️ Technical Skills' },
            { id: 'education', label: '🎓 Education' },
            { id: 'projects', label: '💻 Projects & Internships' },
            { id: 'additional', label: '🏆 Honors & Links' },
          ].map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              style={{
                padding: '13px 16px',
                fontSize: '13px',
                fontWeight: activeTab === tab.id ? '700' : '600',
                color: activeTab === tab.id ? 'var(--primary, #2563eb)' : 'var(--text-secondary, #334155)',
                border: 'none',
                background: 'transparent',
                borderBottom: activeTab === tab.id ? '2px solid var(--primary, #2563eb)' : '2px solid transparent',
                cursor: 'pointer',
                transition: 'color 0.15s ease',
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab Body */}
        <div style={{ padding: '20px 24px', overflowY: 'auto', flex: 1 }}>
          {activeTab === 'contact' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '5px' }}>Full Name</label>
                <input
                  type="text"
                  value={content.full_name || ''}
                  onChange={(e) => setContent({ ...content, full_name: e.target.value })}
                  style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '5px' }}>Email Address</label>
                <input
                  type="email"
                  value={content.email || ''}
                  onChange={(e) => setContent({ ...content, email: e.target.value })}
                  style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '5px' }}>Phone Number</label>
                <input
                  type="text"
                  value={content.phone || ''}
                  onChange={(e) => setContent({ ...content, phone: e.target.value })}
                  style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '5px' }}>Location</label>
                <input
                  type="text"
                  value={content.location || ''}
                  onChange={(e) => setContent({ ...content, location: e.target.value })}
                  style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '5px' }}>GitHub / Portfolio</label>
                <input
                  type="text"
                  value={content.github_or_portfolio || ''}
                  onChange={(e) => setContent({ ...content, github_or_portfolio: e.target.value })}
                  style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '5px' }}>LinkedIn Profile</label>
                <input
                  type="text"
                  value={content.linkedin_url || ''}
                  onChange={(e) => setContent({ ...content, linkedin_url: e.target.value })}
                  style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px' }}
                />
              </div>
              <div style={{ gridColumn: '1 / -1' }}>
                <label style={{ display: 'block', fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '5px' }}>Professional Summary</label>
                <textarea
                  value={content.summary || ''}
                  onChange={(e) => setContent({ ...content, summary: e.target.value })}
                  rows={3}
                  style={{ width: '100%', padding: '10px 12px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px', lineHeight: 1.5 }}
                />
              </div>
            </div>
          )}

          {activeTab === 'skills' && (
            <div>
              <label style={{ display: 'block', fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '6px' }}>
                Technical Skills (comma-separated)
              </label>
              <textarea
                value={skillsText}
                onChange={(e) => setSkillsText(e.target.value)}
                onBlur={handleSkillsBlur}
                rows={5}
                style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid var(--border)' }}
              />
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '12px' }}>
                {(skillsText ? skillsText.split(',').map((s) => s.trim()).filter(Boolean) : (content.skills || [])).map((s, idx) => (
                  <span
                    key={idx}
                    style={{
                      background: 'var(--bg-card-soft, #f1f5f9)',
                      padding: '4px 8px',
                      borderRadius: '6px',
                      fontSize: '12px',
                      border: '1px solid var(--border)',
                    }}
                  >
                    ✓ {s}
                  </span>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'education' && (
            <div>
              {(content.education || []).map((edu, idx) => {
                const parsedMonth = resolveParsedGradMonth(edu, idx, content.evidence_notes || diag.evidence_notes)
                const currentMonth = edu.grad_month !== undefined ? edu.grad_month : parsedMonth

                return (
                  <div key={idx} style={{ background: 'var(--bg-card-soft)', padding: '12px', borderRadius: '8px', marginBottom: '10px', border: '1px solid var(--border)' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '10px' }}>
                      <div>
                        <label htmlFor={`edu-inst-${idx}`} style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Institution</label>
                        <input
                          id={`edu-inst-${idx}`}
                          type="text"
                          value={edu.institution || ''}
                          onChange={(e) => {
                            const updated = [...content.education]
                            updated[idx] = { ...updated[idx], institution: e.target.value }
                            setContent({ ...content, education: updated })
                          }}
                          style={{ width: '100%', padding: '6px 8px', borderRadius: '6px', border: '1px solid var(--border)' }}
                        />
                      </div>
                      <div>
                        <label htmlFor={`edu-degree-${idx}`} style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Degree</label>
                        <input
                          id={`edu-degree-${idx}`}
                          type="text"
                          value={edu.degree || ''}
                          placeholder="e.g. B.Tech / B.S."
                          onChange={(e) => {
                            const updated = [...content.education]
                            updated[idx] = { ...updated[idx], degree: e.target.value }
                            setContent({ ...content, education: updated })
                          }}
                          style={{ width: '100%', padding: '6px 8px', borderRadius: '6px', border: '1px solid var(--border)' }}
                        />
                      </div>
                      <div>
                        <label htmlFor={`edu-field-${idx}`} style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Field of study</label>
                        <input
                          id={`edu-field-${idx}`}
                          type="text"
                          value={edu.field_of_study || ''}
                          placeholder="e.g. Computer Science"
                          onChange={(e) => {
                            const updated = [...content.education]
                            updated[idx] = { ...updated[idx], field_of_study: e.target.value }
                            setContent({ ...content, education: updated })
                          }}
                          style={{ width: '100%', padding: '6px 8px', borderRadius: '6px', border: '1px solid var(--border)' }}
                        />
                      </div>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '10px', marginTop: '10px' }}>
                      <div>
                        <label htmlFor={`edu-start-${idx}`} style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Start year</label>
                        <input
                          id={`edu-start-${idx}`}
                          type="number"
                          value={edu.start_year ?? ''}
                          onChange={(e) => {
                            const updated = [...content.education]
                            updated[idx] = { ...updated[idx], start_year: e.target.value === '' ? null : Number(e.target.value) }
                            setContent({ ...content, education: updated })
                          }}
                          style={{ width: '100%', padding: '6px 8px', borderRadius: '6px', border: '1px solid var(--border)' }}
                        />
                      </div>
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '2px' }}>
                          <label htmlFor={`edu-end-${idx}`} style={{ fontSize: '11px', color: 'var(--text-muted)' }}>End (graduation) year</label>
                          {parsedMonth && (
                            <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>
                              Parsed: {parsedMonth}
                            </span>
                          )}
                        </div>
                        <input
                          id={`edu-end-${idx}`}
                          type="number"
                          value={edu.end_year ?? ''}
                          onChange={(e) => {
                            const updated = [...content.education]
                            updated[idx] = { ...updated[idx], end_year: e.target.value === '' ? null : Number(e.target.value) }
                            setContent({ ...content, education: updated })
                          }}
                          style={{ width: '100%', padding: '6px 8px', borderRadius: '6px', border: '1px solid var(--border)' }}
                        />
                      </div>
                      <div>
                        <label htmlFor={`edu-grad-month-${idx}`} style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Graduation month</label>
                        <select
                          id={`edu-grad-month-${idx}`}
                          value={currentMonth || ''}
                          onChange={(e) => {
                            const updated = [...content.education]
                            updated[idx] = { ...updated[idx], grad_month: e.target.value }
                            setContent({ ...content, education: updated })
                          }}
                          style={{ width: '100%', padding: '6px 8px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px' }}
                        >
                          <option value="">--</option>
                          {MONTH_NAMES.map((m) => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label htmlFor={`edu-grade-${idx}`} style={{ fontSize: '11px', color: 'var(--text-muted)' }}>CGPA / grade</label>
                        <input
                          id={`edu-grade-${idx}`}
                          type="text"
                          value={edu.cgpa_or_grade || ''}
                          placeholder="e.g. 8.4/10"
                          onChange={(e) => {
                            const updated = [...content.education]
                            updated[idx] = { ...updated[idx], cgpa_or_grade: e.target.value }
                            setContent({ ...content, education: updated })
                          }}
                          style={{ width: '100%', padding: '6px 8px', borderRadius: '6px', border: '1px solid var(--border)' }}
                        />
                      </div>
                    </div>
                    {content.evidence_notes?.[`education_note_${idx + 1}`] && (
                      <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--text-secondary)' }}>
                        Note from your resume: {content.evidence_notes[`education_note_${idx + 1}`]}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          {activeTab === 'projects' && (
            <div>
              <h4 style={{ margin: '0 0 10px', fontSize: '13px', color: 'var(--text-muted)' }}>Extracted Technical Projects</h4>
              {(content.projects || []).map((proj, idx) => (
                <div key={idx} style={{ background: 'var(--bg-card-soft)', padding: '12px', borderRadius: '8px', marginBottom: '10px', border: '1px solid var(--border)' }}>
                  <input
                    type="text"
                    value={proj.title || ''}
                    placeholder="Project Title"
                    onChange={(e) => {
                      const updated = [...content.projects]
                      updated[idx].title = e.target.value
                      setContent({ ...content, projects: updated })
                    }}
                    style={{ fontWeight: '700', width: '100%', padding: '6px 8px', borderRadius: '6px', border: '1px solid var(--border)', marginBottom: '6px' }}
                  />
                  <textarea
                    value={proj.description || ''}
                    placeholder="Project Description"
                    onChange={(e) => {
                      const updated = [...content.projects]
                      updated[idx].description = e.target.value
                      setContent({ ...content, projects: updated })
                    }}
                    rows={2}
                    style={{ width: '100%', padding: '6px 8px', borderRadius: '6px', border: '1px solid var(--border)', marginBottom: proj.technologies?.length ? '6px' : '0' }}
                  />
                  {proj.technologies && proj.technologies.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '4px' }}>
                      <span style={{ fontSize: '11px', fontWeight: '700', color: 'var(--text-muted)', marginRight: '4px' }}>Tech:</span>
                      {proj.technologies.map((t, tIdx) => (
                        <span key={tIdx} style={{ fontSize: '11px', background: 'var(--bg-card)', padding: '2px 6px', borderRadius: '4px', border: '1px solid var(--border)' }}>
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}

              {((content.experience && content.experience.length > 0) || (content.internships && content.internships.length > 0)) && (
                <div style={{ marginTop: '20px' }}>
                  <h4 style={{ margin: '0 0 10px', fontSize: '13px', color: 'var(--text-muted)' }}>Extracted Experience & Internships</h4>
                  {[...(content.experience || []), ...(content.internships || [])].map((exp, idx) => {
                    const expCount = (content.experience || []).length
                    const isInternship = idx >= expCount
                    const itemIdx = isInternship ? idx - expCount : idx

                    return (
                      <div key={idx} style={{ background: 'var(--bg-card-soft)', padding: '12px', borderRadius: '8px', marginBottom: '8px', border: '1px solid var(--border)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                          <span style={{ fontWeight: '700', fontSize: '13px', color: 'var(--text-primary)' }}>
                            {exp.role_title ? `${exp.role_title} · ${exp.company}` : exp.company}
                          </span>
                          {(exp.start_date || exp.end_date) && (
                            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                              {exp.start_date || ''} {exp.end_date ? `– ${exp.end_date}` : ''}
                            </span>
                          )}
                        </div>
                        <div style={{ margin: '6px 0 4px' }}>
                          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--text-secondary)', cursor: 'pointer' }}>
                            <input
                              type="checkbox"
                              checked={Boolean(exp.is_current)}
                              onChange={(e) => {
                                if (isInternship) {
                                  const updated = [...(content.internships || [])]
                                  updated[itemIdx] = { ...updated[itemIdx], is_current: e.target.checked }
                                  setContent({ ...content, internships: updated })
                                } else {
                                  const updated = [...(content.experience || [])]
                                  updated[itemIdx] = { ...updated[itemIdx], is_current: e.target.checked }
                                  setContent({ ...content, experience: updated })
                                }
                              }}
                            />
                            Currently working here
                          </label>
                        </div>
                        {exp.highlights && exp.highlights.length > 0 && (
                          <ul style={{ margin: '4px 0 0', paddingLeft: '18px', fontSize: '12px', color: 'var(--text-secondary)' }}>
                            {exp.highlights.map((h, hIdx) => (
                              <li key={hIdx} style={{ marginBottom: '3px', lineHeight: '1.4' }}>{h}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}

          {activeTab === 'additional' && (
            <div>
              <div style={{ marginBottom: '14px' }}>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: '700', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Awards & Achievements
                </label>
                <textarea
                  value={awardsText}
                  onChange={(e) => setAwardsText(e.target.value)}
                  onBlur={handleAwardsBlur}
                  rows={3}
                  style={{ width: '100%', padding: '8px', borderRadius: '8px', border: '1px solid var(--border)' }}
                />
              </div>
              {content.certifications && content.certifications.length > 0 && (
                <div style={{ marginBottom: '14px' }}>
                  <label style={{ display: 'block', fontSize: '12px', fontWeight: '700', color: 'var(--text-muted)', marginBottom: '4px' }}>
                    Certificates & Licenses
                  </label>
                  <textarea
                    value={certificationsText}
                    onChange={(e) => setCertificationsText(e.target.value)}
                    onBlur={handleCertificationsBlur}
                    rows={2}
                    style={{ width: '100%', padding: '8px', borderRadius: '8px', border: '1px solid var(--border)' }}
                  />
                </div>
              )}
              <div style={{ marginBottom: '14px' }}>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: '700', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Detected Links & Profiles
                </label>
                <div style={{ fontSize: '12px', color: 'var(--text-primary)' }}>
                  {(content.relevant_links || []).map((link, idx) => (
                    <div key={idx} style={{ marginBottom: '4px' }}>
                      🔗 <a href={link} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)' }}>{link}</a>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div
          style={{
            padding: '16px 24px',
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
          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              type="button"
              onClick={() => handleCommit('draft')}
              disabled={committing}
              style={preferDraft ? {
                background: 'var(--primary, #2563eb)',
                color: '#fff',
                border: 'none',
                padding: '8px 18px',
                borderRadius: '8px',
                fontSize: '13px',
                fontWeight: '700',
                cursor: committing ? 'wait' : 'pointer',
              } : {
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                padding: '8px 16px',
                borderRadius: '8px',
                fontSize: '13px',
                fontWeight: '600',
                cursor: committing ? 'wait' : 'pointer',
              }}
            >
              Save as Separate Draft
            </button>
            <button
              type="button"
              onClick={() => handleCommit('master')}
              disabled={committing}
              style={preferDraft ? {
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                padding: '8px 16px',
                borderRadius: '8px',
                fontSize: '13px',
                fontWeight: '600',
                cursor: committing ? 'wait' : 'pointer',
              } : {
                background: 'var(--primary, #2563eb)',
                color: '#fff',
                border: 'none',
                padding: '8px 18px',
                borderRadius: '8px',
                fontSize: '13px',
                fontWeight: '700',
                cursor: committing ? 'wait' : 'pointer',
              }}
            >
              {committing ? '⏳ Committing...' : '✓ Commit to Master Profile'}
            </button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}
