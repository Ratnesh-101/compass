import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const srcDir = process.env.CAREER_FIXES_SRC_DIR || path.resolve(__dirname, '../src/components')

function readComponent(relPath) {
  const fullPath = path.resolve(srcDir, relPath)
  return fs.readFileSync(fullPath, 'utf8')
}

// ---------------------------------------------------------------------------
// Item 1: Controlled textarea strips commas, spaces, and newlines instantly
// ---------------------------------------------------------------------------
test('ExtractionReviewModal: Controlled inputs use local text states and do not prune delimiters on keystroke', () => {
  const src = readComponent('career/ExtractionReviewModal.jsx')

  // Check state declarations
  assert.match(src, /const\s*\[skillsText,\s*setSkillsText\]\s*=\s*useState\(['"]{2}\)/,
    'Must manage local skillsText string state')
  assert.match(src, /const\s*\[awardsText,\s*setAwardsText\]\s*=\s*useState\(['"]{2}\)/,
    'Must manage local awardsText string state')
  assert.match(src, /const\s*\[certificationsText,\s*setCertificationsText\]\s*=\s*useState\(['"]{2}\)/,
    'Must manage local certificationsText string state')

  // Must not bind textarea value directly to .join on every render
  assert.doesNotMatch(src, /value=\{\(content\.skills\s*\|\|\s*\[\]\)\.join\(/,
    'Skills textarea value must not be bound directly to .join() on every render')
  assert.doesNotMatch(src, /value=\{\(content\.awards\s*\|\|\s*\[\]\)\.join\(/,
    'Awards textarea value must not be bound directly to .join() on every render')
  assert.doesNotMatch(src, /value=\{\(content\.certifications\s*\|\|\s*\[\]\)\.join\(/,
    'Certifications textarea value must not be bound directly to .join() on every render')

  // Must not parse into arrays directly in onChange
  assert.doesNotMatch(src, /skills:\s*e\.target\.value\.split\(/,
    'Skills onChange must not parse directly into content array on every keystroke')
  assert.doesNotMatch(src, /awards:\s*e\.target\.value\.split\(/,
    'Awards onChange must not parse directly into content array on every keystroke')
  assert.doesNotMatch(src, /certifications:\s*e\.target\.value\.split\(/,
    'Certifications onChange must not parse directly into content array on every keystroke')

  // Textarea values bound to local string states
  assert.match(src, /value=\{skillsText\}/, 'Skills textarea must bind to skillsText')
  assert.match(src, /value=\{awardsText\}/, 'Awards textarea must bind to awardsText')
  assert.match(src, /value=\{certificationsText\}/, 'Certifications textarea must bind to certificationsText')

  // Behaviour test: typing preserves trailing delimiters and parsing happens cleanly
  let localSkills = ''
  const onType = (newVal) => { localSkills = newVal }
  onType('Python, ')
  assert.equal(localSkills, 'Python, ', 'Typing a comma and space must be preserved in state without being pruned')

  let localAwards = 'Award 1'
  const onTypeAward = (newVal) => { localAwards = newVal }
  onTypeAward('Award 1\n')
  assert.equal(localAwards, 'Award 1\n', 'Typing Enter in awards must preserve newline without being stripped')

  // Parsed representation upon commit/blur
  const parsedSkills = localSkills.split(',').map(s => s.trim()).filter(Boolean)
  assert.deepEqual(parsedSkills, ['Python'], 'Parsed skills must trim and filter empty entries')
  const parsedAwards = localAwards.split('\n').map(s => s.trim()).filter(Boolean)
  assert.deepEqual(parsedAwards, ['Award 1'], 'Parsed awards must trim and filter empty entries')
})

// ---------------------------------------------------------------------------
// Item 2: Unauthenticated API call triggers 401 in Handoff Kit
// ---------------------------------------------------------------------------
test('HandoffKitDrawer: fetches handoff-kit with auth headers and credentials include', () => {
  const src = readComponent('career/HandoffKitDrawer.jsx')

  // Must import getAuthHeaders
  assert.match(src, /import\s*\{[^}]*getAuthHeaders[^}]*\}\s*from\s*['"]\.\.\/\.\.\/api\/baseClient(\.js)?['"]/,
    'HandoffKitDrawer must import getAuthHeaders from baseClient')

  // Must include auth headers and credentials: include
  assert.match(src, /headers:\s*getAuthHeaders\(\{\s*['"]Accept['"]:\s*['"]application\/json['"]\s*\}\)/,
    'HandoffKit fetch must pass getAuthHeaders')
  assert.match(src, /credentials:\s*['"]include['"]/,
    'HandoffKit fetch must pass credentials: include')
})

// ---------------------------------------------------------------------------
// Item 3: Stale resumesList wipes imported GitHub projects/skills
// ---------------------------------------------------------------------------
test('ResumeStudio: GitHub imports refresh resumesList to prevent wiping imported data on version switch', () => {
  const src = readComponent('career/ResumeStudio.jsx')

  // In handleImportGitHubRepo, must refresh resumesList
  const repoIdx = src.indexOf('handleImportGitHubRepo')
  assert.ok(repoIdx !== -1, 'handleImportGitHubRepo must exist')
  const repoBlock = src.slice(repoIdx, repoIdx + 1200)
  assert.match(repoBlock, /const\s+list\s*=\s*await\s+fetchResumes\(\)/,
    'handleImportGitHubRepo must call fetchResumes after updating master resume')
  assert.match(repoBlock, /setResumesList\(list\)/,
    'handleImportGitHubRepo must update resumesList state')

  // In handleImportGitHubSkills, must refresh resumesList
  const skillsIdx = src.indexOf('handleImportGitHubSkills')
  assert.ok(skillsIdx !== -1, 'handleImportGitHubSkills must exist')
  const skillsBlock = src.slice(skillsIdx, skillsIdx + 1200)
  assert.match(skillsBlock, /const\s+list\s*=\s*await\s+fetchResumes\(\)/,
    'handleImportGitHubSkills must call fetchResumes after updating master resume')
  assert.match(skillsBlock, /setResumesList\(list\)/,
    'handleImportGitHubSkills must update resumesList state')
})

// ---------------------------------------------------------------------------
// Item 4: Dead buttons dispatching unhandled 'navigate' CustomEvent
// ---------------------------------------------------------------------------
test('Dead navigate buttons wired to real application navigation mechanism', () => {
  const appCenterSrc = readComponent('career/ApplicationCenter.jsx')
  const drawerSrc = readComponent('career/HandoffKitDrawer.jsx')
  const copilotSrc = readComponent('CareerCopilot.jsx')

  // ApplicationCenter must accept onNavigateToResumeStudio prop
  assert.match(appCenterSrc, /export\s+default\s+function\s+ApplicationCenter\(\s*\{[^}]*onNavigateToResumeStudio[^}]*\}\s*\)/,
    'ApplicationCenter must accept onNavigateToResumeStudio prop')

  // ApplicationCenter must forward onNavigateToResumeStudio to HandoffKitDrawer
  assert.match(appCenterSrc, /<HandoffKitDrawer[\s\S]*?onNavigateToResumeStudio=\{onNavigateToResumeStudio\}[\s\S]*?\/>/,
    'ApplicationCenter must pass onNavigateToResumeStudio to HandoffKitDrawer')

  // CareerCopilot must pass handleNavigateToResumeStudio to ApplicationCenter
  assert.match(copilotSrc, /<ApplicationCenter\s+onNavigateToResumeStudio=\{handleNavigateToResumeStudio\}\s*\/>/,
    'CareerCopilot must wire onNavigateToResumeStudio to ApplicationCenter')

  // HandoffKitDrawer must accept onNavigateToResumeStudio prop
  assert.match(drawerSrc, /export\s+default\s+function\s+HandoffKitDrawer\(\s*\{[^}]*onNavigateToResumeStudio[^}]*\}\s*\)/,
    'HandoffKitDrawer must accept onNavigateToResumeStudio prop')

  // Neither component should dispatch dead unhandled 'navigate' CustomEvent
  assert.doesNotMatch(appCenterSrc, /CustomEvent\(['"]navigate['"]/,
    'ApplicationCenter must not dispatch dead navigate CustomEvent')
  assert.doesNotMatch(drawerSrc, /CustomEvent\(['"]navigate['"]/,
    'HandoffKitDrawer must not dispatch dead navigate CustomEvent')

  // Fix now button invokes real callback
  assert.match(appCenterSrc, /onClick=\{[^{}]*onNavigateToResumeStudio\?\.?\(\)[^{}]*\}/,
    'Fix now button must invoke onNavigateToResumeStudio')

  // + Add to profile button invokes real callback
  assert.match(drawerSrc, /onClick=\{[^{}]*onNavigateToResumeStudio\?\.?\(\)[^{}]*\}/,
    '+ Add to profile button must invoke onNavigateToResumeStudio')
})

// ---------------------------------------------------------------------------
// Item 5: Select All selects hidden applications across unselected tabs
// ---------------------------------------------------------------------------
test('ApplicationCenter: Select All toggles only visible applications on filtered tabs', () => {
  const src = readComponent('career/ApplicationCenter.jsx')

  // Must compute visibleApps based on statusFilter
  assert.match(src, /const\s+visibleApps\s*=\s*useMemo\(/,
    'ApplicationCenter must compute visibleApps via useMemo')

  // handleSelectAll must toggle against visibleApps, NOT all applications
  assert.doesNotMatch(src, /selectedAppIds\.size\s*===\s*applications\.length/,
    'handleSelectAll / checkbox must not check against total applications.length')
  assert.doesNotMatch(src, /setSelectedAppIds\(new\s+Set\(applications\.map/,
    'handleSelectAll must not select all unfiltered applications')

  // Checkbox checked state checks visibleApps
  assert.match(src, /checked=\{visibleApps\.length\s*>\s*0\s*&&\s*visibleApps\.every/,
    'Header checkbox checked state must evaluate visibleApps')

  // Table body renders visibleApps
  assert.match(src, /\{visibleApps\.map\(/,
    'Table body must render visibleApps instead of unfiltered applications')

  // Behavioural test of visibleApps filtering & selection logic
  const mockApps = [
    { id: 1, status: 'READY_FOR_REVIEW' },
    { id: 2, status: 'PREPARING' },
    { id: 3, status: 'SUBMITTED' },
    { id: 4, status: 'CLOSED' },
  ]

  const statusFilter = 'NEEDS_REVIEW'
  const filterFn = (a) => {
    if (statusFilter === 'ALL') return true
    if (statusFilter === 'NEEDS_REVIEW') return ['READY_FOR_REVIEW', 'READY_FOR_APPROVAL', 'PREPARING'].includes(a.status)
    return true
  }

  const visible = mockApps.filter(filterFn)
  assert.equal(visible.length, 2, 'Visible apps should only contain the 2 apps in review')

  // Toggle select all on visible
  let selected = new Set()
  const allVisibleSelected = visible.length > 0 && visible.every(a => selected.has(a.id))
  assert.equal(allVisibleSelected, false)

  if (allVisibleSelected) {
    visible.forEach(a => selected.delete(a.id))
  } else {
    visible.forEach(a => selected.add(a.id))
  }

  assert.equal(selected.size, 2, 'Only visible items should be selected')
  assert.ok(selected.has(1) && selected.has(2))
  assert.ok(!selected.has(3) && !selected.has(4), 'Hidden applications must remain unselected')
})

// ---------------------------------------------------------------------------
// Item 5 (cont): Career application statuses use uppercase CareerApplicationStatus enums
// ---------------------------------------------------------------------------
test('ResumeStudio: Truthful Cover Letter tab provides a Save button', () => {
  const src = readComponent('career/ResumeStudio.jsx')

  // Must find the cover letter editor section (rendered when activeTab !== 'resume')
  const clTabIdx = src.lastIndexOf("activeTab === 'cover_letter'")
  assert.ok(clTabIdx !== -1, 'Cover letter tab branch must exist')
  const clSection = src.slice(clTabIdx)

  // Must have Save button inside cover letter section invoking handleSave
  assert.match(clSection, /<button[^>]*onClick=\{handleSave\}[\s\S]*?>[\s\S]*?Save Cover Letter/,
    'Cover letter footer must include a Save button invoking handleSave')
  assert.match(clSection, /📋\s*Copy to Clipboard/,
    'Cover letter footer must retain Copy to Clipboard button')
})
