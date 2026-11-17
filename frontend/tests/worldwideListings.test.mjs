import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import {
  isOpenWorldwide,
  radarHeadingText,
  WORLDWIDE_CHIP_LABEL,
  WORLDWIDE_DETAIL_LINE,
} from '../src/components/radar/radarDisplay.js'

const read = (rel) => fs.readFileSync(new URL(rel, import.meta.url), 'utf8')

test('isOpenWorldwide: India-located listing is not worldwide', () => {
  assert.equal(isOpenWorldwide({ location: 'Bengaluru, India', country: 'India', is_india_eligible: true }), false)
  assert.equal(isOpenWorldwide({ location: 'Remote, Pune', country: 'Global', is_india_eligible: true }), false)
})

test('isOpenWorldwide: Remote, Global and Work from anywhere count when server marks eligible', () => {
  assert.equal(isOpenWorldwide({ location: 'Remote, Global', country: 'Global', is_india_eligible: true }), true)
  assert.equal(isOpenWorldwide({ location: 'Work from anywhere', is_india_eligible: true }), true)
  assert.equal(isOpenWorldwide({ location: 'Remote (Worldwide)', is_india_eligible: true }), true)
})

test('isOpenWorldwide: other-country listing or not eligible is false', () => {
  assert.equal(isOpenWorldwide({ location: 'Remote (United States)', country: 'United States', is_india_eligible: false }), false)
  assert.equal(isOpenWorldwide({ location: 'Anywhere', country: 'Global', is_india_eligible: false }), false)
  assert.equal(isOpenWorldwide({ location: 'Remote (United States)', is_india_eligible: true }), false)
})

test('isOpenWorldwide: missing fields do not throw', () => {
  assert.equal(isOpenWorldwide(undefined), false)
  assert.equal(isOpenWorldwide(null), false)
  assert.equal(isOpenWorldwide({}), false)
  assert.equal(isOpenWorldwide({ is_india_eligible: true }), false)
})

test('radarHeadingText: worldwide wording only with India filter on and a worldwide listing', () => {
  const ww = { location: 'Remote, Global', country: 'Global', is_india_eligible: true }
  const india = { location: 'Pune, India', country: 'India', is_india_eligible: true }
  assert.equal(radarHeadingText(true, [india, ww]), 'Internships in India, then remote roles open worldwide')
  assert.match(radarHeadingText(true, [india]), /^Internships in India, or open to applicants in India/)
  assert.match(radarHeadingText(true, null), /^Internships in India, or open to applicants in India/)
  assert.match(radarHeadingText(false, [ww]), /^Internships worldwide/)
})

test('chip text, detail line and wiring appear in the card and modal', () => {
  assert.equal(WORLDWIDE_CHIP_LABEL, 'Remote · open worldwide')
  assert.equal(WORLDWIDE_DETAIL_LINE, 'The listing says anyone can apply. Check the company site for location rules.')
  const card = read('../src/components/radar/RadarOpportunityCard.jsx')
  const modal = read('../src/components/radar/RadarDetailModal.jsx')
  assert.ok(card.includes('isOpenWorldwide(opportunity)') && card.includes('WORLDWIDE_CHIP_LABEL'))
  assert.ok(modal.includes('isOpenWorldwide(opportunity)') && modal.includes('WORLDWIDE_DETAIL_LINE'))
  assert.ok(read('../src/components/InternshipRadar.jsx').includes('radarHeadingText(indiaOnly, opportunities)'))
})

test('chat placeholder is the new default and the slash hint stays reachable', () => {
  const src = read('../src/components/chat/ChatInputBar.jsx')
  assert.ok(src.includes("'Ask anything, for example: Plan my week'"))
  assert.ok(!src.includes('Ask Compass anything'))
  assert.ok(src.includes("title='Type / to choose a mode'"))
  assert.ok(src.includes("aria-description='Type / to choose a mode'"))
})
