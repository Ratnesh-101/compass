import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import {
  friendlyStatusLabel,
  buildResumeIncompleteHint,
  hasCopyableText,
  COPY_EMPTY_MESSAGE,
  restoreSkillCase,
  collectSkillNames,
  resumeVersionLabel,
} from '../src/utils/careerPolishHelpers.js'
import { APPLICATION_STATUS_LABELS, getValidationCardState } from '../src/utils/careerUiHelpers.js'

const read = rel => fs.readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')

test('Print ATS Resume opens a window synchronously, no hidden-frame fallback', () => {
  const src = read('components/career/HandoffKitDrawer.jsx')
  assert.ok(src.includes('onClick={handlePrintResume}'))
  assert.ok(!/onClick=\{\(\) => openAuthedHtml\(/.test(src))
  const handler = src.slice(src.indexOf('const handlePrintResume'), src.indexOf('useEffect('))
  const openAt = handler.indexOf("window.open('about:blank'")
  assert.ok(openAt > -1)
  assert.ok(openAt < handler.indexOf('await'), 'window.open must run before any await')
  assert.ok(handler.includes('popup })'))
  assert.ok(src.includes('Allow pop-ups to print, or use Download Word.'))
})

test('amber primary button uses a dark text colour', () => {
  const css = read('index.css')
  const block = css.slice(css.indexOf('.btn-primary-amber {'))
  assert.match(block.slice(0, 300), /color: var\(--accent-text\)/)
  assert.match(css, /--accent-text: #1b1a17/)
  for (const f of ['components/career/HandoffKitDrawer.jsx', 'components/career/ApplicationWorkspaceModal.jsx', 'components/career/ApplicationCenter.jsx']) {
    const lines = read(f).split('\n')
    lines.forEach((l, i) => {
      if (/background: ?'var\(--brand[^)]*\)'/.test(l)) {
        const near = lines.slice(Math.max(0, i - 4), i + 7).join('\n')
        assert.ok(!/\bcolor: ?'(#fff|#ffffff|white)'/.test(near), `${f}:${i + 1} white text on amber`)
      }
    })
  }
})

test('accessibility labels, aria-pressed and htmlFor are present', () => {
  const center = read('components/career/ApplicationCenter.jsx')
  assert.ok(center.includes('aria-label={`Select '))
  assert.ok(center.includes('aria-label="Select all visible applications"'))
  const filters = read('components/radar/RadarFilters.jsx')
  assert.ok(filters.includes('aria-label="Search internships by company, role or keyword"'))
  assert.ok(filters.includes('aria-label="Filter by role category"'))
  assert.ok(filters.includes('aria-label="Filter by work arrangement"'))
  assert.ok(filters.includes('aria-label="Filter by employer type"'))
  assert.ok(filters.includes('aria-pressed={!!indiaOnly}'))
  assert.ok(read('components/radar/RadarProfileModal.jsx').includes('aria-pressed={checked}'))
  const ws = read('components/career/ApplicationWorkspaceModal.jsx')
  for (const id of ['workspace-target-deadline', 'workspace-private-notes', 'workspace-full-name', 'workspace-email']) {
    assert.ok(ws.includes(`htmlFor="${id}"`), `label for ${id}`)
    assert.ok(ws.includes(`id="${id}"`), `input ${id}`)
  }
})

test('friendly status labels', () => {
  assert.equal(friendlyStatusLabel('READY_FOR_REVIEW'), 'Ready for review')
  assert.equal(friendlyStatusLabel('VALIDATION_FAILED'), 'Needs fixes before sending')
  assert.equal(friendlyStatusLabel('RESUME_VALIDATION_FAILED'), 'Needs fixes before sending')
  assert.equal(friendlyStatusLabel('APPROVED'), 'Approved')
  assert.equal(friendlyStatusLabel(''), '')
  assert.equal(APPLICATION_STATUS_LABELS.RESUME_VALIDATION_FAILED, 'Needs fixes before sending')
  assert.equal(APPLICATION_STATUS_LABELS.READY_FOR_REVIEW, 'Ready for review')
  assert.ok(read('components/career/ResumeStudio.jsx').includes('friendlyStatusLabel(res.validation_status)'))
})

test('resume hint lists only missing fields', () => {
  assert.equal(buildResumeIncompleteHint(['education']), 'Add your education in My resume.')
  assert.equal(buildResumeIncompleteHint(['Email', 'education']), 'Add your email and education in My resume.')
  assert.match(buildResumeIncompleteHint([]), /name, email and education/)
  const state = getValidationCardState({ is_valid: false, missing_fields: ['education'] })
  assert.equal(state.hint, 'Add your education in My resume.')
})

test('empty cover letter says nothing to copy', () => {
  assert.equal(hasCopyableText('   '), false)
  assert.equal(hasCopyableText('Dear team'), true)
  assert.equal(COPY_EMPTY_MESSAGE, 'Nothing to copy yet.')
  const src = read('components/career/ResumeStudio.jsx')
  assert.ok(src.includes('!hasCopyableText(coverLetterText)'))
})

test('empty stage message, watchlist removal, radar banner wording, saved status', () => {
  assert.ok(read('components/career/ApplicationCenter.jsx').includes('No applications in this stage yet.'))
  assert.ok(read('components/InternshipRadar.jsx').includes("activeTab === 'watchlist' && isCurrentlySaved"))
  const banner = read('components/radar/RadarOverviewCards.jsx')
  assert.ok(banner.includes('Manage in My resume'))
  assert.ok(!banner.includes('Manage in Resume Studio'))
  const modal = read('components/radar/RadarProfileModal.jsx')
  assert.ok(!modal.includes('setTimeout(') && modal.includes("if (typeof onClose === 'function') onClose()"))
})

test('duplicate resume names show created date; diff keeps skill capitalisation', () => {
  const a = resumeVersionLabel({ title: 'Tailored', created_at: '2026-05-01T09:30:00Z' })
  const b = resumeVersionLabel({ title: 'Tailored', created_at: '2026-05-02T14:05:00Z' })
  assert.notEqual(a, b)
  assert.ok(a.startsWith('Tailored · '))
  assert.equal(resumeVersionLabel({ title: 'Main' }), 'Main')
  const known = collectSkillNames({ languages: ['Python', 'C++'], tools: 'Git, Docker' })
  assert.equal(restoreSkillCase('python', known), 'Python')
  assert.equal(restoreSkillCase('docker', known), 'Docker')
  assert.equal(restoreSkillCase('rust', known), 'rust')
})
