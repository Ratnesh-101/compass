import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Radar, RefreshCw, Loader2, ArrowDown, Info, X } from 'lucide-react'
import RadarOverviewCards from './radar/RadarOverviewCards'
import RadarFilters from './radar/RadarFilters'
import RadarOpportunityCard from './radar/RadarOpportunityCard'
import RadarDetailModal from './radar/RadarDetailModal'

const ApplicationWorkspaceModal = React.lazy(() => import('./career/ApplicationWorkspaceModal'))
import {
  fetchOpportunities,
  fetchRecommendedOpportunities,
  fetchOpenOpportunities,
  fetchUpcomingOpportunities,
  fetchRadarAnalytics,
  fetchWatchlist,
  fetchApplications,
  saveOpportunity,
  unsaveOpportunity,
  updateApplication,
  fetchRadarProfile,
  verifyOpportunity,
} from '../api/radarApi'
import { hasSavedProfile } from '../utils/careerUiHelpers'

export function newestRefreshDate(opportunities) {
  let newest = null
  for (const opp of opportunities || []) {
    for (const raw of [opp?.last_verified_at, opp?.last_checked_at]) {
      const t = raw ? Date.parse(raw) : NaN
      if (!Number.isNaN(t) && (newest === null || t > newest)) newest = t
    }
  }
  return newest === null ? null : new Date(newest)
}

export default function InternshipRadar({
  refreshTrigger = 0,
  onRefreshComplete,
  onRefreshError,
  onOpenProfile,
  onNavigateToResumeStudio,
} = {}) {
  const handleGoToResumeStudio = onNavigateToResumeStudio || onOpenProfile
  const handleOpenCandidateProfile = onOpenProfile || onNavigateToResumeStudio
  const [activeTab, setActiveTab] = useState('recommended')
  const [opportunities, setOpportunities] = useState([])
  const [stats, setStats] = useState(null)
  const [profile, setProfile] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('')
  const [selectedEmployerType, setSelectedEmployerType] = useState('')
  const [workArrangement, setWorkArrangement] = useState('')
  const [indiaOnly, setIndiaOnly] = useState(true)

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [isVerifying, setIsVerifying] = useState(false)
  const [isRefreshingMatches, setIsRefreshingMatches] = useState(false)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const isFirstMountRef = useRef(true)

  const [selectedDetailOpp, setSelectedDetailOpp] = useState(null)
  const [activeWorkspaceOpp, setActiveWorkspaceOpp] = useState(null)
  const [bannerDismissed, setBannerDismissed] = useState(false)

  const hasCandidateProfile = hasSavedProfile(profile)

  // Load analytics & profile
  const loadMetadata = useCallback(async () => {
    try {
      const [analyticsData, profileData] = await Promise.allSettled([
        fetchRadarAnalytics(),
        fetchRadarProfile(),
      ])
      if (analyticsData.status === 'fulfilled') setStats(analyticsData.value)
      if (profileData.status === 'fulfilled') setProfile(profileData.value)
    } catch (e) {
      console.warn('[Radar] Error fetching metadata:', e)
    }
  }, [])

  // Load list based on active tab and filters
  const loadOpportunities = useCallback(async (options = {}) => {
    const isBackground = options?.background === true
    const targetPage = options?.targetPage || 1
    const isAppending = options?.append === true

    if (!isBackground && !isAppending) {
      setLoading(true)
    }
    if (isAppending) {
      setIsLoadingMore(true)
    }
    setError(null)

    try {
      let items = []
      let serverHasMore = false

      if (activeTab === 'recommended') {
        items = await fetchRecommendedOpportunities(30, selectedEmployerType)
      } else if (activeTab === 'recent_24h') {
        const res = await fetchOpportunities({
          category: selectedCategory,
          employer_type: selectedEmployerType,
          work_arrangement: workArrangement,
          search: searchQuery,
          india_only: indiaOnly,
          page: 1,
          pageSize: 50,
        })
        const allOpps = res.opportunities || []
        // Strict 24h verified filter: strictly rely ONLY on backend is_verified_within_24h boolean
        items = allOpps.filter(o => o.is_verified_within_24h === true)
      } else if (activeTab === 'open') {
        items = await fetchOpenOpportunities({
          category: selectedCategory,
          employer_type: selectedEmployerType,
          work_arrangement: workArrangement,
          india_only: indiaOnly,
        })
      } else if (activeTab === 'upcoming') {
        items = await fetchUpcomingOpportunities()
      } else if (activeTab === 'watchlist') {
        items = await fetchWatchlist()
      } else if (activeTab === 'applications') {
        items = await fetchApplications()
      } else {
        // 'all'
        const res = await fetchOpportunities({
          category: selectedCategory,
          employer_type: selectedEmployerType,
          work_arrangement: workArrangement,
          search: searchQuery,
          india_only: indiaOnly,
          page: targetPage,
          pageSize: 24,
        })
        items = res.opportunities || []
        serverHasMore = Boolean(res.has_more)
      }

      // Client-side text search filter if tab is not 'all'
      if (activeTab !== 'all' && searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        items = items.filter(
          o =>
            o.company_name.toLowerCase().includes(q) ||
            o.role_title.toLowerCase().includes(q) ||
            (o.location && o.location.toLowerCase().includes(q))
        )
      }

      // Employer type filter for client-filtered tabs
      if (selectedEmployerType && activeTab !== 'all' && activeTab !== 'open' && activeTab !== 'recommended') {
        items = items.filter(o => o.employer_type === selectedEmployerType)
      }

      // Category filter for tabs other than 'all' and 'open'
      if (activeTab !== 'all' && activeTab !== 'open' && selectedCategory) {
        items = items.filter(o => o.category === selectedCategory)
      }

      // Work arrangement filter
      if (activeTab !== 'all' && activeTab !== 'open' && workArrangement) {
        items = items.filter(o => o.work_arrangement === workArrangement)
      }

      if (isAppending) {
        setOpportunities(prev => [...prev, ...items])
      } else {
        setOpportunities(items)
      }
      setHasMore(serverHasMore)
      setPage(targetPage)
    } catch (err) {
      console.error('[Radar] Error fetching opportunities:', err)
      if (!isBackground) {
        setError(err.message || 'Failed to load opportunities.')
      } else {
        throw err
      }
    } finally {
      if (!isBackground && !isAppending) {
        setLoading(false)
      }
      setIsLoadingMore(false)
    }
  }, [activeTab, selectedCategory, selectedEmployerType, workArrangement, searchQuery, indiaOnly])

  // Asynchronous background refresh for recommendation and eligibility updates
  const handleBackgroundRefresh = useCallback(async () => {
    setIsRefreshingMatches(true)
    try {
      await Promise.all([
        loadMetadata(),
        loadOpportunities({ background: true }),
      ])
      if (typeof onRefreshComplete === 'function') {
        onRefreshComplete()
      }
    } catch (err) {
      console.error('[Radar] Background refresh failed:', err)
      if (typeof onRefreshError === 'function') {
        onRefreshError(err)
      }
    } finally {
      setIsRefreshingMatches(false)
    }
  }, [loadMetadata, loadOpportunities, onRefreshComplete, onRefreshError])

  useEffect(() => {
    if (isFirstMountRef.current) {
      isFirstMountRef.current = false
      return
    }
    if (refreshTrigger > 0) {
      handleBackgroundRefresh()
    }
  }, [refreshTrigger, handleBackgroundRefresh])

  useEffect(() => {
    loadMetadata()
  }, [loadMetadata])

  useEffect(() => {
    loadOpportunities()
  }, [loadOpportunities])

  // Save / Bookmark toggle
  const handleToggleSave = async (id, isCurrentlySaved) => {
    try {
      if (isCurrentlySaved) {
        await unsaveOpportunity(id)
      } else {
        await saveOpportunity(id)
      }
      setOpportunities(prev =>
        prev.map(o => (o.id === id ? { ...o, is_saved: !isCurrentlySaved } : o))
      )
      loadMetadata()
    } catch (err) {
      console.error('Error toggling save:', err)
    }
  }

  // Application tracker update
  const handleUpdateApplication = async (id, payload) => {
    await updateApplication(id, payload)
    setOpportunities(prev =>
      prev.map(o => (o.id === id ? { ...o, application_status: payload.application_status } : o))
    )
    if (selectedDetailOpp && selectedDetailOpp.id === id) {
      setSelectedDetailOpp(prev => ({
        ...prev,
        application_status: payload.application_status,
        personal_deadline: payload.personal_deadline,
        private_notes: payload.private_notes,
      }))
    }
    loadMetadata()
  }

  // Live Official Re-verification
  const handleVerifyOpportunity = async id => {
    setIsVerifying(true)
    try {
      const res = await verifyOpportunity(id)
      setOpportunities(prev =>
        prev.map(o =>
          o.id === id
            ? {
                ...o,
                current_status: res.current_status,
                last_verified_at: res.last_verified_at,
              }
            : o
        )
      )
      if (selectedDetailOpp && selectedDetailOpp.id === id) {
        setSelectedDetailOpp(prev => ({
          ...prev,
          current_status: res.current_status,
          last_verified_at: res.last_verified_at,
        }))
      }
      loadMetadata()
    } catch (err) {
      console.error('Verification failed:', err)
    } finally {
      setIsVerifying(false)
    }
  }

  // Sync is admin-only on the server (POST /api/opportunities/sync returns 403 otherwise),
  // so ordinary users get a read-only "last refreshed" line instead of a button that cannot work.
  const lastRefreshed = newestRefreshDate(opportunities)

  return (
    <div
      style={{
        width: '100%',
        maxWidth: '1280px',
        margin: '0 auto',
        padding: '24px 20px 80px 20px',
        boxSizing: 'border-box',
      }}
    >
      {/* Header Title */}
      <div style={{ marginBottom: '20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Radar size={24} color="var(--brand)" strokeWidth={1.8} />
          <h1 style={{ fontSize: '24px', fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}>
            Internship Radar
          </h1>
          <span
            style={{
              padding: '2px 8px',
              borderRadius: '6px',
              background: 'rgba(245, 166, 35, 0.15)',
              color: 'var(--brand-dark)',
              fontSize: '11px',
              fontWeight: 700,
              textTransform: 'uppercase',
            }}
          >
            Live Intel
          </span>
        </div>
        <p style={{ margin: '6px 0 0 0', fontSize: '14px', color: 'var(--text-secondary)' }}>
          Verified AI, software engineering, and research internships for undergraduates in India with deterministic eligibility matching.
        </p>
      </div>

      {/* 1. Overview Metric Cards */}
      <RadarOverviewCards
        stats={stats}
        profile={profile}
        onOpenProfile={handleOpenCandidateProfile}
        onNavigateToResumeStudio={handleGoToResumeStudio}
        onSelectTab={setActiveTab}
      />

      {/* 2. Filter Bar */}
      <RadarFilters
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        selectedCategory={selectedCategory}
        onCategoryChange={setSelectedCategory}
        selectedEmployerType={selectedEmployerType}
        onEmployerTypeChange={setSelectedEmployerType}
        indiaOnly={indiaOnly}
        onToggleIndiaOnly={() => setIndiaOnly(prev => !prev)}
        workArrangement={workArrangement}
        onWorkArrangementChange={setWorkArrangement}
        onOpenProfile={handleOpenCandidateProfile}
        lastRefreshed={lastRefreshed}
      />

      {/* Scoped Background Refreshing Indicator */}
      {isRefreshingMatches && (
        <div
          role="status"
          aria-live="polite"
          id="radar-refreshing-indicator"
          style={{
            padding: '8px 14px',
            marginBottom: '16px',
            borderRadius: '8px',
            background: 'rgba(59, 130, 246, 0.08)',
            border: '1px solid rgba(59, 130, 246, 0.25)',
            color: 'var(--primary, #3b82f6)',
            fontSize: '12px',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <RefreshCw size={14} strokeWidth={1.8} className="spin" />
          <span>Refreshing internship recommendations and eligibility matches…</span>
        </div>
      )}

      {/* 3. Opportunities List Content */}
      {loading ? (
        <div
          style={{
            padding: '48px 24px',
            textAlign: 'center',
            color: 'var(--text-muted)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '12px',
          }}
        >
          <Loader2 size={32} strokeWidth={1.8} className="spin" color="var(--brand)" />
          <div style={{ fontSize: '15px', fontWeight: 600 }}>Loading verified opportunities…</div>
        </div>
      ) : error ? (
        <div
          style={{
            padding: '24px',
            borderRadius: 'var(--radius-card, 8px)',
            background: 'rgba(239, 68, 68, 0.08)',
            border: '1px solid #ef4444',
            color: '#dc2626',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <div>
            <strong>Error:</strong> {error}
          </div>
          <button
            type="button"
            onClick={loadOpportunities}
            style={{
              padding: '6px 14px',
              borderRadius: 'var(--radius-btn, 6px)',
              background: '#ef4444',
              color: '#ffffff',
              border: 'none',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Retry
          </button>
        </div>
      ) : opportunities.length === 0 ? (
        activeTab === 'recommended' && !hasCandidateProfile ? (
          <div
            style={{
              padding: '48px 24px',
              textAlign: 'center',
              borderRadius: 'var(--radius-card, 8px)',
              background: 'var(--bg-card)',
              border: '1px dashed var(--border)',
            }}
          >
            <Radar size={36} strokeWidth={1.5} color="var(--brand)" style={{ margin: '0 auto 12px auto' }} />
            <h3 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 6px 0' }}>
              Candidate Profile Required for Recommendations
            </h3>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', maxWidth: '480px', margin: '0 auto 20px auto', lineHeight: 1.5 }}>
              Career Copilot evaluates internship eligibility and match fit against the verified candidate profile maintained in Resume Studio. Upload or build your resume in Resume Studio to unlock personalized match scoring.
            </p>
            {handleGoToResumeStudio && (
              <button
                type="button"
                onClick={handleGoToResumeStudio}
                style={{
                  padding: '9px 20px',
                  borderRadius: 'var(--radius-btn, 6px)',
                  background: 'var(--brand)',
                  color: 'var(--accent-text, #1b1a17)',
                  border: 'none',
                  fontWeight: 600,
                  fontSize: '13px',
                  cursor: 'pointer',
                }}
              >
                Go to Resume Studio
              </button>
            )}
          </div>
        ) : (searchQuery.trim() || selectedCategory || selectedEmployerType || workArrangement) ? (
          <div
            style={{
              padding: '48px 24px',
              textAlign: 'center',
              borderRadius: 'var(--radius-card, 8px)',
              background: 'var(--bg-card)',
              border: '1px dashed var(--border)',
            }}
          >
            <Radar size={36} strokeWidth={1.5} color="var(--text-muted)" style={{ margin: '0 auto 12px auto' }} />
            <h3 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 6px 0' }}>
              No opportunities match your current filters
            </h3>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', maxWidth: '440px', margin: '0 auto 16px auto' }}>
              We could not find any postings matching your search query or selected criteria. Try adjusting or clearing your filters.
            </p>
            <button
              type="button"
              onClick={() => {
                setSearchQuery('')
                setSelectedCategory('')
                setSelectedEmployerType('')
                setWorkArrangement('')
              }}
              style={{
                padding: '8px 18px',
                borderRadius: 'var(--radius-btn, 6px)',
                background: 'var(--bg-card)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border)',
                fontWeight: 600,
                fontSize: '13px',
                cursor: 'pointer',
              }}
            >
              Reset Filters
            </button>
          </div>
        ) : activeTab === 'watchlist' ? (
          <div
            style={{
              padding: '48px 24px',
              textAlign: 'center',
              borderRadius: 'var(--radius-card, 8px)',
              background: 'var(--bg-card)',
              border: '1px dashed var(--border)',
            }}
          >
            <Radar size={36} strokeWidth={1.5} color="var(--text-muted)" style={{ margin: '0 auto 12px auto' }} />
            <h3 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 6px 0' }}>
              Your watchlist is empty
            </h3>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', maxWidth: '440px', margin: '0 auto 16px auto' }}>
              You have not bookmarked any opportunities yet. Click the bookmark icon on any card to monitor its hiring cycle and deadlines.
            </p>
            <button
              type="button"
              onClick={() => setActiveTab('open')}
              style={{
                padding: '8px 18px',
                borderRadius: 'var(--radius-btn, 6px)',
                background: 'var(--brand)',
                color: 'var(--accent-text, #1b1a17)',
                border: 'none',
                fontWeight: 600,
                fontSize: '13px',
                cursor: 'pointer',
              }}
            >
              Browse Open Opportunities
            </button>
          </div>
        ) : activeTab === 'applications' ? (
          <div
            style={{
              padding: '48px 24px',
              textAlign: 'center',
              borderRadius: 'var(--radius-card, 8px)',
              background: 'var(--bg-card)',
              border: '1px dashed var(--border)',
            }}
          >
            <Radar size={36} strokeWidth={1.5} color="var(--text-muted)" style={{ margin: '0 auto 12px auto' }} />
            <h3 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 6px 0' }}>
              No applications tracked yet
            </h3>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', maxWidth: '440px', margin: '0 auto 16px auto' }}>
              Track applications through preparation, submission, and interviews to stay organized across active cycles.
            </p>
            <button
              type="button"
              onClick={() => setActiveTab('recommended')}
              style={{
                padding: '8px 18px',
                borderRadius: 'var(--radius-btn, 6px)',
                background: 'var(--brand)',
                color: 'var(--accent-text, #1b1a17)',
                border: 'none',
                fontWeight: 600,
                fontSize: '13px',
                cursor: 'pointer',
              }}
            >
              Explore Recommendations
            </button>
          </div>
        ) : (
          <div
            style={{
              padding: '48px 24px',
              textAlign: 'center',
              borderRadius: 'var(--radius-card, 8px)',
              background: 'var(--bg-card)',
              border: '1px dashed var(--border)',
            }}
          >
            <Radar size={36} strokeWidth={1.5} color="var(--text-muted)" style={{ margin: '0 auto 12px auto' }} />
            <h3 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 6px 0' }}>
              No opportunities found in this view
            </h3>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', maxWidth: '440px', margin: '0 auto 16px auto' }}>
              Try broadening your criteria. Listings are refreshed automatically from verified sources.
            </p>
          </div>
        )
      ) : (
        <>
          {/* Top Dismissible Candidate Profile Banner (replaces repeating per-card boxes) */}
          {!hasCandidateProfile && !bannerDismissed && (
            <div
              role="status"
              id="radar-missing-profile-banner"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '12px',
                padding: '12px 16px',
                marginBottom: '16px',
                background: 'var(--bg-card-soft, #f2eee6)',
                border: '1px solid var(--border, #e6e1d6)',
                borderRadius: 'var(--radius-btn, 6px)',
                fontSize: '13px',
                color: 'var(--text-primary)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Info size={16} strokeWidth={1.8} style={{ color: 'var(--brand, #f5a623)', flexShrink: 0 }} />
                <span>
                  Add your profile in{' '}
                  <button
                    type="button"
                    onClick={handleGoToResumeStudio}
                    style={{
                      background: 'transparent',
                      border: 'none',
                      padding: 0,
                      color: 'var(--brand, #f5a623)',
                      fontWeight: 600,
                      cursor: 'pointer',
                      textDecoration: 'underline',
                      font: 'inherit',
                    }}
                  >
                    Resume Studio
                  </button>{' '}
                  to check eligibility for these roles.
                </span>
              </div>
              <button
                type="button"
                onClick={() => setBannerDismissed(true)}
                aria-label="Dismiss banner"
                style={{
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  padding: '4px',
                  color: 'var(--text-muted)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <X size={15} strokeWidth={1.8} />
              </button>
            </div>
          )}

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
              gap: '16px',
            }}
          >
            {opportunities.map(opp => (
              <RadarOpportunityCard
                key={opp.id}
                opportunity={opp}
                onOpenDetail={setSelectedDetailOpp}
                onToggleSave={handleToggleSave}
                onUpdateAppStatus={handleUpdateApplication}
                onApply={setActiveWorkspaceOpp}
              />
            ))}
          </div>
          {hasMore && (
            <div style={{ textAlign: 'center', marginTop: '28px' }}>
              <button
                type="button"
                onClick={() => {
                  if (!isLoadingMore) {
                    loadOpportunities({ append: true, targetPage: page + 1 })
                  }
                }}
                disabled={isLoadingMore}
                style={{
                  padding: '10px 24px',
                  borderRadius: '8px',
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-primary)',
                  fontWeight: 600,
                  fontSize: '13px',
                  cursor: isLoadingMore ? 'not-allowed' : 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '8px',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
                }}
              >
                {isLoadingMore ? (
                  <>
                    <Loader2 size={14} className="spin" />
                    <span>Loading more opportunities…</span>
                  </>
                ) : (
                  <>
                    <span>Load More Opportunities</span>
                    <ArrowDown size={14} />
                  </>
                )}
              </button>
            </div>
          )}
        </>
      )}

      {/* Detail & History Modal */}
      {selectedDetailOpp && (
        <RadarDetailModal
          opportunity={selectedDetailOpp}
          onClose={() => setSelectedDetailOpp(null)}
          onUpdateApp={handleUpdateApplication}
          onVerify={handleVerifyOpportunity}
          isVerifying={isVerifying}
          onApply={setActiveWorkspaceOpp}
          onNavigateToResumeStudio={handleGoToResumeStudio}
        />
      )}

      {/* Internal Application Workspace Modal */}
      {activeWorkspaceOpp && (
        <React.Suspense fallback={null}>
          <ApplicationWorkspaceModal
            opportunity={activeWorkspaceOpp}
            onClose={() => setActiveWorkspaceOpp(null)}
            onApplicationUpdated={(updatedApp) => {
              setOpportunities(prev =>
                prev.map(o => (o.id === activeWorkspaceOpp.id ? { ...o, application_status: updatedApp.status } : o))
              )
              loadMetadata()
            }}
            onNavigateToResumeStudio={handleGoToResumeStudio}
          />
        </React.Suspense>
      )}
    </div>
  )
}
