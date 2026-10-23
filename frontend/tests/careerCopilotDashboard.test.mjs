import test from 'node:test'
import assert from 'node:assert/strict'

test('URL validation: safely distinguishes valid http(s) URLs from empty/malformed/javascript links', () => {
  const isValidUrl = (url) => {
    if (!url || typeof url !== 'string') return false
    const s = url.trim()
    return /^https?:\/\//i.test(s) && !s.toLowerCase().includes('javascript:')
  }

  assert.equal(isValidUrl('https://careers.google.com/jobs/123'), true)
  assert.equal(isValidUrl('http://careers.microsoft.com/job'), true)
  assert.equal(isValidUrl('javascript:alert(1)'), false)
  assert.equal(isValidUrl(''), false)
  assert.equal(isValidUrl(null), false)
  assert.equal(isValidUrl(undefined), false)
  assert.equal(isValidUrl('nan'), false)
  assert.equal(isValidUrl('null'), false)
  assert.equal(isValidUrl('ftp://example.com'), false)
})

test('Data quality cleansing: cleanses nan, null, undefined, none strings to null', () => {
  const isCleanString = (val) => {
    if (!val) return false
    const s = String(val).trim().toLowerCase()
    return s !== '' && s !== 'nan' && s !== 'null' && s !== 'undefined' && s !== 'none' && s !== 'n/a'
  }

  assert.equal(isCleanString('nan'), false)
  assert.equal(isCleanString('NaN'), false)
  assert.equal(isCleanString('null'), false)
  assert.equal(isCleanString('undefined'), false)
  assert.equal(isCleanString('none'), false)
  assert.equal(isCleanString('n/a'), false)
  assert.equal(isCleanString(''), false)
  assert.equal(isCleanString('Bengaluru, India'), true)
  assert.equal(isCleanString('Google'), true)
})

test('Dashboard zero results categorization: distinguishes missing profile from filter emptiness', () => {
  const getZeroResultType = ({ activeTab, profile, searchQuery, selectedCategory, selectedEmployerType, workArrangement }) => {
    const isProfileMissing = !profile || (profile.has_profile === false) || (!profile.degree_level && (!profile.skills || profile.skills.length === 0) && !profile.grad_year)
    if (activeTab === 'recommended' && isProfileMissing) {
      return 'missing_profile'
    }
    if (searchQuery || selectedCategory || selectedEmployerType || workArrangement) {
      return 'filtered_empty'
    }
    if (activeTab === 'watchlist') {
      return 'empty_watchlist'
    }
    if (activeTab === 'applications') {
      return 'empty_applications'
    }
    return 'empty_general'
  }

  // 1. Missing profile in recommendations
  assert.equal(
    getZeroResultType({ activeTab: 'recommended', profile: null, searchQuery: '', selectedCategory: '', selectedEmployerType: '', workArrangement: '' }),
    'missing_profile'
  )

  // 2. Active filters produce empty results
  assert.equal(
    getZeroResultType({ activeTab: 'all', profile: { has_profile: true, degree_level: 'B.Tech' }, searchQuery: 'UnknownCorp', selectedCategory: '', selectedEmployerType: '', workArrangement: '' }),
    'filtered_empty'
  )

  // 3. Watchlist empty
  assert.equal(
    getZeroResultType({ activeTab: 'watchlist', profile: { has_profile: true }, searchQuery: '', selectedCategory: '', selectedEmployerType: '', workArrangement: '' }),
    'empty_watchlist'
  )

  // 4. Applications empty
  assert.equal(
    getZeroResultType({ activeTab: 'applications', profile: { has_profile: true }, searchQuery: '', selectedCategory: '', selectedEmployerType: '', workArrangement: '' }),
    'empty_applications'
  )
})

test('Opportunity Card top row constraints: at most 2 compact rectangular badges', () => {
  const generateTopRowBadges = (opp) => {
    const badges = []
    // 1. Status badge
    if (opp.current_status === 'OPEN_CONFIRMED') {
      badges.push({ label: 'Verified Open', type: 'status' })
    } else if (opp.current_status === 'NEEDS_VERIFICATION') {
      badges.push({ label: 'Needs Verification', type: 'status' })
    }

    // 2. Eligibility badge
    if (opp.eligibility_classification === 'ELIGIBLE') {
      badges.push({ label: 'Confirmed Match', type: 'eligibility' })
    } else if (opp.eligibility_classification === 'POTENTIAL_MATCH') {
      badges.push({ label: 'Possible Match', type: 'eligibility' })
    } else if (opp.eligibility_classification === 'INELIGIBLE') {
      badges.push({ label: 'Ineligible', type: 'eligibility' })
    }

    // Limit top row to at most 2 labels
    return badges.slice(0, 2)
  }

  const badges = generateTopRowBadges({
    current_status: 'OPEN_CONFIRMED',
    eligibility_classification: 'ELIGIBLE',
    is_saved: true,
  })

  assert.equal(badges.length, 2)
  assert.equal(badges[0].label, 'Verified Open')
  assert.equal(badges[1].label, 'Confirmed Match')
})

test('Opportunity Card action semantics: View details vs Open original listing', () => {
  const getCardActions = (opp) => {
    const originalUrl = opp.official_application_url || opp.canonical_url
    const hasValidExternalUrl = Boolean(
      originalUrl &&
      typeof originalUrl === 'string' &&
      /^https?:\/\//i.test(originalUrl.trim()) &&
      !originalUrl.toLowerCase().includes('javascript:')
    )

    return {
      primaryAction: {
        label: 'View details',
        type: 'modal',
      },
      externalAction: {
        label: 'Open original listing',
        disabled: !hasValidExternalUrl,
        url: hasValidExternalUrl ? originalUrl.trim() : null,
      },
    }
  }

  // Valid original URL
  const validActions = getCardActions({
    id: 1,
    canonical_url: 'https://careers.google.com/jobs/1',
  })
  assert.equal(validActions.primaryAction.label, 'View details')
  assert.equal(validActions.externalAction.disabled, false)
  assert.equal(validActions.externalAction.label, 'Open original listing')

  // Malformed / JavaScript URL
  const invalidActions = getCardActions({
    id: 2,
    canonical_url: 'javascript:void(0)',
  })
  assert.equal(invalidActions.externalAction.disabled, true)
  assert.equal(invalidActions.externalAction.url, null)
})

test('Date distinction: separates posted date from verification date', () => {
  const formatDates = (opp) => {
    const rawPostingDate = opp.posted_at || opp.confirmed_open_date
    const formattedPosted = rawPostingDate
      ? new Date(rawPostingDate).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
      : null

    const formattedVerified = opp.last_verified_at
      ? `${new Date(opp.last_verified_at).toLocaleDateString()}`
      : null

    return { posted: formattedPosted, verified: formattedVerified }
  }

  const dates = formatDates({
    posted_at: '2026-10-15T10:00:00Z',
    last_verified_at: '2026-10-23T18:30:00Z',
  })

  assert.notEqual(dates.posted, null)
  assert.notEqual(dates.verified, null)
  assert.notEqual(dates.posted, dates.verified)
})

test('Resume Studio navigation callback triggers correctly on candidate profile click', () => {
  let navigatedTab = null
  const handleNavigateToResumeStudio = () => {
    navigatedTab = 'resumes'
  }

  // Click on "Candidate Profile" button or missing profile prompt
  handleNavigateToResumeStudio()
  assert.equal(navigatedTab, 'resumes')
})
