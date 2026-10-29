import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { getProfileBannerInfo } from '../src/utils/radarProfileBanner.js'

const profileWith = (...fields) => ({ missing_fields_limiting_eligibility: fields })

test('no banner when nothing limits eligibility', () => {
  assert.equal(getProfileBannerInfo(null).show, false)
  assert.equal(getProfileBannerInfo({}).show, false)
  assert.equal(getProfileBannerInfo(profileWith('cgpa')).show, false)
})

test('missing academic_year points at Candidate Profile, not Resume Studio', () => {
  const info = getProfileBannerInfo(profileWith('academic_year'))
  assert.equal(info.show, true)
  assert.equal(info.missingAcademicYear, true)
  assert.equal(info.missingGradYear, false)
  assert.equal(info.title, 'Add your year of study to confirm eligibility')
  assert.match(info.body, /Resume import can't tell which year you are in/)
  assert.match(info.body, /Candidate Profile/)
})

test('missing grad_year mentions graduation year and resume import', () => {
  const info = getProfileBannerInfo(profileWith('grad_year'))
  assert.equal(info.show, true)
  assert.equal(info.missingGradYear, true)
  assert.equal(info.missingAcademicYear, false)
  assert.match(info.body, /graduation year/i)
  assert.match(info.body, /Resume Studio/)
})

test('both missing shows both hints', () => {
  const info = getProfileBannerInfo(profileWith('academic_year', 'grad_year'))
  assert.equal(info.missingAcademicYear, true)
  assert.equal(info.missingGradYear, true)
  assert.match(info.body, /year you are in/)
  assert.match(info.body, /graduation year/i)
})

test('component uses the helper and the new button labels', () => {
  const source = fs.readFileSync(
    new URL('../src/components/radar/RadarOverviewCards.jsx', import.meta.url),
    'utf8',
  )
  assert.ok(source.includes('getProfileBannerInfo'))
  assert.ok(source.includes('Open Candidate Profile'))
  assert.ok(!source.includes('Complete your Candidate Profile in Resume Studio'))
})
