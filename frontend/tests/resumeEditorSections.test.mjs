import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import {
  validateEducation, validateProject, validateLinks, validateExperience, validateGrade,
  sectionsReducer, contentToSections, buildSectionsContent, sectionForMissingField,
} from '../src/components/career/resumeEditorModel.js'

const read = (p) => fs.readFileSync(new URL(p, import.meta.url), 'utf8')

test('validateEducation requires institution and degree, bounds years', () => {
  const bad = validateEducation({ institution: '', degree: '', start_year: '1949', end_year: '2101', cgpa_or_grade: '' })
  assert.ok(bad.errors.institution && bad.errors.degree && bad.errors.start_year && bad.errors.end_year)
  const ok = validateEducation({ institution: 'IIT', degree: 'B.Tech', start_year: '2021', end_year: '2025', cgpa_or_grade: '8.5' })
  assert.deepEqual(ok.errors, {})
  assert.equal(ok.value.start_year, 2021)
  assert.equal(ok.value.field_of_study, null)
  assert.ok(validateEducation({ institution: 'a', degree: 'b', start_year: '2025', end_year: '2021' }).errors.end_year)
  assert.ok(validateEducation({ institution: 'a', degree: 'b', start_year: '20x1' }).errors.start_year)
})

test('validateGrade accepts 0-10 and scaled grades, rejects the rest', () => {
  assert.equal(validateGrade(''), null)
  assert.equal(validateGrade('10'), null)
  assert.equal(validateGrade('3.6/4.0'), null)
  assert.ok(validateGrade('10.5'))
  assert.ok(validateGrade('5/4'))
  assert.ok(validateGrade('great'))
})

test('validateProject checks title and http(s) link, splits technologies', () => {
  assert.ok(validateProject({ title: '', link: '' }).errors.title)
  assert.ok(validateProject({ title: 'P', link: 'javascript:alert(1)' }).errors.link)
  assert.ok(validateProject({ title: 'P', link: 'ftp://x.y' }).errors.link)
  const ok = validateProject({ title: 'P', description: 'd', technologies: 'Python, React,, ', link: 'https://x.dev' })
  assert.deepEqual(ok.errors, {})
  assert.deepEqual(ok.value.technologies, ['Python', 'React'])
  assert.equal(ok.value.project_url, 'https://x.dev/')
})

test('validateLinks requires http(s) URLs but allows blanks and free text', () => {
  const bad = validateLinks({ linkedin_url: 'linkedin.com/in/x', github_url: 'javascript:1', portfolio_url: 'https://ok.dev' })
  assert.ok(bad.errors.linkedin_url && bad.errors.github_url)
  assert.equal(bad.errors.portfolio_url, undefined)
  const ok = validateLinks({ work_authorization: ' Authorised to work in India ', notice_period: '30 days' })
  assert.deepEqual(ok.errors, {})
  assert.equal(ok.value.work_authorization, 'Authorised to work in India')
  assert.equal(ok.value.linkedin_url, null)
})

test('validateExperience requires company and role; current drops end date', () => {
  assert.ok(validateExperience({ company: '', role_title: '' }).errors.company)
  const r = validateExperience({ company: 'A', role_title: 'B', is_current: true, end_date: 'x', highlights: 'one\n\ntwo' })
  assert.equal(r.value.end_date, null)
  assert.deepEqual(r.value.highlights, ['one', 'two'])
})

test('sectionsReducer adds, updates and removes items without mutating', () => {
  const s0 = contentToSections({})
  const s1 = sectionsReducer(s0, { type: 'add', section: 'education' })
  assert.equal(s0.education.length, 0)
  assert.equal(s1.education.length, 1)
  const s2 = sectionsReducer(s1, { type: 'update', section: 'education', index: 0, field: 'institution', value: 'IIT' })
  assert.equal(s2.education[0].institution, 'IIT')
  assert.equal(s1.education[0].institution, '')
  const s3 = sectionsReducer(sectionsReducer(s2, { type: 'add', section: 'projects' }), { type: 'add', section: 'experience' })
  assert.equal(s3.projects.length, 1)
  assert.equal(s3.experience.length, 1)
  const s4 = sectionsReducer(s3, { type: 'remove', section: 'education', index: 0 })
  assert.equal(s4.education.length, 0)
  assert.equal(sectionsReducer(s4, { type: 'add', section: 'nope' }), s4)
  const s5 = sectionsReducer(s4, { type: 'setLink', key: 'notice_period', value: '30 days' })
  assert.equal(s5.links.notice_period, '30 days')
  assert.equal(s4.links.notice_period, '')
})

test('buildSectionsContent maps to the stored model fields and blocks on errors', () => {
  const sections = contentToSections({})
  sections.education = [{ institution: 'IIT', degree: 'B.Tech', field_of_study: '', start_year: '2021', end_year: '2025', cgpa_or_grade: '8' }, { institution: '', degree: '', field_of_study: '', start_year: '', end_year: '', cgpa_or_grade: '' }]
  sections.links = { linkedin_url: 'https://linkedin.com/in/a', github_url: 'https://github.com/a', portfolio_url: 'https://a.dev', work_authorization: 'Authorised to work in India', notice_period: '30 days' }
  const r = buildSectionsContent(sections, { evidence_notes: { keep: 'x' } })
  assert.equal(r.ok, true)
  assert.equal(r.content.education.length, 1)
  assert.equal(r.content.linkedin_url, 'https://linkedin.com/in/a')
  assert.equal(r.content.github_or_portfolio, 'https://github.com/a')
  assert.deepEqual(r.content.relevant_links, ['https://a.dev/'])
  assert.deepEqual(r.content.evidence_notes, { keep: 'x', work_authorization: 'Authorised to work in India', notice_period: '30 days' })
  sections.links.github_url = 'nope'
  assert.equal(buildSectionsContent(sections, {}).ok, false)
  const round = contentToSections({ ...r.content })
  assert.equal(round.links.notice_period, '30 days')
  assert.equal(round.education[0].end_year, 2025)
})

test("'+ Add to profile' passes the section key and the editor focuses it", () => {
  assert.equal(sectionForMissingField('degree'), 'education')
  assert.equal(sectionForMissingField('graduation_year'), 'education')
  assert.equal(sectionForMissingField('work_authorization'), 'links')
  assert.equal(sectionForMissingField('linkedin_url'), 'links')
  assert.equal(sectionForMissingField('unknown'), null)
  assert.equal(sectionForMissingField('toString'), null)
  const drawer = read('../src/components/career/HandoffKitDrawer.jsx')
  assert.match(drawer, /onNavigateToResumeStudio\?\.\(sectionForMissingField\(item\.key\)\)/)
  const center = read('../src/components/career/ApplicationCenter.jsx')
  assert.match(center, /onNavigateToResumeStudio\?\.\(sectionForMissingField\(app\.missing_fields\[0\]\)\)/)
  const copilot = read('../src/components/CareerCopilot.jsx')
  assert.match(copilot, /<ResumeFocusContext\.Provider value=\{resumeFocus\}>/)
  assert.match(copilot, /setResumeFocus\(\(prev\) => \(\{ section: key, nonce: prev\.nonce \+ 1 \}\)\)/)
  const studio = read('../src/components/career/ResumeStudio.jsx')
  assert.match(studio, /useContext\(ResumeFocusContext\)/)
  assert.match(studio, /scrollIntoView/)
})
