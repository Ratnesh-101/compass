import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { parseLocation, buildUrl, RESERVED_ROUTES } from '../src/router.js'

describe('Router Legal Routes and 404 Fallback', () => {
  it('parses /terms correctly before any custom domain fallback', () => {
    const loc = parseLocation('/terms', '')
    assert.equal(loc.tab, 'terms')
    assert.equal(loc.domain, 'all')
  })

  it('parses /privacy correctly before any custom domain fallback', () => {
    const loc = parseLocation('/privacy', '')
    assert.equal(loc.tab, 'privacy')
    assert.equal(loc.domain, 'all')
  })

  it('parses ?tab=terms and ?tab=privacy query parameters', () => {
    const locTerms = parseLocation('/', '?tab=terms')
    assert.equal(locTerms.tab, 'terms')

    const locPrivacy = parseLocation('/', '?tab=privacy')
    assert.equal(locPrivacy.tab, 'privacy')
  })

  it('buildUrl produces canonical URLs for terms, privacy, and 404', () => {
    assert.equal(buildUrl('terms'), '/terms')
    assert.equal(buildUrl('privacy'), '/privacy')
    assert.equal(buildUrl('404'), '/404')
  })

  it('reserves terms and privacy in RESERVED_ROUTES so custom domains cannot collide', () => {
    assert.ok(RESERVED_ROUTES.includes('terms'), 'terms must be reserved')
    assert.ok(RESERVED_ROUTES.includes('privacy'), 'privacy must be reserved')
    assert.ok(RESERVED_ROUTES.includes('404'), '404 must be reserved')
    assert.ok(RESERVED_ROUTES.includes('dashboard'), 'dashboard must be reserved')
  })

  it('routes valid custom single-segment domains to timeline', () => {
    const loc = parseLocation('/robotics', '')
    assert.equal(loc.tab, 'timeline')
    assert.equal(loc.domain, 'robotics')
  })

  it('routes unrecognized multi-segment or reserved non-tab paths to 404', () => {
    const loc1 = parseLocation('/unknown/subpage', '')
    assert.equal(loc1.tab, '404')

    const loc2 = parseLocation('/terms/extra', '')
    assert.equal(loc2.tab, '404')
  })
})
