import React, { useState, useEffect, useCallback, useRef } from 'react'
import {
  Building2,
  MapPin,
  ClipboardList,
  Target,
  FileText,
  PenLine,
  CheckSquare,
  Send,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  Briefcase,
  AlertCircle,
  MessageSquare,
  ChevronDown,
  ChevronUp,
  ExternalLink,
} from 'lucide-react'
import { cleanOpportunity } from '../../utils/jobCardCleaner'
import {
  prepareApplication,
  fetchResume,
  updateResume,
  tailorResume,
  draftCoverLetter,
  setApplicationCoverLetter,
  updateApplication,
  getResumeExportUrl,
  getResumeExportDocxUrl,
  fetchJobAnalysis,
  fetchCompanyIntel,
  refreshCompanyIntelJob,
  getCompanyIntelJobStatus,
} from '../../api/careerApi'
import { downloadAuthedFile, openAuthedHtml } from '../../api/baseClient.js'

import {
  loadWorkspaceDraft,
  saveWorkspaceDraft,
  clearWorkspaceDraft,
  inspectDraftConflict,
} from '../../utils/workspaceDraft'
import ValidationReportCard from './ValidationReportCard'
import { getSafeHttpUrl } from '../../utils/safeUrl.js'
import {
  buildStatusOptions,
  buildDeadlinePayload,
  formatMatchScore,
  resolveSkillMatch,
  intelCooldownForError,
  intelErrorMessage,
  cooldownSecondsLeft,
  copyWithFeedback,
  DEFAULT_INTEL_COOLDOWN_SECONDS,
  NO_APPLICATION_URL_TEXT,
} from '../../utils/careerUiHelpers.js'

const STATUS_LABELS = {
  discovered: 'Discovered',
  eligibility_checked: 'Eligibility checked',
  preparing: 'Preparing',
  saved: 'Saved',
  ready_for_review: 'Ready for review',
  ready_for_approval: 'Ready for approval',
  approved: 'Approved',
  approved_for_submission: 'Approved for submission',
  submitted: 'Submitted',
  manual_submission_required: 'Manual handoff',
  handoff_kit_ready: 'Handoff kit ready',
  interview: 'Interviewing',
  offer_received: 'Offer received',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
}

function formatStatusLabel(status) {
  if (!status) return 'Preparing'
  const key = String(status).trim().toLowerCase()
  if (STATUS_LABELS[key]) return STATUS_LABELS[key]
  return key
    .split('_')
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

function formatIntelDate(isoString) {
  if (!isoString) return ''
  try {
    const d = new Date(isoString)
    if (isNaN(d.getTime())) return ''
    const now = Date.now()
    const diffMs = now - d.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMins / 60)
    if (diffMins < 1) return 'Updated just now'
    if (diffMins < 60) return `Updated ${diffMins} min${diffMins === 1 ? '' : 's'} ago`
    if (diffHours < 24) return `Updated ${diffHours} hour${diffHours === 1 ? '' : 's'} ago`
    const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    return `Updated ${d.getDate()} ${monthNames[d.getMonth()]}`
  } catch {
    return ''
  }
}

function formatBriefDateOnly(isoString) {
  if (!isoString) return ''
  try {
    const d = new Date(isoString)
    if (isNaN(d.getTime())) return ''
    const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    return `${d.getDate()} ${monthNames[d.getMonth()]}`
  } catch {
    return ''
  }
}

function formatAttemptTime(isoString) {
  if (!isoString) return ''
  try {
    const d = new Date(isoString)
    if (isNaN(d.getTime())) return ''
    const now = new Date()
    const isToday =
      d.getDate() === now.getDate() &&
      d.getMonth() === now.getMonth() &&
      d.getFullYear() === now.getFullYear()
    const timeStr = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    if (isToday) {
      return `Last attempt today, ${timeStr}`
    }
    const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    return `Last attempt ${d.getDate()} ${monthNames[d.getMonth()]}, ${timeStr}`
  } catch {
    return ''
  }
}

function getIntelErrorMessage(reason, fallbackError) {
  switch (reason) {
    case 'search_failed':
    case 'search_quota':
      return 'Search service is temporarily unavailable. Please try refreshing again shortly.'
    case 'search_timeout':
      return 'Search took too long to respond. Please try refreshing again.'
    case 'model_failed':
      return 'Summary service is temporarily unavailable. Please try refreshing again.'
    case 'model_timeout':
      return 'Summary took too long to generate. Please try refreshing again.'
    case 'model_bad_output':
      return 'Could not format company intelligence correctly. Please try refreshing again.'
    case 'no_sources':
      return 'We could not find enough reliable information about this company.'
    case 'auth_failed':
      return 'Service authentication issue. Please try again later.'
    case 'job_lost':
      return 'Server restarted or research session expired. Please refresh intel again.'
    case 'storage_failed':
      return 'Could not save intelligence data. Please try refreshing again.'
    case 'backend_unreachable':
      return 'Network issue. Please check your connection and try again.'
    default:
      return fallbackError || "We couldn't generate company intel right now. Please try again with Refresh Intel."
  }
}

function cleanOldBriefText(text) {
  if (!text) return ''
  let t = String(text)
  t = t.replace(/#{1,6}\s*/g, ' ').replace(/[*_~`]+/g, ' ')
  t = t.replace(/[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/gu, ' ')
  t = t.replace(/\[\s*\.{2,}\s*\]/g, ' ').replace(/\.{3,}/g, ' ').replace(/…/g, ' ')
  t = t.replace(/\b\w+\s+logo\b/gi, ' ').replace(/\b(?:view job|apply now|save job|report job|cookie)\b:?/gi, ' ')
  t = t.replace(/\u2014/g, '-').replace(/\u2013/g, '-')
  t = t.replace(/\s+/g, ' ').trim()
  const punct = Math.max(t.lastIndexOf('.'), t.lastIndexOf('!'), t.lastIndexOf('?'))
  if (punct !== -1) {
    t = t.slice(0, punct + 1)
  }
  const words = t.split(' ')
  if (words.length > 22) {
    t = words.slice(0, 22).join(' ') + '.'
  }
  return t
}

export default function ApplicationWorkspaceModal({
  opportunity,
  onClose,
  onApplicationUpdated,
  onNavigateToResumeStudio,
  onOpenProfile,
}) {
  const handleFixInProfile = () => {
    if (onClose) onClose()
    const nav = onNavigateToResumeStudio || onOpenProfile
    if (nav) nav()
  }

  const [activeTab, setActiveTab] = useState('overview') // 'overview' | 'resume' | 'cover_letter' | 'checklist' | 'handoff'
  const [application, setApplication] = useState(null)
  const [resume, setResume] = useState(null)
  const [loading, setLoading] = useState(true)
  const [tailoring, setTailoring] = useState(false)
  const [savingResume, setSavingResume] = useState(false)
  const [draftingLetter, setDraftingLetter] = useState(false)
  const [savingLetter, setSavingLetter] = useState(false)
  const [savingStatus, setSavingStatus] = useState(false)
  const [error, setError] = useState(null)
  const [notification, setNotification] = useState(null)
  const [exportingDocx, setExportingDocx] = useState(false)
  const [exportingPrint, setExportingPrint] = useState(false)

  // Resume form state
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [location, setLocation] = useState('')
  const [summary, setSummary] = useState('')
  const [skillsText, setSkillsText] = useState('')
  const [resumeTemplate, setResumeTemplate] = useState('ats_classic') // 'ats_classic' | 'modern' | 'minimal'

  // Cover Letter & Notes state
  const [coverLetterText, setCoverLetterText] = useState('')
  const [appStatus, setAppStatus] = useState('preparing')
  const [privateNotes, setPrivateNotes] = useState('')
  const [targetDeadline, setTargetDeadline] = useState('')

  // Draft recovery state
  const [draftConflict, setDraftConflict] = useState(null)
  const [isInitialLoaded, setIsInitialLoaded] = useState(false)

  // Job Requirement Analysis state (Phase 5 & 8)
  const [jobAnalysis, setJobAnalysis] = useState(null)
  const [loadingAnalysis, setLoadingAnalysis] = useState(false)
  const [analysisError, setAnalysisError] = useState(null)
  const [workspaceError, setWorkspaceError] = useState(null)
  const [customJobDesc, setCustomJobDesc] = useState(opportunity?.description || '')

  // Preparation Checklist state (stored in application metadata / notes or locally)
  const [checklist, setChecklist] = useState({
    resumeTailored: false,
    resumeDownloaded: false,
    coverLetterDrafted: false,
    questionsReviewed: false,
    submittedExternally: false,
  })

  // Load deep job requirement analysis
  const loadJobAnalysisData = useCallback(async (customDesc = null) => {
    if (!opportunity?.id) return
    setLoadingAnalysis(true)
    setAnalysisError(null)
    try {
      const report = await fetchJobAnalysis(opportunity.id, customDesc)
      setJobAnalysis(report)
    } catch (err) {
      console.warn('Could not load detailed job analysis:', err)
      setAnalysisError(err?.message || 'Could not load the analysis.')
    } finally {
      setLoadingAnalysis(false)
    }
  }, [opportunity?.id])

  // Company Intel state
  const [companyIntel, setCompanyIntel] = useState(null)
  const [loadingIntel, setLoadingIntel] = useState(false)
  const [coldStartPending, setColdStartPending] = useState(false)
  const [intelError, setIntelError] = useState(null)
  const [lastAttemptTime, setLastAttemptTime] = useState(null)
  const [sourcesExpanded, setSourcesExpanded] = useState(false)
  const [highlightedSourceId, setHighlightedSourceId] = useState(null)
  const [intelRequested, setIntelRequested] = useState(false)
  const [cooldownUntil, setCooldownUntil] = useState(0)
  const [nowTick, setNowTick] = useState(() => Date.now())
  const refreshBtnRef = useRef(null)
  const cooldownUntilRef = useRef(0)
  const intelFetchStartedRef = useRef(false)
  const cooldownSeconds = cooldownSecondsLeft(cooldownUntil, nowTick)

  // Tick once a second while a cooldown is running so the countdown stays visible.
  useEffect(() => {
    if (!cooldownUntil || cooldownUntil <= Date.now()) return undefined
    const timer = setInterval(() => {
      const now = Date.now()
      setNowTick(now)
      if (now >= cooldownUntil) clearInterval(timer)
    }, 1000)
    return () => clearInterval(timer)
  }, [cooldownUntil])
  const companyIntelRef = useRef(null)
  const loadingIntelRef = useRef(false)
  const coldStartTimerRef = useRef(null)

  useEffect(() => {
    return () => {
      if (coldStartTimerRef.current) {
        clearTimeout(coldStartTimerRef.current)
      }
    }
  }, [])

  useEffect(() => {
    companyIntelRef.current = companyIntel
  }, [companyIntel])

  // Load company intelligence
  const loadCompanyIntelData = useCallback(async (isRefresh = false) => {
    if (!opportunity?.id) return
    if (loadingIntelRef.current) return

    if (isRefresh && cooldownUntilRef.current > Date.now()) return

    const startCooldown = (seconds) => {
      if (!(seconds > 0)) return
      const until = Date.now() + seconds * 1000
      cooldownUntilRef.current = until
      setCooldownUntil(until)
      setNowTick(Date.now())
    }

    loadingIntelRef.current = true
    setLoadingIntel(true)
    setIntelError(null)
    setColdStartPending(false)
    if (coldStartTimerRef.current) clearTimeout(coldStartTimerRef.current)
    coldStartTimerRef.current = setTimeout(() => {
      setColdStartPending(true)
    }, 5000)

    try {
      if (isRefresh) {
        let job = null
        try {
          job = await refreshCompanyIntelJob(opportunity.id)
        } catch (postErr) {
          // The server answered 429: do not retry through the sync path, surface its message.
          if (postErr?.status === 429) throw postErr
          console.warn('Async refresh job creation failed, falling back to sync fetch:', postErr)
        }
        // The server accepted the refresh (job created or answered): only now throttle further refreshes.
        if (job) startCooldown(DEFAULT_INTEL_COOLDOWN_SECONDS)

        if (job?.status === 'done' && job?.result) {
          setCompanyIntel(job.result)
          if (job.result.status === 'error' || job.result.error) {
            setIntelError(getIntelErrorMessage(job.result.reason, job.result.error))
            setLastAttemptTime(new Date().toISOString())
          }
        } else if (job?.job_id) {
          const maxAttempts = 30
          let attempt = 0
          let finished = false
          let consecutivePollErrors = 0

          while (attempt < maxAttempts && !finished) {
            await new Promise((r) => setTimeout(r, 2000))
            if (document.visibilityState === 'hidden') {
              break
            }
            attempt++
            try {
              const statusData = await getCompanyIntelJobStatus(opportunity.id, job.job_id)
              consecutivePollErrors = 0
              if (statusData?.status === 'done' && statusData?.result) {
                setCompanyIntel(statusData.result)
                if (statusData.result.status === 'error' || statusData.result.error) {
                  setIntelError(getIntelErrorMessage(statusData.result.reason, statusData.result.error))
                  setLastAttemptTime(new Date().toISOString())
                }
                finished = true
                break
              } else if (statusData?.status === 'failed') {
                const msg = getIntelErrorMessage(statusData.reason, statusData.error)
                setIntelError(msg)
                setLastAttemptTime(new Date().toISOString())
                finished = true
                break
              }
            } catch (pollErr) {
              consecutivePollErrors++
              console.warn('Job poll error:', pollErr)
              if (consecutivePollErrors >= 3) {
                setIntelError('Connection to research service lost. Please refresh intel again.')
                setLastAttemptTime(new Date().toISOString())
                finished = true
                break
              }
            }
          }

          if (!finished) {
            setIntelError('Research took too long to complete. Please try refreshing again.')
            setLastAttemptTime(new Date().toISOString())
          }
        } else {
          const intel = await fetchCompanyIntel(opportunity.id, true)
          startCooldown(DEFAULT_INTEL_COOLDOWN_SECONDS)
          setCompanyIntel(intel)
          if (intel?.status === 'error' || intel?.error) {
            setIntelError(getIntelErrorMessage(intel.reason, intel.error))
            setLastAttemptTime(new Date().toISOString())
          }
        }
      } else {
        const intel = await fetchCompanyIntel(opportunity.id, false)
        setCompanyIntel(intel)
        if (intel?.status === 'error' || intel?.error) {
          setIntelError(getIntelErrorMessage(intel.reason, intel.error))
          setLastAttemptTime(new Date().toISOString())
        }
      }
    } catch (err) {
      console.warn('Could not load company intelligence:', err)
      setLastAttemptTime(new Date().toISOString())
      // A 429 means the server refused: back off for Retry-After. Other failures never start a cooldown.
      startCooldown(intelCooldownForError(err))
      // Prefer the server's own wording (budget exhausted / cooldown / daily cap) when it answered.
      const errMsg = err?.status ? intelErrorMessage(err) : getIntelErrorMessage('backend_unreachable', err?.message)
      if (!companyIntelRef.current) {
        setIntelError(errMsg)
      } else if (err?.status) {
        showNotification(errMsg, 'error')
      } else {
        showNotification('Could not refresh intelligence report. Please try again.', 'error')
      }
    } finally {
      if (coldStartTimerRef.current) {
        clearTimeout(coldStartTimerRef.current)
        coldStartTimerRef.current = null
      }
      setColdStartPending(false)
      loadingIntelRef.current = false
      setLoadingIntel(false)
      if (isRefresh && refreshBtnRef.current) {
        refreshBtnRef.current.focus()
      }
    }
  }, [opportunity?.id])

  // Load or auto-prepare application on mount
  const loadWorkspaceData = useCallback(async () => {
    if (!opportunity?.id) return
    setLoading(true)
    setError(null)
    setWorkspaceError(null)
    try {
      const app = await prepareApplication(opportunity.id)
      setApplication(app)
      setAppStatus(String(app.status || 'preparing').toLowerCase())
      setPrivateNotes(app.private_notes || '')
      setTargetDeadline(app.target_deadline || '')
      setCoverLetterText(app.cover_letter || '')

      let currentResume = null
      if (app.resume_id) {
        currentResume = await fetchResume(app.resume_id)
        setResume(currentResume)
        populateResumeForm(currentResume)
        setChecklist(prev => ({
          ...prev,
          resumeTailored: true,
          coverLetterDrafted: Boolean(app.cover_letter),
          submittedExternally: String(app.status || '').toLowerCase() === 'submitted',
        }))
      }

      // Check for local unsaved draft
      const storedDraft = loadWorkspaceDraft(opportunity.id)
      if (storedDraft) {
        const conflict = inspectDraftConflict(storedDraft, currentResume, app)
        if (conflict.hasConflict) {
          setDraftConflict(conflict)
        }
      }
      setIsInitialLoaded(true)
      loadJobAnalysisData()
    } catch (err) {
      console.error('Error loading application workspace:', err)
      const message = err.message || 'Failed to prepare application workspace.'
      setError(message)
      setWorkspaceError(message)
    } finally {
      setLoading(false)
    }
  }, [opportunity?.id, loadJobAnalysisData])

  useEffect(() => {
    loadWorkspaceData()
  }, [loadWorkspaceData])

  // Company Intel spends the shared daily search budget, so fetch it lazily the first time
  // its tab is opened (once per mount); afterwards only the Refresh button re-fetches.
  useEffect(() => {
    if (activeTab !== 'company_intel' || !isInitialLoaded || intelFetchStartedRef.current) return
    intelFetchStartedRef.current = true
    setIntelRequested(true)
    loadCompanyIntelData()
  }, [activeTab, isInitialLoaded, loadCompanyIntelData])

  // Restore unsaved local draft edits
  const handleRestoreDraft = () => {
    if (!draftConflict?.draftRecord?.draft) return
    const d = draftConflict.draftRecord.draft
    if (d.fullName !== undefined) setFullName(d.fullName)
    if (d.email !== undefined) setEmail(d.email)
    if (d.phone !== undefined) setPhone(d.phone)
    if (d.location !== undefined) setLocation(d.location)
    if (d.summary !== undefined) setSummary(d.summary)
    if (d.skillsText !== undefined) setSkillsText(d.skillsText)
    if (d.resumeTemplate) setResumeTemplate(d.resumeTemplate)
    if (d.coverLetterText !== undefined) setCoverLetterText(d.coverLetterText)
    if (d.privateNotes !== undefined) setPrivateNotes(d.privateNotes)
    if (d.targetDeadline !== undefined) setTargetDeadline(d.targetDeadline)
    setDraftConflict(null)
    showNotification('Restored unsaved local draft edits!')
  }

  // Discard local draft and preserve server state
  const handleDiscardDraft = () => {
    clearWorkspaceDraft(opportunity?.id)
    setDraftConflict(null)
    showNotification('Discarded local draft.')
  }

  // Debounced auto-save to local draft
  useEffect(() => {
    if (!isInitialLoaded || !opportunity?.id || draftConflict) return

    const timer = setTimeout(() => {
      saveWorkspaceDraft(opportunity.id, {
        fullName,
        email,
        phone,
        location,
        summary,
        skillsText,
        resumeTemplate,
        coverLetterText,
        privateNotes,
        targetDeadline,
        baseResumeId: resume?.id,
        baseResumeUpdatedAt: resume?.updated_at,
        baseAppUpdatedAt: application?.updated_at,
      })
    }, 600)

    return () => clearTimeout(timer)
  }, [
    isInitialLoaded,
    opportunity?.id,
    fullName,
    email,
    phone,
    location,
    summary,
    skillsText,
    resumeTemplate,
    coverLetterText,
    privateNotes,
    targetDeadline,
    resume?.id,
    resume?.updated_at,
    application?.updated_at,
    draftConflict,
  ])

  const populateResumeForm = (res) => {
    if (!res || !res.content) return
    const c = res.content
    setFullName(c.full_name || '')
    setEmail(c.email || '')
    setPhone(c.phone || '')
    setLocation(c.location || '')
    setSummary(c.summary || '')
    setSkillsText((c.skills || []).join(', '))
  }

  const showNotification = (msg, type = 'success') => {
    setNotification({ message: msg, type })
    setTimeout(() => {
      setNotification(prev => (prev?.message === msg ? null : prev))
    }, 3500)
  }

  // Handle AI Resume Tailoring (strictly truthful, preserves master)
  const handleTriggerTailor = async () => {
    setTailoring(true)
    setError(null)
    try {
      const tailored = await tailorResume(opportunity.id, null, null, application?.id ?? null)
      setResume(tailored)
      populateResumeForm(tailored)
      if (application) {
        setApplication(prev => ({ ...prev, resume_id: tailored.id, resume: tailored }))
      }
      setChecklist(prev => ({ ...prev, resumeTailored: true }))
      const verified = tailored?.validation_report?.status && tailored.validation_report.status !== 'NOT ENOUGH DATA'
      if (verified) {
        showNotification('Tailored resume snapshot created and validated against your master profile!')
      } else {
        showNotification('Tailored resume snapshot created. Add more details to your master profile to enable verification.')
      }
    } catch (err) {
      setError(err.message || 'Failed to tailor resume')
    } finally {
      setTailoring(false)
    }
  }

  // Handle saving inline edits to tailored resume
  const handleSaveResumeEdits = async () => {
    if (!resume) return
    setSavingResume(true)
    setError(null)
    try {
      const skillsArr = skillsText.split(',').map(s => s.trim()).filter(Boolean)
      const updatedContent = {
        ...(resume.content || {}),
        full_name: fullName,
        email,
        phone,
        location,
        summary,
        skills: skillsArr,
      }
      const updated = await updateResume(resume.id, {
        title: resume.title || `${opportunity.company_name} Tailored Resume`,
        content: updatedContent,
      })
      setResume(updated)
      clearWorkspaceDraft(opportunity.id)
      showNotification('Resume updates saved and factual validation re-evaluated.')
    } catch (err) {
      setError(err.message || 'Failed to save resume edits')
    } finally {
      setSavingResume(false)
    }
  }

  const handleExportDocx = async () => {
    if (!resume?.id || exportingDocx) return
    const nameVal = (resume.content?.full_name || fullName || '').trim()
    const emailVal = (resume.content?.email || email || '').trim()
    if (!nameVal || nameVal.toLowerCase() === 'compass candidate' || !emailVal || emailVal.toLowerCase() === 'candidate@compass.local') {
      setError('Please complete candidate Full Name and Email before exporting.')
      return
    }
    setExportingDocx(true)
    try {
      const url = getResumeExportDocxUrl(resume.id)
      const fallbackName = `${(resume.title || 'tailored_resume').replace(/[^\w\s-]/g, '').trim().replace(/\s+/g, '_')}.docx`
      const res = await downloadAuthedFile(url, fallbackName)
      showNotification(`Downloaded ${res.filename || 'Word (.docx) resume'}.`)
    } catch (err) {
      setError(err.message || 'Failed to download Word document.')
    } finally {
      setExportingDocx(false)
    }
  }

  const handleExportPrint = async () => {
    if (!resume?.id || exportingPrint) return
    const nameVal = (resume.content?.full_name || fullName || '').trim()
    const emailVal = (resume.content?.email || email || '').trim()
    if (!nameVal || nameVal.toLowerCase() === 'compass candidate' || !emailVal || emailVal.toLowerCase() === 'candidate@compass.local') {
      setError('Please complete candidate Full Name and Email before exporting.')
      return
    }
    setExportingPrint(true)
    const popup = typeof window !== 'undefined' ? window.open('about:blank', '_blank') : null
    try {
      const url = getResumeExportUrl(resume.id, resumeTemplate)
      await openAuthedHtml(url, { printOnLoad: true, popup })
      showNotification('Opened ATS-compliant printable resume for PDF export.')
    } catch (err) {
      if (popup && typeof popup.close === 'function' && !popup.closed) {
        try { popup.close() } catch { /* ignore */ }
      }
      setError(err.message || 'Failed to open print preview.')
    } finally {
      setExportingPrint(false)
    }
  }

  // Handle Cover Letter Generation
  const handleGenerateCoverLetter = async () => {
    setDraftingLetter(true)
    setError(null)
    try {
      const res = await draftCoverLetter(opportunity.id)
      setCoverLetterText(res.content)
      if (application) {
        await setApplicationCoverLetter(application.id, res.content)
      }
      setChecklist(prev => ({ ...prev, coverLetterDrafted: true }))
      showNotification('Truthful cover letter generated from your verified projects and skills!')
    } catch (err) {
      setError(err.message || 'Failed to generate cover letter')
    } finally {
      setDraftingLetter(false)
    }
  }

  // Handle Saving Cover Letter
  const handleSaveCoverLetter = async () => {
    if (!application) return
    setSavingLetter(true)
    setError(null)
    try {
      await setApplicationCoverLetter(application.id, coverLetterText)
      clearWorkspaceDraft(opportunity.id)
      setChecklist(prev => ({ ...prev, coverLetterDrafted: Boolean(coverLetterText) }))
      showNotification('Cover letter saved to application record.')
    } catch (err) {
      setError(err.message || 'Failed to save cover letter')
    } finally {
      setSavingLetter(false)
    }
  }

  // Handle Status & Notes Updates
  const handleUpdateApplicationRecord = async (newStatus = appStatus) => {
    if (!application) return false
    setSavingStatus(true)
    setError(null)
    try {
      const statusToSend = newStatus ? String(newStatus).toUpperCase() : undefined
      const updated = await updateApplication(application.id, {
        status: statusToSend,
        private_notes: privateNotes || null,
        ...buildDeadlinePayload(targetDeadline),
      })
      setApplication(updated)
      setAppStatus(String(updated.status || newStatus).toLowerCase())
      clearWorkspaceDraft(opportunity.id)
      if (onApplicationUpdated) onApplicationUpdated(updated)
      showNotification(`Application updated: Status is now "${(statusToSend || '').toUpperCase()}"`)
      return true
    } catch (err) {
      setError(err.message || 'Failed to update application status')
      return false
    } finally {
      setSavingStatus(false)
    }
  }

  // Copy to the clipboard and report the real outcome (never announce success on failure).
  const handleCopy = async (label, text) => {
    const result = await copyWithFeedback(label, text)
    showNotification(result.message, result.ok ? 'success' : 'error')
  }

  // Handle External Submission Confirmation
  const handleConfirmExternalSubmission = async () => {
    const success = await handleUpdateApplicationRecord('submitted')
    if (!success) return
    setChecklist(prev => ({ ...prev, submittedExternally: true }))
    showNotification('You marked this as submitted. Compass cannot verify submissions on employer portals.')
  }

  // Compute Match Analysis
  const rawRequiredSkills = opportunity?.requirements?.required_skills || []
  const requiredSkills = rawRequiredSkills.length > 0
    ? rawRequiredSkills
    : (jobAnalysis?.required_skills || [])
  // Matched/missing come from the analysis once loaded, so the overview and the analysis tab agree.
  const skillMatch = resolveSkillMatch({
    analysis: jobAnalysis,
    loading: loadingAnalysis,
    failed: Boolean(analysisError),
    postingSkills: requiredSkills,
  })
  const matchedSkills = skillMatch.matched
  const missingSkills = skillMatch.missing
  const matchScoreView = formatMatchScore(loadingAnalysis && !jobAnalysis ? null : jobAnalysis)

  const cleanedOpp = cleanOpportunity(opportunity)
  const safeApplyUrl = getSafeHttpUrl(opportunity?.official_application_url)

  const tabListRef = useRef(null)
  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(false)

  const checkTabScroll = useCallback(() => {
    const el = tabListRef.current
    if (!el) return
    const { scrollLeft, scrollWidth, clientWidth } = el
    setCanScrollLeft(scrollLeft > 4)
    setCanScrollRight(scrollLeft < scrollWidth - clientWidth - 4)
  }, [])

  useEffect(() => {
    const el = tabListRef.current
    if (!el) return
    checkTabScroll()
    el.addEventListener('scroll', checkTabScroll, { passive: true })
    window.addEventListener('resize', checkTabScroll)
    return () => {
      el.removeEventListener('scroll', checkTabScroll)
      window.removeEventListener('resize', checkTabScroll)
    }
  }, [checkTabScroll])

  useEffect(() => {
    const el = tabListRef.current
    if (!el) return
    const activeEl = el.querySelector('[aria-selected="true"]')
    if (activeEl) {
      activeEl.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' })
    }
    checkTabScroll()
  }, [activeTab, checkTabScroll])

  const scrollTabs = (dir) => {
    const el = tabListRef.current
    if (!el) return
    el.scrollBy({ left: dir === 'left' ? -200 : 200, behavior: 'smooth' })
  }

  const handleTabKeyDown = (e, index) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault()
      const nextIdx = (index + 1) % TABS.length
      setActiveTab(TABS[nextIdx].key)
      const tabs = tabListRef.current?.querySelectorAll('[role="tab"]')
      tabs?.[nextIdx]?.focus()
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault()
      const prevIdx = (index - 1 + TABS.length) % TABS.length
      setActiveTab(TABS[prevIdx].key)
      const tabs = tabListRef.current?.querySelectorAll('[role="tab"]')
      tabs?.[prevIdx]?.focus()
    } else if (e.key === 'Home') {
      e.preventDefault()
      setActiveTab(TABS[0].key)
      const tabs = tabListRef.current?.querySelectorAll('[role="tab"]')
      tabs?.[0]?.focus()
    } else if (e.key === 'End') {
      e.preventDefault()
      setActiveTab(TABS[TABS.length - 1].key)
      const tabs = tabListRef.current?.querySelectorAll('[role="tab"]')
      tabs?.[TABS.length - 1]?.focus()
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      setActiveTab(TABS[index].key)
    }
  }

  const TABS = [
    { key: 'overview', icon: ClipboardList, label: 'Role & Match' },
    { key: 'company_intel', icon: Building2, label: 'Company Intel' },
    { key: 'job_analysis', icon: Target, label: 'Job Analysis' },
    { key: 'resume', icon: FileText, label: 'Tailored Resume' },
    { key: 'cover_letter', icon: PenLine, label: 'Cover Letter' },
    { key: 'checklist', icon: CheckSquare, label: 'Checklist & Notes' },
    { key: 'handoff', icon: Send, label: 'Official Submission' },
  ]

  return (
    <div
      id="application-workspace-backdrop"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        background: 'rgba(15, 23, 42, 0.75)',
        backdropFilter: 'blur(6px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px',
        boxSizing: 'border-box',
      }}
    >
      <div
        id="application-workspace-modal"
        style={{
          width: '100%',
          maxWidth: '920px',
          maxHeight: '92vh',
          background: 'var(--bg-card)',
          borderRadius: '16px',
          border: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.35)',
          overflow: 'hidden',
          animation: 'fadeIn 0.2s ease-out',
        }}
      >
        {/* Workspace Header */}
        <div
          style={{
            padding: '18px 24px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: '16px',
            background: 'var(--bg-app)',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  padding: '3px 8px',
                  borderRadius: 'var(--radius-chip, 6px)',
                  background: 'var(--bg-card-soft)',
                  color: 'var(--text-secondary)',
                  border: '1px solid var(--border)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px',
                }}
              >
                Application Workspace
              </span>
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  padding: '3px 8px',
                  borderRadius: 'var(--radius-chip, 6px)',
                  background: 'var(--bg-card-soft)',
                  color: 'var(--text-secondary)',
                  border: '1px solid var(--border)',
                }}
              >
                Status: {formatStatusLabel(appStatus)}
              </span>
            </div>
            <h2 style={{ margin: '6px 0 2px 0', fontSize: '20px', fontWeight: 800, color: 'var(--text-primary)' }}>
              {opportunity.role_title}
            </h2>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}>
                <Building2 size={14} strokeWidth={1.8} aria-hidden="true" />
                <strong>{cleanedOpp.company}</strong>
              </span>
              <span>•</span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}>
                <MapPin size={14} strokeWidth={1.8} aria-hidden="true" />
                <span>{cleanedOpp.locationLine}</span>
              </span>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close Application Workspace"
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
            ×
          </button>
        </div>

        {/* Workspace Notifications */}
        {notification && (
          <div
            style={{
              padding: '10px 20px',
              background: notification.type === 'success' ? '#f0fdf4' : notification.type === 'error' ? '#fef2f2' : '#eff6ff',
              color: notification.type === 'success' ? '#166534' : notification.type === 'error' ? '#991b1b' : '#1d4ed8',
              borderBottom: '1px solid var(--border)',
              fontSize: '13px',
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            <span>{notification.type === 'success' ? '✓' : notification.type === 'error' ? '⚠️' : 'ℹ️'}</span>
            <span>{notification.message}</span>
          </div>
        )}

        {/* Global Error Banner */}
        {error && (
          <div
            style={{
              padding: '10px 20px',
              background: '#fef2f2',
              color: '#991b1b',
              borderBottom: '1px solid #fecaca',
              fontSize: '13px',
            }}
          >
            <strong>Error:</strong> {error}
          </div>
        )}

        {/* Workspace Nav Tabs */}
        <div className="unified-tablist-container">
          {canScrollLeft && (
            <button
              type="button"
              className="tab-scroll-btn"
              onClick={() => scrollTabs('left')}
              aria-label="Scroll tabs left"
              tabIndex={-1}
            >
              <ChevronLeft size={16} strokeWidth={2} />
            </button>
          )}
          {canScrollLeft && <div className="tab-scroll-fade-left" aria-hidden="true" />}

          <div
            ref={tabListRef}
            role="tablist"
            aria-label="Application workspace sections"
            className="unified-tablist"
          >
            {TABS.map((tab, idx) => {
              const isActive = activeTab === tab.key
              const TabIcon = tab.icon
              return (
                <button
                  key={tab.key}
                  id={`tab-${tab.key}`}
                  role="tab"
                  aria-selected={isActive}
                  aria-controls={`panel-${tab.key}`}
                  tabIndex={isActive ? 0 : -1}
                  type="button"
                  onClick={() => setActiveTab(tab.key)}
                  onKeyDown={(e) => handleTabKeyDown(e, idx)}
                  className={`unified-tab ${isActive ? 'active' : ''}`}
                >
                  <span className="unified-tab-icon" aria-hidden="true">
                    <TabIcon size={14} strokeWidth={1.8} />
                  </span>
                  <span>{tab.label}</span>
                </button>
              )
            })}
          </div>

          {canScrollRight && <div className="tab-scroll-fade-right" aria-hidden="true" />}
          {canScrollRight && (
            <button
              type="button"
              className="tab-scroll-btn"
              onClick={() => scrollTabs('right')}
              aria-label="Scroll tabs right"
              tabIndex={-1}
            >
              <ChevronRight size={16} strokeWidth={2} />
            </button>
          )}
        </div>

        {/* Main Content Area */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
          {loading ? (
            <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)' }}>
              <div style={{ fontSize: '24px', marginBottom: '8px' }}>⏳</div>
              <div>Initializing application workspace and tailored resume snapshot…</div>
            </div>
          ) : (
            <>
              {/* Draft Recovery Banner */}
              {draftConflict && (
                <div
                  id="draft-conflict-banner"
                  style={{
                    padding: '12px 16px',
                    borderRadius: '8px',
                    background: draftConflict.type === 'server_newer' ? '#fffbeb' : '#eff6ff',
                    border: draftConflict.type === 'server_newer' ? '1px solid #fcd34d' : '1px solid #bfdbfe',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '12px',
                    flexWrap: 'wrap',
                    marginBottom: '16px',
                  }}
                >
                  <div style={{ fontSize: '13px', color: draftConflict.type === 'server_newer' ? '#92400e' : '#1e40af', lineHeight: 1.4 }}>
                    {draftConflict.type === 'server_newer' ? (
                      <span>
                        ⚠️ <strong>Server has newer updates</strong>, but you also have an unsaved local draft ({new Date(draftConflict.draftUpdatedAt).toLocaleTimeString()}).
                      </span>
                    ) : (
                      <span>
                        💾 <strong>Unsaved local draft found</strong> ({new Date(draftConflict.draftUpdatedAt).toLocaleTimeString()}). Would you like to restore your edits?
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      type="button"
                      id="restore-draft-btn"
                      onClick={handleRestoreDraft}
                      style={{
                        padding: '5px 12px',
                        borderRadius: '6px',
                        background: 'var(--brand)',
                        color: '#ffffff',
                        border: 'none',
                        fontSize: '12px',
                        fontWeight: 600,
                        cursor: 'pointer',
                      }}
                    >
                      Restore Draft
                    </button>
                    <button
                      type="button"
                      id="discard-draft-btn"
                      onClick={handleDiscardDraft}
                      style={{
                        padding: '5px 12px',
                        borderRadius: '6px',
                        background: 'transparent',
                        color: 'var(--text-muted)',
                        border: '1px solid var(--border)',
                        fontSize: '12px',
                        fontWeight: 600,
                        cursor: 'pointer',
                      }}
                    >
                      Discard
                    </button>
                  </div>
                </div>
              )}

              {/* Workspace failed to load: Company Intel and Job Analysis depend on it */}
              {workspaceError && (activeTab === 'company_intel' || activeTab === 'job_analysis') && (
                <div
                  id="workspace-load-error"
                  role="alert"
                  style={{ padding: '24px 20px', borderRadius: '8px', background: '#fef2f2', border: '1px solid #fecaca', textAlign: 'center' }}
                >
                  <p style={{ margin: '0 0 12px 0', fontSize: '13px', color: '#991b1b' }}>
                    Could not prepare this workspace: {workspaceError}
                  </p>
                  <button
                    type="button"
                    onClick={loadWorkspaceData}
                    className="radar-card-btn radar-card-btn-secondary"
                  >
                    <RefreshCw size={14} aria-hidden="true" />
                    <span>Retry</span>
                  </button>
                </div>
              )}

              {/* TAB: Company Intel Brief */}
              {activeTab === 'company_intel' && !workspaceError && (() => {
                const isOldBrief = companyIntel && !('summary' in companyIntel) && Boolean(companyIntel.strategic_insights || companyIntel.technical_pain_points)
                const isError = Boolean(companyIntel?.status === 'error' || companyIntel?.error || intelError)
                const isEmptyInfo = Boolean(
                  !isError && (
                    companyIntel?.status === 'empty' ||
                    Boolean(companyIntel?.message && (!companyIntel.summary || companyIntel.summary === '')) ||
                    (companyIntel && !isOldBrief && !companyIntel.summary && (!companyIntel.priorities || companyIntel.priorities.length === 0))
                  )
                )
                const isReady = Boolean(
                  companyIntel && !isError && !isEmptyInfo && !isOldBrief && (Boolean(companyIntel.summary) || (Array.isArray(companyIntel.priorities) && companyIntel.priorities.length > 0))
                )
                const isShowingOlderBrief = Boolean(companyIntel?.showing_older_brief || companyIntel?.refresh_failed)

                const sections = [
                  {
                    key: 'priorities',
                    title: 'What they care about',
                    icon: Target,
                    points: companyIntel?.priorities || [],
                  },
                  {
                    key: 'role_context',
                    title: 'What this role works on',
                    icon: Briefcase,
                    points: companyIntel?.role_context || [],
                  },
                  {
                    key: 'challenges',
                    title: 'Challenges to know',
                    icon: AlertCircle,
                    points: companyIntel?.challenges || [],
                  },
                  {
                    key: 'talking_points',
                    title: 'Talking points for your application',
                    icon: MessageSquare,
                    points: companyIntel?.talking_points || [],
                  },
                ].filter(s => Array.isArray(s.points) && s.points.length > 0)

                const oldItems = isOldBrief ? [
                  ...(companyIntel.strategic_insights || []),
                  ...(companyIntel.technical_pain_points || []),
                  ...(companyIntel.recent_news || []),
                ].map(cleanOldBriefText).filter(Boolean).slice(0, 3) : []

                const handleJumpToSource = (sourceId) => {
                  setSourcesExpanded(true)
                  setHighlightedSourceId(sourceId)
                  setTimeout(() => {
                    const el = document.getElementById(`intel-source-${sourceId}`)
                    if (el) {
                      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
                    }
                  }, 80)
                  setTimeout(() => setHighlightedSourceId(null), 3000)
                }

                return (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', paddingBottom: '24px' }}>
                    {/* Header Row */}
                    <div
                      style={{
                        padding: '16px 20px',
                        borderRadius: '6px',
                        background: 'var(--bg-app)',
                        border: '1px solid var(--border)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        flexWrap: 'wrap',
                        gap: '12px',
                      }}
                    >
                      <div style={{ minWidth: '220px', flex: '1 1 auto' }}>
                        <h3 style={{ margin: '0 0 4px 0', fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
                          Company intel for {opportunity.company_name}
                        </h3>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', fontSize: '12px', color: 'var(--text-secondary)' }}>
                          {isReady && companyIntel?.generated_at && (
                            <span>{formatIntelDate(companyIntel.generated_at)}</span>
                          )}
                          {isReady && companyIntel?.confidence && (
                            <span
                              style={{
                                padding: '2px 8px',
                                borderRadius: '6px',
                                border: '1px solid var(--border)',
                                background: 'var(--bg-card)',
                                color: 'var(--text-secondary)',
                                fontSize: '11px',
                                fontWeight: 600,
                                textTransform: 'capitalize',
                              }}
                            >
                              {companyIntel.confidence} confidence
                            </span>
                          )}
                          {isReady && companyIntel?.fallback_label && (
                            <span
                              style={{
                                padding: '2px 8px',
                                borderRadius: '6px',
                                border: '1px solid var(--border)',
                                background: 'var(--bg-card)',
                                color: 'var(--brand)',
                                fontSize: '11px',
                                fontWeight: 600,
                              }}
                            >
                              {companyIntel.fallback_label}
                            </span>
                          )}
                          {isError && !isShowingOlderBrief && lastAttemptTime && (
                            <span>{formatAttemptTime(lastAttemptTime)}</span>
                          )}
                          {cooldownSeconds > 0 && (
                            <span style={{ color: 'var(--brand)', fontSize: '11px', fontWeight: 600 }} aria-live="polite">
                              Refresh available in {cooldownSeconds}s
                            </span>
                          )}
                        </div>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <button
                          ref={refreshBtnRef}
                          type="button"
                          onClick={() => loadCompanyIntelData(true)}
                          disabled={loadingIntel || cooldownSeconds > 0}
                          className="radar-card-btn radar-card-btn-secondary"
                          aria-label="Refresh company intelligence"
                        >
                          <RefreshCw size={14} className={loadingIntel ? 'spin' : ''} strokeWidth={1.8} aria-hidden="true" />
                          <span>{loadingIntel ? 'Updating…' : cooldownSeconds > 0 ? `Refresh in ${cooldownSeconds}s` : 'Refresh Intel'}</span>
                        </button>
                      </div>
                    </div>

                    {/* Accessible Live Announcement */}
                    <div className="sr-only" aria-live="polite">
                      {loadingIntel ? 'Updating company intelligence report...' : isReady ? 'Company intelligence report ready.' : ''}
                    </div>

                    {/* Notification banner when showing older brief after failed refresh */}
                    {isShowingOlderBrief && companyIntel?.generated_at && (
                      <div
                        style={{
                          padding: '10px 14px',
                          borderRadius: '6px',
                          background: 'var(--bg-app)',
                          border: '1px solid var(--border)',
                          fontSize: '12px',
                          color: 'var(--text-secondary)',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                        }}
                      >
                        <AlertCircle size={14} style={{ color: 'var(--brand)', flexShrink: 0 }} aria-hidden="true" />
                        <span>Latest refresh failed. Showing the brief from {formatBriefDateOnly(companyIntel.generated_at)}.</span>
                      </div>
                    )}

                    {/* Loading Skeleton */}
                    {(loadingIntel || (!intelRequested && !companyIntel)) ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }} aria-busy="true">
                        <div
                          style={{
                            padding: '12px 16px',
                            borderRadius: '6px',
                            background: 'var(--bg-app)',
                            border: '1px solid var(--border)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '4px',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <RefreshCw size={14} className="spin" style={{ color: 'var(--brand)', flexShrink: 0 }} aria-hidden="true" />
                            <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                              Researching {opportunity?.company_name || 'company'}...
                            </span>
                          </div>
                          {coldStartPending && (
                            <span style={{ fontSize: '12px', color: 'var(--text-secondary)', marginLeft: '24px' }}>
                              Waking up the server, this can take up to a minute
                            </span>
                          )}
                        </div>
                        <div
                          style={{
                            padding: '16px',
                            borderRadius: '6px',
                            background: 'var(--bg-app)',
                            border: '1px solid var(--border)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '8px',
                          }}
                        >
                          <div style={{ height: '14px', width: '92%', background: 'var(--border)', borderRadius: '4px' }} />
                          <div style={{ height: '14px', width: '70%', background: 'var(--border)', borderRadius: '4px' }} />
                        </div>
                        <div className="company-intel-grid">
                          {[1, 2, 3, 4].map((i) => (
                            <div
                              key={i}
                              style={{
                                padding: '16px',
                                borderRadius: '6px',
                                background: 'var(--bg-app)',
                                border: '1px solid var(--border)',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '10px',
                              }}
                            >
                              <div style={{ height: '14px', width: '50%', background: 'var(--border)', borderRadius: '4px' }} />
                              <div style={{ height: '12px', width: '85%', background: 'var(--border)', borderRadius: '4px' }} />
                              <div style={{ height: '12px', width: '65%', background: 'var(--border)', borderRadius: '4px' }} />
                            </div>
                          ))}
                        </div>
                        <div style={{ height: '38px', background: 'var(--bg-app)', border: '1px solid var(--border)', borderRadius: '6px' }} />
                      </div>
                    ) : isError && !isShowingOlderBrief ? (
                      /* Error State */
                      <div
                        style={{
                          padding: '32px 20px',
                          borderRadius: '6px',
                          background: 'var(--bg-app)',
                          border: '1px solid var(--border)',
                          textAlign: 'center',
                        }}
                        role="alert"
                        aria-live="assertive"
                      >
                        <p style={{ margin: '0 0 16px 0', fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                          {intelError || companyIntel?.error || "We couldn't generate company intel right now. Please try again with Refresh Intel."}
                        </p>
                        <button
                          type="button"
                          onClick={() => loadCompanyIntelData(true)}
                          disabled={loadingIntel || cooldownSeconds > 0}
                          className="radar-card-btn radar-card-btn-secondary"
                          style={{ margin: '0 auto', display: 'inline-flex', alignItems: 'center', gap: '6px', minHeight: '36px', padding: '6px 14px' }}
                          aria-label="Refresh company intelligence"
                        >
                          <RefreshCw size={13} className={loadingIntel ? 'spin' : ''} aria-hidden="true" />
                          <span>Refresh Intel</span>
                        </button>
                      </div>
                    ) : isEmptyInfo && !isShowingOlderBrief ? (
                      /* Empty / Not enough info state */
                      <div
                        style={{
                          padding: '32px 20px',
                          borderRadius: '6px',
                          background: 'var(--bg-app)',
                          border: '1px solid var(--border)',
                          textAlign: 'center',
                        }}
                      >
                        <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-secondary)' }}>
                          {companyIntel?.message || 'We could not find enough reliable information about this company. You can try refreshing intel.'}
                        </p>
                      </div>
                    ) : isOldBrief ? (
                      /* Old Brief Fallback */
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                        <div
                          style={{
                            padding: '12px 16px',
                            borderRadius: '6px',
                            background: 'var(--bg-app)',
                            border: '1px solid var(--border)',
                            fontSize: '12px',
                            color: 'var(--text-muted)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            flexWrap: 'wrap',
                            gap: '8px',
                          }}
                        >
                          <span>This summary is from an older version. Refresh Intel for a clearer one.</span>
                          <button
                            type="button"
                            onClick={() => loadCompanyIntelData(true)}
                            disabled={cooldownSeconds > 0}
                            style={{
                              background: 'transparent',
                              border: 'none',
                              color: 'var(--brand)',
                              fontWeight: 600,
                              cursor: 'pointer',
                              padding: 0,
                              fontSize: '12px',
                              textDecoration: 'underline',
                            }}
                          >
                            {cooldownSeconds > 0 ? `Refresh in ${cooldownSeconds}s` : 'Refresh now'}
                          </button>
                        </div>
                        {oldItems.length > 0 && (
                          <div
                            style={{
                              padding: '16px',
                              borderRadius: '6px',
                              background: 'var(--bg-app)',
                              border: '1px solid var(--border)',
                            }}
                          >
                            <h3 style={{ margin: '0 0 12px 0', fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>
                              Overview points
                            </h3>
                            <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                              {oldItems.map((item, idx) => (
                                <li key={idx} style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                                  {item}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    ) : companyIntel ? (
                      /* Modern Clean Structured Brief */
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                        {/* Summary */}
                        {companyIntel.summary && (
                          <div
                            style={{
                              padding: '16px 18px',
                              borderRadius: '6px',
                              background: 'var(--bg-app)',
                              border: '1px solid var(--border)',
                            }}
                          >
                            <p
                              style={{
                                margin: 0,
                                fontSize: '15px',
                                lineHeight: 1.6,
                                color: 'var(--text-primary)',
                                fontWeight: 500,
                                overflowWrap: 'break-word',
                                wordBreak: 'break-word',
                              }}
                            >
                              {companyIntel.summary}
                            </p>
                          </div>
                        )}

                        {/* Four Sections Grid */}
                        {sections.length > 0 && (
                          <div
                            className={sections.length >= 2 ? 'company-intel-grid' : ''}
                            style={sections.length === 1 ? { display: 'grid', gridTemplateColumns: '1fr', gap: '16px' } : undefined}
                          >
                            {sections.map((sec) => (
                              <div
                                key={sec.key}
                                style={{
                                  padding: '16px',
                                  borderRadius: '6px',
                                  background: 'var(--bg-app)',
                                  border: '1px solid var(--border)',
                                  overflowWrap: 'break-word',
                                  wordBreak: 'break-word',
                                }}
                              >
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                                  <sec.icon size={16} strokeWidth={1.8} style={{ color: 'currentColor', flexShrink: 0 }} aria-hidden="true" />
                                  <h3 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>
                                    {sec.title}
                                  </h3>
                                </div>
                                <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                  {sec.points.map((p, idx) => (
                                    <li
                                      key={idx}
                                      style={{
                                        fontSize: '13px',
                                        color: 'var(--text-secondary)',
                                        lineHeight: 1.5,
                                        overflowWrap: 'break-word',
                                        wordBreak: 'break-word',
                                      }}
                                    >
                                      <span>{p.point}</span>
                                      {p.source && (
                                        <button
                                          type="button"
                                          onClick={() => handleJumpToSource(p.source)}
                                          aria-label={`View source ${p.source}`}
                                          style={{
                                            display: 'inline-block',
                                            marginLeft: '6px',
                                            padding: '0 4px',
                                            fontSize: '11px',
                                            fontWeight: 700,
                                            color: 'var(--brand)',
                                            background: 'transparent',
                                            border: 'none',
                                            cursor: 'pointer',
                                            textDecoration: 'underline',
                                            verticalAlign: 'baseline',
                                          }}
                                        >
                                          [{p.source}]
                                        </button>
                                      )}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Collapsible Sources Section */}
                        {companyIntel.sources && companyIntel.sources.length > 0 && (
                          <div
                            id="company-intel-sources-section"
                            style={{
                              borderRadius: '6px',
                              border: '1px solid var(--border)',
                              background: 'var(--bg-app)',
                              overflow: 'hidden',
                            }}
                          >
                            <button
                              type="button"
                              onClick={() => setSourcesExpanded(!sourcesExpanded)}
                              aria-expanded={sourcesExpanded}
                              aria-controls="company-intel-sources-list"
                              style={{
                                width: '100%',
                                padding: '12px 16px',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                background: 'transparent',
                                border: 'none',
                                color: 'var(--text-primary)',
                                fontSize: '13px',
                                fontWeight: 600,
                                cursor: 'pointer',
                                textAlign: 'left',
                              }}
                            >
                              <span>Sources ({companyIntel.sources.length})</span>
                              {sourcesExpanded ? <ChevronUp size={16} aria-hidden="true" /> : <ChevronDown size={16} aria-hidden="true" />}
                            </button>
                            {sourcesExpanded && (
                              <ul
                                id="company-intel-sources-list"
                                style={{
                                  margin: 0,
                                  padding: '12px 16px 16px 16px',
                                  borderTop: '1px solid var(--border)',
                                  display: 'flex',
                                  flexDirection: 'column',
                                  gap: '8px',
                                  listStyle: 'none',
                                }}
                              >
                                {companyIntel.sources.map((src) => {
                                  const safeUrl = getSafeHttpUrl(src.url)
                                  return (
                                  <li
                                    key={src.id}
                                    id={`intel-source-${src.id}`}
                                    style={{
                                      fontSize: '12px',
                                      lineHeight: 1.5,
                                      padding: '6px 8px',
                                      borderRadius: '6px',
                                      background: highlightedSourceId === src.id ? 'var(--bg-card)' : 'transparent',
                                      transition: 'background 0.2s',
                                      display: 'flex',
                                      alignItems: 'baseline',
                                      gap: '6px',
                                    }}
                                  >
                                    <span style={{ fontWeight: 700, color: 'var(--brand)', flexShrink: 0 }}>[{src.id}]</span>
                                    {safeUrl ? (
                                      <a
                                        href={safeUrl}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        aria-label={`Source ${src.id}: ${src.title} on ${src.domain} (opens in new tab)`}
                                        style={{
                                          color: 'var(--text-primary)',
                                          textDecoration: 'none',
                                          wordBreak: 'break-word',
                                        }}
                                        onMouseEnter={(e) => (e.currentTarget.style.textDecoration = 'underline')}
                                        onMouseLeave={(e) => (e.currentTarget.style.textDecoration = 'none')}
                                      >
                                        <span>{src.title}</span>
                                        {src.domain && <span style={{ color: 'var(--text-muted)', marginLeft: '6px' }}>({src.domain})</span>}
                                        <ExternalLink size={11} style={{ marginLeft: '4px', verticalAlign: 'middle', display: 'inline-block' }} aria-hidden="true" />
                                      </a>
                                    ) : (
                                      <span style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>
                                        <span>{src.title}</span>
                                        {src.domain && <span style={{ color: 'var(--text-muted)', marginLeft: '6px' }}>({src.domain})</span>}
                                      </span>
                                    )}
                                  </li>
                                  )
                                })}
                              </ul>
                            )}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div style={{ textAlign: 'center', padding: '32px 0', color: 'var(--text-muted)', fontSize: '13px' }}>
                        Intelligence report unavailable.
                      </div>
                    )}
                  </div>
                )
              })()}

              {/* TAB: Role & Match Overview */}
              {activeTab === 'overview' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                  <div
                    style={{
                      padding: '14px 18px',
                      borderRadius: '10px',
                      background: 'var(--bg-app)',
                      border: '1px solid var(--border)',
                    }}
                  >
                    <h3 style={{ margin: '0 0 8px 0', fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
                      Role Description & Verified Requirements
                    </h3>
                    <p style={{ margin: '0 0 12px 0', fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                      {opportunity.description || 'Verified opportunity description is retrieved directly from official career postings.'}
                    </p>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      {requiredSkills.length > 0 ? (
                        requiredSkills.map((sk, idx) => (
                          <span
                            key={idx}
                            style={{
                              padding: '4px 10px',
                              borderRadius: '6px',
                              background: 'var(--bg-card)',
                              border: '1px solid var(--border)',
                              fontSize: '12px',
                              fontWeight: 600,
                              color: 'var(--text-primary)',
                            }}
                          >
                            {sk}
                          </span>
                        ))
                      ) : skillMatch.status === 'loading' ? (
                        <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                          Checking this posting's requirements…
                        </span>
                      ) : skillMatch.status === 'unavailable' ? (
                        <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                          Requirements unavailable: the analysis could not be loaded.
                        </span>
                      ) : (
                        <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                          No explicit prerequisite technical skills mandated for this role.
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Factual Integrity & Match Analysis Card */}
                  <div
                    style={{
                      padding: '16px 18px',
                      borderRadius: '10px',
                      background: 'var(--bg-app)',
                      border: '1px solid var(--border)',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                      <h3 style={{ margin: 0, fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
                        🎯 Factual Match Analysis
                      </h3>
                      <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                        Calculated deterministically from verified profile background
                      </span>
                    </div>

                    {skillMatch.status !== 'ready' ? (
                      <div
                        id="factual-match-pending"
                        style={{ padding: '14px 16px', borderRadius: '8px', background: 'var(--bg-card)', border: '1px solid var(--border)', fontSize: '12px', color: 'var(--text-secondary)' }}
                      >
                        {skillMatch.status === 'loading'
                          ? 'Checking your skills against this posting…'
                          : 'Skill match unavailable: the analysis could not be loaded. Open the Job Analysis tab to retry.'}
                      </div>
                    ) : requiredSkills.length === 0 || skillMatch.required.length === 0 ? (
                      <div
                        id="factual-match-general-role"
                        style={{
                          padding: '14px 16px',
                          borderRadius: '8px',
                          background: '#f8fafc',
                          border: '1px solid var(--border)',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '12px',
                        }}
                      >
                        <span style={{ fontSize: '20px' }}>📋</span>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontWeight: 700, fontSize: '13px', color: 'var(--text-primary)', marginBottom: '3px' }}>
                            General Qualification Opportunity: No Mandatory Tech Stack
                          </div>
                          <div style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                            This employer posting does not list strict prerequisite skills. Evaluated holistically on candidate projects, leadership, and domain alignment.
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '14px' }}>
                        <div style={{ padding: '12px', borderRadius: '8px', background: '#f0fdf4', border: '1px solid #bbf7d0' }}>
                          <div style={{ fontWeight: 700, fontSize: '12px', color: '#166534', marginBottom: '6px' }}>
                            ✓ Verified Matching Skills ({matchedSkills.length})
                          </div>
                          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                            {matchedSkills.length > 0 ? (
                              matchedSkills.map((sk, i) => (
                                <span key={i} style={{ background: '#ffffff', color: '#15803d', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 600, border: '1px solid #bbf7d0' }}>
                                  {sk}
                                </span>
                              ))
                            ) : (
                              <span style={{ fontSize: '12px', color: '#166534' }}>Add relevant skills to your profile to match.</span>
                            )}
                          </div>
                        </div>

                        {missingSkills.length === 0 ? (
                          <div style={{ padding: '12px', borderRadius: '8px', background: '#f0fdf4', border: '1px solid #bbf7d0' }}>
                            <div style={{ fontWeight: 700, fontSize: '12px', color: '#166534', marginBottom: '6px' }}>
                              ✓ All Role Requirements Verified! ({matchedSkills.length}/{skillMatch.required.length})
                            </div>
                            <span style={{ fontSize: '12px', color: '#15803d' }}>
                              100% of required skills found in your verified master profile!
                            </span>
                          </div>
                        ) : (
                          <div style={{ padding: '12px', borderRadius: '8px', background: '#fffbeb', border: '1px solid #fde68a' }}>
                            <div style={{ fontWeight: 700, fontSize: '12px', color: '#b45309', marginBottom: '6px' }}>
                              ⚠️ Unverified or Missing Skills ({missingSkills.length})
                            </div>
                            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                              {missingSkills.map((sk, i) => (
                                <span key={i} style={{ background: '#ffffff', color: '#b45309', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 600, border: '1px solid #fde68a' }}>
                                  {sk}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    <div style={{ marginTop: '14px', fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.5, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span>🛡️ <strong>Zero Hallucination Guarantee:</strong> Tailored resumes strictly derived from verified profile background.</span>
                      <button
                        type="button"
                        onClick={() => setActiveTab('job_analysis')}
                        style={{
                          padding: '4px 10px',
                          borderRadius: '6px',
                          background: 'transparent',
                          border: '1px solid var(--border)',
                          color: 'var(--brand)',
                          fontSize: '11px',
                          fontWeight: 700,
                          cursor: 'pointer',
                        }}
                      >
                        Deep Requirement Breakdown →
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* TAB: Deep Job Description Analysis & Evidence Match (Phase 5) */}
              {activeTab === 'job_analysis' && !workspaceError && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
                  {/* Top Match Score & Verdict Card */}
                  <div
                    style={{
                      padding: '18px 20px',
                      borderRadius: '12px',
                      background: 'var(--bg-app)',
                      border: '1px solid var(--border)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      flexWrap: 'wrap',
                      gap: '16px',
                    }}
                  >
                    <div>
                      <div style={{ fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-muted)', marginBottom: '4px' }}>
                        Deterministic Requirement Alignment
                      </div>
                      <h3 style={{ margin: '0 0 6px 0', fontSize: '18px', fontWeight: 800, color: 'var(--text-primary)' }}>
                        {opportunity.role_title} @ {opportunity.company_name}
                      </h3>
                      <div style={{ fontSize: '13px', color: 'var(--text-secondary)', maxWidth: '600px', lineHeight: 1.5 }}>
                        {jobAnalysis?.summary_verdict || (loadingAnalysis ? 'Analyzing requirements against candidate master profile…' : analysisError ? 'Could not load the analysis' : 'Requirement analysis ready.')}
                      </div>
                      {analysisError && (
                        <div
                          id="job-analysis-error"
                          role="alert"
                          style={{ marginTop: '8px', display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', fontSize: '12px', color: '#991b1b' }}
                        >
                          <span>
                            {jobAnalysis ? `Re-analysis failed (showing the previous report): ${analysisError}` : `Could not load the analysis: ${analysisError}`}
                          </span>
                          <button
                            type="button"
                            onClick={() => loadJobAnalysisData(jobAnalysis ? customJobDesc : null)}
                            disabled={loadingAnalysis}
                            style={{ padding: '3px 10px', borderRadius: '6px', border: '1px solid #fecaca', background: '#ffffff', color: '#991b1b', fontWeight: 700, fontSize: '11px', cursor: loadingAnalysis ? 'not-allowed' : 'pointer' }}
                          >
                            Retry
                          </button>
                        </div>
                      )}
                    </div>

                    <div
                      style={{
                        padding: '12px 20px',
                        borderRadius: '10px',
                        background: 'var(--bg-card)',
                        border: '1px solid var(--border)',
                        textAlign: 'center',
                      }}
                    >
                      <div
                        style={{
                          fontSize: '26px',
                          fontWeight: 800,
                          color: matchScoreView.color,
                        }}
                      >
                        {loadingAnalysis && !jobAnalysis ? '…' : analysisError && !jobAnalysis ? '?' : matchScoreView.text}
                      </div>
                      {matchScoreView.caption && !loadingAnalysis && (
                        <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '2px' }}>{matchScoreView.caption}</div>
                      )}
                      <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                        Match Score
                      </div>
                    </div>
                  </div>

                  {/* Missing Critical Skills Alert */}
                  {jobAnalysis?.missing_critical_skills && jobAnalysis.missing_critical_skills.length > 0 && (
                      <div style={{ padding: '12px 16px', borderRadius: '8px', background: '#fef2f2', border: '1px solid #fecaca', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', fontSize: '13px', color: '#991b1b', lineHeight: 1.4 }}>
                          <span style={{ fontSize: '18px' }}>⚠️</span>
                          <div>
                            <strong>Missing Mandatory Qualifications:</strong>{' '}
                            {jobAnalysis.missing_critical_skills.join(', ')}. If you possess these, update your master profile before submitting.
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={handleFixInProfile}
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: '#991b1b',
                            fontWeight: '700',
                            cursor: 'pointer',
                            fontSize: '12px',
                            textDecoration: 'underline',
                            padding: '4px 8px'
                          }}
                        >
                          Fix in Profile
                        </button>
                      </div>
                  )}

                  {/* Job Description Fine-Tuner */}
                  <div
                    style={{
                      padding: '14px 18px',
                      borderRadius: '10px',
                      background: 'var(--bg-app)',
                      border: '1px solid var(--border)',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                      <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary)' }}>
                        Detailed Job Description (Editable for custom postings)
                      </span>
                      <button
                        type="button"
                        onClick={() => loadJobAnalysisData(customJobDesc)}
                        disabled={loadingAnalysis}
                        style={{
                          padding: '5px 12px',
                          borderRadius: '6px',
                          background: 'var(--brand)',
                          color: '#ffffff',
                          border: 'none',
                          fontSize: '11px',
                          fontWeight: 700,
                          cursor: loadingAnalysis ? 'not-allowed' : 'pointer',
                        }}
                      >
                        {loadingAnalysis ? 'Analyzing…' : '🔄 Re-Analyze Alignment'}
                      </button>
                    </div>
                    <textarea
                      rows={4}
                      value={customJobDesc}
                      onChange={e => setCustomJobDesc(e.target.value)}
                      placeholder="Paste complete job description or eligibility requirements here to re-evaluate…"
                      style={{
                        width: '100%',
                        padding: '10px',
                        borderRadius: '6px',
                        border: '1px solid var(--border)',
                        background: 'var(--bg-card)',
                        color: 'var(--text-primary)',
                        fontSize: '12px',
                        fontFamily: 'monospace',
                        boxSizing: 'border-box',
                        resize: 'vertical',
                      }}
                    />
                  </div>

                  {/* Detailed Evidence Match Grid */}
                  <div
                    style={{
                      padding: '16px 18px',
                      borderRadius: '10px',
                      background: 'var(--bg-app)',
                      border: '1px solid var(--border)',
                    }}
                  >
                    <h4 style={{ margin: '0 0 12px 0', fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>
                      Requirement-by-Requirement Evidence Traceability
                    </h4>

                    {jobAnalysis?.matches && jobAnalysis.matches.length > 0 ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                        {jobAnalysis.matches.map((m, idx) => {
                          const statusConfig = {
                            supported: { bg: '#f0fdf4', text: '#166534', border: '#bbf7d0', icon: '✓', label: 'Supported' },
                            partial: { bg: '#eff6ff', text: '#1e40af', border: '#bfdbfe', icon: '~', label: 'Partial Match' },
                            missing_evidence: { bg: '#fffbeb', text: '#92400e', border: '#fde68a', icon: '?', label: 'Missing Evidence' },
                            gap: { bg: '#fef2f2', text: '#991b1b', border: '#fecaca', icon: '✗', label: 'Requirement Gap' },
                          }[m.match_status] || { bg: '#f1f5f9', text: '#475569', border: '#cbd5e1', icon: '•', label: m.match_status }

                          return (
                            <div
                              key={idx}
                              style={{
                                padding: '12px 14px',
                                borderRadius: '8px',
                                background: 'var(--bg-card)',
                                border: '1px solid var(--border)',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '6px',
                              }}
                            >
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px', flexWrap: 'wrap' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                  <span
                                    style={{
                                      padding: '2px 8px',
                                      borderRadius: '4px',
                                      fontSize: '10px',
                                      fontWeight: 800,
                                      textTransform: 'uppercase',
                                      background: statusConfig.bg,
                                      color: statusConfig.text,
                                      border: `1px solid ${statusConfig.border}`,
                                    }}
                                  >
                                    {statusConfig.icon} {statusConfig.label}
                                  </span>
                                  <span
                                    style={{
                                      fontSize: '10px',
                                      fontWeight: 700,
                                      padding: '2px 6px',
                                      borderRadius: '4px',
                                      background: m.is_mandatory ? '#fee2e2' : '#f1f5f9',
                                      color: m.is_mandatory ? '#991b1b' : '#475569',
                                      textTransform: 'uppercase',
                                    }}
                                  >
                                    {m.is_mandatory ? 'Mandatory' : 'Preferred'} {m.category}
                                  </span>
                                </div>
                                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                                  Confidence: {Math.round(m.confidence * 100)}%
                                </span>
                              </div>

                              <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                                {m.requirement}
                              </div>

                              {m.supporting_facts && m.supporting_facts.length > 0 && (
                                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', background: 'var(--bg-app)', padding: '6px 10px', borderRadius: '6px' }}>
                                  <strong>Verified Profile Evidence:</strong> {m.supporting_facts.join(' • ')}
                                </div>
                              )}

                              {m.reasoning && (
                                <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                                  {m.reasoning}
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    ) : (
                      <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--text-muted)', fontSize: '13px' }}>
                        {loadingAnalysis ? 'Extracting mandatory and preferred criteria…' : 'No requirements parsed. Paste detailed job description above.'}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* TAB 2: Tailored Resume Studio & ATS Preview */}
              {activeTab === 'resume' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
                    <div>
                      <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
                        {resume?.title || 'Tailored Application Resume'}
                      </h3>
                      <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                        Snapshot isolated for {opportunity.company_name}. Master resume remains unchanged.
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      <button
                        type="button"
                        onClick={handleTriggerTailor}
                        disabled={tailoring}
                        style={{
                          padding: '7px 14px',
                          borderRadius: '8px',
                          background: 'var(--bg-app)',
                          border: '1px solid var(--border)',
                          color: 'var(--text-primary)',
                          fontSize: '12px',
                          fontWeight: 600,
                          cursor: tailoring ? 'not-allowed' : 'pointer',
                        }}
                      >
                        {tailoring ? 'Tailoring with AI…' : '✨ Re-Tailor with AI'}
                      </button>
                      {resume?.id && (
                        <>
                          <button
                            type="button"
                            disabled={exportingDocx}
                            onClick={handleExportDocx}
                            style={{
                              padding: '7px 14px',
                              borderRadius: '8px',
                              background: 'var(--bg-app)',
                              border: '1px solid var(--border)',
                              color: 'var(--text-primary)',
                              fontSize: '12px',
                              fontWeight: 600,
                              cursor: exportingDocx ? 'not-allowed' : 'pointer',
                              opacity: exportingDocx ? 0.7 : 1,
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '6px',
                            }}
                          >
                            {exportingDocx ? '⏳ Downloading…' : '📥 Export Word (.docx)'}
                          </button>
                          <button
                            type="button"
                            disabled={exportingPrint}
                            onClick={handleExportPrint}
                            style={{
                              padding: '7px 14px',
                              borderRadius: '8px',
                              background: 'var(--brand)',
                              color: '#ffffff',
                              border: 'none',
                              fontSize: '12px',
                              fontWeight: 600,
                              cursor: exportingPrint ? 'not-allowed' : 'pointer',
                              opacity: exportingPrint ? 0.7 : 1,
                            }}
                          >
                            {exportingPrint ? '⏳ Generating PDF…' : '📄 Export ATS Resume (Print/PDF)'}
                          </button>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Factual Integrity Audit Card */}
                  {resume?.validation_report && (
                    <ValidationReportCard validationReport={resume.validation_report} />
                  )}

                  {/* Template Style Selector */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '10px 14px', borderRadius: '8px', background: 'var(--bg-app)', border: '1px solid var(--border)' }}>
                    <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>ATS Template Style:</span>
                    {[
                      { id: 'ats_classic', label: 'ATS Classic' },
                      { id: 'modern', label: 'Modern Clean' },
                      { id: 'minimal', label: 'Minimalist' },
                    ].map(t => (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() => setResumeTemplate(t.id)}
                        style={{
                          padding: '4px 10px',
                          borderRadius: '6px',
                          border: resumeTemplate === t.id ? '1px solid var(--brand)' : '1px solid var(--border)',
                          background: resumeTemplate === t.id ? 'var(--brand)' : 'var(--bg-card)',
                          color: resumeTemplate === t.id ? '#ffffff' : 'var(--text-primary)',
                          fontSize: '11px',
                          fontWeight: 600,
                          cursor: 'pointer',
                        }}
                      >
                        {t.label}
                      </button>
                    ))}
                  </div>

                  {/* In-line Resume Fine-Tuner */}
                  <div style={{ padding: '16px', borderRadius: '10px', background: 'var(--bg-app)', border: '1px solid var(--border)' }}>
                    <h4 style={{ margin: '0 0 12px 0', fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>
                      Fine-Tune Tailored Resume Details
                    </h4>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px', marginBottom: '12px' }}>
                      <div>
                        <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>Full Name</label>
                        <input
                          type="text"
                          value={fullName}
                          onChange={e => setFullName(e.target.value)}
                          style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px', boxSizing: 'border-box' }}
                        />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>Email</label>
                        <input
                          type="email"
                          value={email}
                          onChange={e => setEmail(e.target.value)}
                          style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px', boxSizing: 'border-box' }}
                        />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>Phone</label>
                        <input
                          type="text"
                          value={phone}
                          onChange={e => setPhone(e.target.value)}
                          style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px', boxSizing: 'border-box' }}
                        />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>Location</label>
                        <input
                          type="text"
                          value={location}
                          onChange={e => setLocation(e.target.value)}
                          style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px', boxSizing: 'border-box' }}
                        />
                      </div>
                    </div>

                    <div style={{ marginBottom: '12px' }}>
                      <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>Professional Summary</label>
                      <textarea
                        rows={3}
                        value={summary}
                        onChange={e => setSummary(e.target.value)}
                        style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px', boxSizing: 'border-box' }}
                      />
                    </div>

                    <div style={{ marginBottom: '14px' }}>
                      <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>Skills (comma separated)</label>
                      <input
                        type="text"
                        value={skillsText}
                        onChange={e => setSkillsText(e.target.value)}
                        style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px', boxSizing: 'border-box' }}
                      />
                    </div>

                    <button
                      type="button"
                      onClick={handleSaveResumeEdits}
                      disabled={savingResume}
                      style={{
                        padding: '8px 18px',
                        borderRadius: '7px',
                        background: 'var(--brand)',
                        color: '#ffffff',
                        border: 'none',
                        fontSize: '12px',
                        fontWeight: 600,
                        cursor: savingResume ? 'not-allowed' : 'pointer',
                      }}
                    >
                      {savingResume ? 'Saving…' : 'Save Resume Updates'}
                    </button>
                  </div>
                </div>
              )}

              {/* TAB 3: Truthful Cover Letter Generator & Editor */}
              {activeTab === 'cover_letter' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
                    <div>
                      <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
                        Tailored Cover Letter
                      </h3>
                      <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                        Crafted specifically for {opportunity.company_name} using your verified projects.
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button
                        type="button"
                        onClick={handleGenerateCoverLetter}
                        disabled={draftingLetter}
                        style={{
                          padding: '7px 14px',
                          borderRadius: '8px',
                          background: 'var(--bg-app)',
                          border: '1px solid var(--border)',
                          color: 'var(--text-primary)',
                          fontSize: '12px',
                          fontWeight: 600,
                          cursor: draftingLetter ? 'not-allowed' : 'pointer',
                        }}
                      >
                        {draftingLetter ? 'Generating…' : '✨ Generate with AI'}
                      </button>
                      <button
                        type="button"
                        onClick={handleSaveCoverLetter}
                        disabled={savingLetter}
                        style={{
                          padding: '7px 14px',
                          borderRadius: '8px',
                          background: 'var(--brand)',
                          color: '#ffffff',
                          border: 'none',
                          fontSize: '12px',
                          fontWeight: 600,
                          cursor: savingLetter ? 'not-allowed' : 'pointer',
                        }}
                      >
                        {savingLetter ? 'Saving…' : 'Save Letter'}
                      </button>
                    </div>
                  </div>

                  <textarea
                    rows={12}
                    value={coverLetterText}
                    onChange={e => setCoverLetterText(e.target.value)}
                    placeholder="Click 'Generate with AI' to draft a truthful cover letter from your verified background..."
                    style={{
                      width: '100%',
                      padding: '14px',
                      borderRadius: '10px',
                      border: '1px solid var(--border)',
                      background: 'var(--bg-app)',
                      color: 'var(--text-primary)',
                      fontSize: '13px',
                      lineHeight: 1.6,
                      boxSizing: 'border-box',
                      fontFamily: 'inherit',
                    }}
                  />
                </div>
              )}

              {/* TAB 4: Checklist & Status Tracker */}
              {activeTab === 'checklist' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                  {/* Preparation Checklist */}
                  <div style={{ padding: '16px', borderRadius: '10px', background: 'var(--bg-app)', border: '1px solid var(--border)' }}>
                    <h3 style={{ margin: '0 0 12px 0', fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
                      Local checklist (not saved)
                    </h3>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                      {[
                        { key: 'resumeTailored', label: 'Tailored resume generated & verified against master' },
                        { key: 'resumeDownloaded', label: 'ATS-formatted resume PDF previewed / downloaded' },
                        { key: 'coverLetterDrafted', label: 'Personalized cover letter reviewed & saved' },
                        { key: 'questionsReviewed', label: 'Required qualifications & application answers reviewed' },
                        { key: 'submittedExternally', label: 'Submitted on official employer portal (if required)' },
                      ].map(item => (
                        <label
                          key={item.key}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '10px',
                            fontSize: '13px',
                            color: 'var(--text-primary)',
                            cursor: 'pointer',
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={Boolean(checklist[item.key])}
                            onChange={e => setChecklist(prev => ({ ...prev, [item.key]: e.target.checked }))}
                            style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                          />
                          <span>{item.label}</span>
                        </label>
                      ))}
                    </div>
                  </div>

                  {/* Status Tracker & Notes */}
                  <div style={{ padding: '16px', borderRadius: '10px', background: 'var(--bg-app)', border: '1px solid var(--border)' }}>
                    <h3 style={{ margin: '0 0 12px 0', fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
                      Track Application Status & Deadlines
                    </h3>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px', marginBottom: '14px' }}>
                      <div>
                        <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>Pipeline Status</label>
                        <select
                          value={appStatus}
                          onChange={e => setAppStatus(e.target.value)}
                          style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px' }}
                        >
                          {buildStatusOptions(appStatus, { useLowerCase: true }).map(opt => (
                            <option key={opt.value} value={opt.value}>
                              {opt.value === 'submitted' ? 'Applied / Submitted Externally (self-reported)' : opt.label}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>Personal Target Deadline</label>
                        <input
                          type="date"
                          value={targetDeadline}
                          onChange={e => setTargetDeadline(e.target.value)}
                          style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px', boxSizing: 'border-box' }}
                        />
                      </div>
                    </div>

                    <div style={{ marginBottom: '14px' }}>
                      <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>Private Candidate Notes</label>
                      <textarea
                        rows={3}
                        value={privateNotes}
                        onChange={e => setPrivateNotes(e.target.value)}
                        placeholder="Add personal interview dates, recruiter contacts, or application notes..."
                        style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px', boxSizing: 'border-box' }}
                      />
                    </div>

                    <button
                      type="button"
                      onClick={() => handleUpdateApplicationRecord(appStatus)}
                      disabled={savingStatus}
                      style={{
                        padding: '8px 18px',
                        borderRadius: '7px',
                        background: 'var(--brand)',
                        color: '#ffffff',
                        border: 'none',
                        fontSize: '12px',
                        fontWeight: 600,
                        cursor: savingStatus ? 'not-allowed' : 'pointer',
                      }}
                    >
                      {savingStatus ? 'Saving…' : 'Save Status & Notes'}
                    </button>
                  </div>
                </div>
              )}

              {/* TAB 5: Official Submission Handoff */}
              {activeTab === 'handoff' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                  <div style={{ padding: '16px', borderRadius: '10px', background: 'var(--bg-app)', border: '1px solid var(--border)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                      <span style={{ fontSize: '18px' }}>🌐</span>
                      <h3 style={{ margin: 0, fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
                        Official Employer Application Portal
                      </h3>
                    </div>
                    <p style={{ margin: '0 0 16px 0', fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                      {safeApplyUrl
                        ? `${opportunity.company_name} accepts applications through its own career portal. Compass prepares your truthful documents and prefilled answers to make completion fast and accurate.`
                        : "Compass prepares your truthful documents and prefilled answers. Submit them on the employer's own site; Compass has not verified an official application URL for this role."}
                    </p>

                    {safeApplyUrl ? (
                      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
                        <a
                          href={safeApplyUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '6px',
                            padding: '10px 18px',
                            borderRadius: '8px',
                            background: 'var(--brand)',
                            color: '#ffffff',
                            fontWeight: 600,
                            fontSize: '13px',
                            textDecoration: 'none',
                          }}
                        >
                          <span>Open Employer Application Portal</span>
                          <span>↗</span>
                        </a>

                        <button
                          type="button"
                          onClick={handleConfirmExternalSubmission}
                          disabled={savingStatus}
                          style={{
                            padding: '10px 18px',
                            borderRadius: '8px',
                            background: appStatus === 'submitted' ? '#dcfce7' : 'var(--bg-card)',
                            color: appStatus === 'submitted' ? '#166534' : 'var(--text-primary)',
                            border: '1px solid var(--border)',
                            fontWeight: 600,
                            fontSize: '13px',
                            cursor: savingStatus ? 'not-allowed' : 'pointer',
                            opacity: savingStatus ? 0.6 : 1,
                          }}
                        >
                          {appStatus === 'submitted' ? '✓ You marked this as submitted' : 'I submitted this externally'}
                        </button>
                      </div>
                    ) : (
                      <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                        {NO_APPLICATION_URL_TEXT}
                      </div>
                    )}
                  </div>

                  {/* Fast Copy-Paste Application Helper */}
                  <div style={{ padding: '16px', borderRadius: '10px', background: 'var(--bg-app)', border: '1px solid var(--border)' }}>
                    <h4 style={{ margin: '0 0 10px 0', fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>
                      Quick Copy Tools for Portal Questions
                    </h4>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      <button
                        type="button"
                        onClick={() => handleCopy('Summary', summary)}
                        style={{ padding: '6px 12px', borderRadius: '6px', background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-primary)', fontSize: '12px', cursor: 'pointer' }}
                      >
                        📋 Copy Summary
                      </button>
                      <button
                        type="button"
                        onClick={() => handleCopy('Skills', skillsText)}
                        style={{ padding: '6px 12px', borderRadius: '6px', background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-primary)', fontSize: '12px', cursor: 'pointer' }}
                      >
                        📋 Copy Skills
                      </button>
                      <button
                        type="button"
                        onClick={() => handleCopy('Cover letter', coverLetterText)}
                        style={{ padding: '6px 12px', borderRadius: '6px', background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-primary)', fontSize: '12px', cursor: 'pointer' }}
                      >
                        📋 Copy Cover Letter
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Modal Footer Controls */}
        <div
          style={{
            padding: '14px 24px',
            borderTop: '1px solid var(--border)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: 'var(--bg-app)',
          }}
        >
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Application ID: {application?.id ? `#${application.id}` : 'Preparing…'}
          </div>

          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              type="button"
              onClick={onClose}
              style={{
                padding: '8px 16px',
                borderRadius: '8px',
                border: '1px solid var(--border)',
                background: 'var(--bg-card)',
                color: 'var(--text-primary)',
                fontSize: '13px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Done & Return to Radar
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
