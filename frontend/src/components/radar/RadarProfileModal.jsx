import React, { useState, useEffect, useCallback } from 'react'
import { fetchRadarProfile, updateRadarProfile } from '../../api/radarApi.js'
import { validateProfileForm, buildProfilePayload } from '../../utils/careerUiHelpers.js'
import Dialog from '../Dialog'

const ROLE_OPTIONS = [
  'Artificial Intelligence and Machine Learning',
  'Generative AI and LLM Engineering',
  'Software Engineering',
  'Backend Engineering',
  'Data Science & Analytics',
  'Research Internships',
  'Cloud and Infrastructure Engineering',
  'Open Source Programs',
]

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

export default function RadarProfileModal({
  isOpen = true,
  profile,
  onClose,
  onSave,
  isSaving = false,
  onProfileUpdated,
}) {
  // If isOpen is explicitly false, do not render modal
  if (isOpen !== undefined && !isOpen) {
    return null
  }

  return (
    <RadarProfileModalContent
      profile={profile}
      onClose={onClose}
      onSave={onSave}
      isSaving={isSaving}
      onProfileUpdated={onProfileUpdated}
    />
  )
}

function RadarProfileModalContent({
  profile,
  onClose,
  onSave,
  isSaving = false,
  onProfileUpdated,
}) {
  const [degree, setDegree] = useState(profile?.degree || '')
  const [specialization, setSpecialization] = useState(profile?.degree_specialization || '')
  const [university, setUniversity] = useState(profile?.university || '')
  const [academicYear, setAcademicYear] = useState(profile?.academic_year ?? '')
  const [gradYear, setGradYear] = useState(profile?.grad_year ?? '')
  const [gradMonth, setGradMonth] = useState(profile?.grad_month ?? '')
  const [cgpa, setCgpa] = useState(profile?.cgpa !== undefined && profile?.cgpa !== null ? String(profile.cgpa) : '')
  const [cgpaScale, setCgpaScale] = useState(profile?.cgpa_scale || 10.0)
  const [activeBacklogs, setActiveBacklogs] = useState(profile?.active_backlogs ?? '')
  const [countryOfStudy, setCountryOfStudy] = useState(profile?.country_of_study || '')
  const [preferredArrangements, setPreferredArrangements] = useState(
    profile?.preferred_work_arrangements || []
  )
  const [preferredRoles, setPreferredRoles] = useState(
    profile?.preferred_roles || []
  )
  const [skillsStr, setSkillsStr] = useState(
    (profile?.skills || []).join(', ')
  )

  const [savingInternal, setSavingInternal] = useState(false)
  const [loadingProfile, setLoadingProfile] = useState(false)
  const [errorMessage, setErrorMessage] = useState(null)

  // Populate state when profile prop changes
  const applyProfileData = useCallback(p => {
    if (!p) return
    if (p.degree !== undefined) setDegree(p.degree || '')
    if (p.degree_specialization !== undefined) setSpecialization(p.degree_specialization || '')
    if (p.university !== undefined) setUniversity(p.university || '')
    if (p.academic_year !== undefined && p.academic_year !== null) setAcademicYear(Number(p.academic_year))
    if (p.grad_year !== undefined && p.grad_year !== null) setGradYear(Number(p.grad_year))
    if (p.grad_month !== undefined && p.grad_month !== null) setGradMonth(Number(p.grad_month))
    if (p.cgpa !== undefined && p.cgpa !== null) setCgpa(String(p.cgpa))
    if (p.cgpa_scale !== undefined && p.cgpa_scale !== null) setCgpaScale(Number(p.cgpa_scale))
    if (p.active_backlogs !== undefined && p.active_backlogs !== null) setActiveBacklogs(Number(p.active_backlogs))
    if (p.country_of_study !== undefined) setCountryOfStudy(p.country_of_study || '')
    if (Array.isArray(p.preferred_work_arrangements)) setPreferredArrangements(p.preferred_work_arrangements)
    if (Array.isArray(p.preferred_roles)) setPreferredRoles(p.preferred_roles)
    if (Array.isArray(p.skills)) setSkillsStr(p.skills.join(', '))
  }, [])

  useEffect(() => {
    if (profile) {
      applyProfileData(profile)
    }
  }, [profile, applyProfileData])

  // If no profile passed, attempt to load profile asynchronously without blocking the UI
  useEffect(() => {
    if (!profile) {
      let isMounted = true
      setLoadingProfile(true)
      fetchRadarProfile()
        .then(data => {
          if (isMounted && data) {
            applyProfileData(data)
          }
        })
        .catch(err => {
          console.warn('[RadarProfileModal] Background profile fetch non-fatal error:', err)
        })
        .finally(() => {
          if (isMounted) setLoadingProfile(false)
        })
      return () => {
        isMounted = false
      }
    }
  }, [profile, applyProfileData])

  const toggleArrangement = arr => {
    setPreferredArrangements(prev =>
      prev.includes(arr) ? prev.filter(x => x !== arr) : [...prev, arr]
    )
  }

  const toggleRole = role => {
    setPreferredRoles(prev =>
      prev.includes(role) ? prev.filter(r => r !== role) : [...prev, role]
    )
  }

  const isBusy = isSaving || savingInternal
  const isFormComplete = validateProfileForm({ degree, academicYear, gradYear, cgpa, cgpaScale }) === null

  const handleSubmit = async e => {
    e.preventDefault()
    if (isBusy) return

    setErrorMessage(null)

    // Client-side validation (shared with the Save button's disabled state)
    const formValues = {
      degree, specialization, university, academicYear, gradYear, gradMonth, cgpa, cgpaScale,
      activeBacklogs, countryOfStudy, preferredArrangements, preferredRoles, skillsStr,
    }
    const validationError = validateProfileForm(formValues)
    if (validationError) {
      setErrorMessage(validationError)
      return
    }

    // Only fields the user actually filled are sent; nothing is invented.
    const payload = buildProfilePayload(formValues)

    setSavingInternal(true)
    try {
      let result = null
      if (typeof onSave === 'function') {
        result = await onSave(payload)
      } else {
        result = await updateRadarProfile(payload)
      }

      if (typeof onProfileUpdated === 'function') {
        onProfileUpdated(result || payload)
      }

      // Close modal immediately upon successful save
      if (typeof onClose === 'function') {
        onClose()
      }
    } catch (err) {
      console.error('[RadarProfileModal] Failed to save profile:', err)
      setErrorMessage(
        err.message || 'Failed to save profile. Please check your connection and try again.'
      )
    } finally {
      setSavingInternal(false)
    }
  }

  const handleClose = () => {
    if (typeof onClose === 'function') onClose()
  }

  return (
    <Dialog onClose={onClose}
      aria-labelledby="radar-profile-modal-title"
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.65)',
        zIndex: 999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px',
        backdropFilter: 'blur(3px)',
      }}
      onClick={handleClose}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '640px',
          maxHeight: '90vh',
          background: 'var(--bg-card)',
          borderRadius: '16px',
          border: '1px solid var(--border)',
          boxShadow: 'var(--shadow-lg)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          boxSizing: 'border-box',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            padding: '20px 24px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <div>
            <h2
              id="radar-profile-modal-title"
              style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}
            >
              Academic Eligibility & Matching Profile
            </h2>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              Used strictly for deterministic eligibility calculation and customized recommendation ranking.
              {loadingProfile && (
                <span style={{ marginLeft: '8px', color: 'var(--amber-text)', fontStyle: 'italic' }}>
                  (Syncing latest profile…)
                </span>
              )}
            </div>
          </div>
          <button
            type="button"
            aria-label="Close modal"
            onClick={handleClose}
            style={{
              background: 'transparent',
              border: 'none',
              fontSize: '22px',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              padding: '4px 8px',
              borderRadius: '6px',
              lineHeight: 1,
            }}
          >
            ✕
          </button>
        </div>

        {/* Scrollable Form */}
        <form
          onSubmit={handleSubmit}
          style={{
            padding: '24px',
            overflowY: 'auto',
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            gap: '16px',
          }}
        >
          {/* Error Banner */}
          {errorMessage && (
            <div
              role="alert"
              style={{
                padding: '10px 14px',
                borderRadius: '8px',
                background: 'rgba(239, 68, 68, 0.12)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                color: '#ef4444',
                fontSize: '13px',
                fontWeight: 500,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '8px',
              }}
            >
              <span>⚠️ {errorMessage}</span>
              <button
                type="button"
                onClick={() => setErrorMessage(null)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: '#ef4444',
                  cursor: 'pointer',
                  fontSize: '14px',
                }}
              >
                ✕
              </button>
            </div>
          )}

          {/* Degree & Specialization */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
            <div>
              <label
                htmlFor="profile-degree"
                style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}
              >
                Current Degree *
              </label>
              <input
                id="profile-degree"
                type="text"
                value={degree}
                onChange={e => setDegree(e.target.value)}
                placeholder="e.g. B.Tech, B.E., BS"
                required
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-app)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  boxSizing: 'border-box',
                }}
              />
            </div>
            <div>
              <label
                htmlFor="profile-specialization"
                style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}
              >
                Specialization / Major
              </label>
              <input
                id="profile-specialization"
                type="text"
                value={specialization}
                onChange={e => setSpecialization(e.target.value)}
                placeholder="e.g. Computer Science, AI, EE"
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-app)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  boxSizing: 'border-box',
                }}
              />
            </div>
          </div>

          {/* University / Institution */}
          <div>
            <label
              htmlFor="profile-university"
              style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}
            >
              University / Institution
            </label>
            <input
              id="profile-university"
              type="text"
              value={university}
              onChange={e => setUniversity(e.target.value)}
              placeholder="e.g. IIT Delhi, BITS Pilani, NIT Trichy"
              style={{
                width: '100%',
                padding: '9px 12px',
                borderRadius: '8px',
                border: '1px solid var(--border)',
                background: 'var(--bg-app)',
                color: 'var(--text-primary)',
                fontSize: '13px',
                boxSizing: 'border-box',
              }}
            />
          </div>

          {/* Academic Year & Graduation Cohort & Country */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '12px' }}>
            <div>
              <label
                htmlFor="profile-academic-year"
                style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}
              >
                Academic Year *
              </label>
              <select
                id="profile-academic-year"
                value={academicYear}
                onChange={e => setAcademicYear(e.target.value === '' ? '' : Number(e.target.value))}
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-app)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  boxSizing: 'border-box',
                }}
              >
                <option value="">Select year of study</option>
                <option value={1}>1st Year (Freshman)</option>
                <option value={2}>2nd Year (Sophomore)</option>
                <option value={3}>3rd Year (Junior)</option>
                <option value={4}>4th Year (Senior)</option>
                <option value={5}>5th Year (Dual Degree)</option>
              </select>
            </div>

            <div>
              <label
                htmlFor="profile-grad-year"
                style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}
              >
                Graduation Year *
              </label>
              <input
                id="profile-grad-year"
                type="number"
                min={2024}
                max={2035}
                value={gradYear}
                onChange={e => setGradYear(e.target.value)}
                required
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-app)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  boxSizing: 'border-box',
                }}
              />
            </div>

            <div>
              <label
                htmlFor="profile-grad-month"
                style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}
              >
                Graduation Month
              </label>
              <select
                id="profile-grad-month"
                value={gradMonth}
                onChange={e => setGradMonth(e.target.value === '' ? '' : Number(e.target.value))}
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-app)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  boxSizing: 'border-box',
                }}
              >
                <option value="">Not set</option>
                {MONTH_NAMES.map((m, idx) => (
                  <option key={m} value={idx + 1}>
                    {m}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label
                htmlFor="profile-country"
                style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}
              >
                Country of Study *
              </label>
              <input
                id="profile-country"
                type="text"
                value={countryOfStudy}
                onChange={e => setCountryOfStudy(e.target.value)}
                required
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-app)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  boxSizing: 'border-box',
                }}
              />
            </div>
          </div>

          {/* Academic Performance: CGPA & Backlogs */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '12px' }}>
            <div>
              <label
                htmlFor="profile-cgpa"
                style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}
              >
                Current CGPA / Percentage
              </label>
              <input
                id="profile-cgpa"
                type="number"
                step="0.01"
                min="0"
                max={cgpaScale}
                value={cgpa}
                onChange={e => setCgpa(e.target.value)}
                placeholder="e.g. 8.5"
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-app)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  boxSizing: 'border-box',
                }}
              />
            </div>

            <div>
              <label
                htmlFor="profile-cgpa-scale"
                style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}
              >
                Grading Scale
              </label>
              <select
                id="profile-cgpa-scale"
                value={cgpaScale}
                onChange={e => setCgpaScale(Number(e.target.value))}
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-app)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  boxSizing: 'border-box',
                }}
              >
                <option value={10.0}>10.0 Scale (India standard)</option>
                <option value={4.0}>4.0 Scale (US standard)</option>
                <option value={100.0}>100% Percentage Scale</option>
              </select>
            </div>

            <div>
              <label
                htmlFor="profile-backlogs"
                style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}
              >
                Active Backlogs
              </label>
              <input
                id="profile-backlogs"
                type="number"
                min="0"
                max="20"
                value={activeBacklogs}
                onChange={e => setActiveBacklogs(e.target.value)}
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-app)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  boxSizing: 'border-box',
                }}
              />
            </div>
          </div>

          {/* Technical Skills */}
          <div>
            <label
              htmlFor="profile-skills"
              style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}
            >
              Technical Skills (comma-separated)
            </label>
            <input
              id="profile-skills"
              type="text"
              value={skillsStr}
              onChange={e => setSkillsStr(e.target.value)}
              placeholder="e.g. Python, PyTorch, C++, CUDA, React, Go, Docker"
              style={{
                width: '100%',
                padding: '9px 12px',
                borderRadius: '8px',
                border: '1px solid var(--border)',
                background: 'var(--bg-app)',
                color: 'var(--text-primary)',
                fontSize: '13px',
                boxSizing: 'border-box',
              }}
            />
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
              Used to match skill requirements and calculate relevance scores.
            </div>
          </div>

          {/* Work Arrangement Preferences */}
          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '8px' }}>
              Preferred Work Arrangements
            </label>
            <div style={{ display: 'flex', gap: '8px' }}>
              {['remote', 'hybrid', 'onsite'].map(arr => {
                const checked = preferredArrangements.includes(arr)
                return (
                  <button
                    key={arr}
                    type="button"
                    onClick={() => toggleArrangement(arr)}
                    style={{
                      padding: '6px 14px',
                      borderRadius: '8px',
                      border: checked ? '1px solid var(--brand)' : '1px solid var(--border)',
                      background: checked ? 'rgba(245, 166, 35, 0.15)' : 'var(--bg-app)',
                      color: checked ? 'var(--brand)' : 'var(--text-secondary)',
                      fontSize: '12px',
                      fontWeight: 600,
                      cursor: 'pointer',
                      textTransform: 'capitalize',
                    }}
                  >
                    {arr}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Preferred Role Tracks */}
          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '8px' }}>
              Target Opportunity Tracks
            </label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
              {ROLE_OPTIONS.map(role => {
                const selected = preferredRoles.includes(role)
                return (
                  <button
                    key={role}
                    type="button"
                    onClick={() => toggleRole(role)}
                    style={{
                      padding: '5px 12px',
                      borderRadius: '8px',
                      border: selected ? '1px solid var(--brand)' : '1px solid var(--border)',
                      background: selected ? 'rgba(245, 166, 35, 0.12)' : 'var(--bg-app)',
                      color: selected ? 'var(--brand-dark)' : 'var(--text-secondary)',
                      fontSize: '11px',
                      fontWeight: 500,
                      cursor: 'pointer',
                    }}
                  >
                    {selected ? '✓ ' : '+ '}
                    {role}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Footer Submit */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '12px', marginTop: '10px' }}>
            <button
              type="button"
              onClick={handleClose}
              style={{
                padding: '9px 16px',
                borderRadius: '8px',
                background: 'transparent',
                color: 'var(--text-secondary)',
                border: '1px solid var(--border)',
                fontWeight: 600,
                fontSize: '13px',
                cursor: 'pointer',
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isBusy || !isFormComplete}
              style={{
                padding: '10px 20px',
                borderRadius: '8px',
                background: 'var(--brand)',
                color: '#ffffff',
                border: 'none',
                fontWeight: 600,
                fontSize: '13px',
                cursor: isBusy || !isFormComplete ? 'not-allowed' : 'pointer',
                opacity: isBusy || !isFormComplete ? 0.6 : 1,
              }}
            >
              {isBusy ? 'Saving Profile…' : 'Save Profile'}
            </button>
          </div>
        </form>
      </div>
    </Dialog>
  )
}
