import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const resumeStudioPath = path.resolve(__dirname, '../src/components/career/ResumeStudio.jsx')
const careerCopilotPath = path.resolve(__dirname, '../src/components/CareerCopilot.jsx')

test('ResumeStudio accepts onSaved prop with default no-op', () => {
  const source = fs.readFileSync(resumeStudioPath, 'utf8')
  assert.match(
    source,
    /export\s+default\s+function\s+ResumeStudio\(\s*\{\s*onSaved\s*=\s*\(\)\s*=>\s*\{\s*\}\s*\}\s*=\s*\{\s*\}\s*\)/,
    'ResumeStudio should accept onSaved with default no-op'
  )
})

test('CareerCopilot passes onSaved={handleResumeSaved} to ResumeStudio', () => {
  const source = fs.readFileSync(careerCopilotPath, 'utf8')
  assert.match(
    source,
    /<ResumeStudio\s+onSaved=\{handleResumeSaved\}\s*\/>/,
    'CareerCopilot should pass onSaved={handleResumeSaved} to ResumeStudio'
  )
})

test('ResumeStudio calls onSaved after master save in handleSaveResume', () => {
  const source = fs.readFileSync(resumeStudioPath, 'utf8')
  const handleSaveResumeStart = source.indexOf('const handleSaveResume')
  assert.ok(handleSaveResumeStart !== -1, 'handleSaveResume must exist')
  const handleSaveResumeBody = source.slice(
    handleSaveResumeStart,
    source.indexOf('const handleRunValidation')
  )

  // Must check for master save branch calling onSaved
  assert.match(
    handleSaveResumeBody,
    /if\s*\(\s*isMaster\s*\)\s*\{\s*onSaved\?\.\(\)/,
    'handleSaveResume must call onSaved when isMaster is true'
  )
  // Must set saveKind accordingly
  assert.match(
    handleSaveResumeBody,
    /setSaveKind\(\s*isMaster\s*\?\s*['"]master['"]\s*:\s*['"]tailored['"]\s*\)/,
    'handleSaveResume must set saveKind based on isMaster'
  )
})

test('ResumeStudio calls onSaved after extraction commit in handleCommitExtraction', () => {
  const source = fs.readFileSync(resumeStudioPath, 'utf8')
  const fnStart = source.indexOf('const handleCommitExtraction')
  assert.ok(fnStart !== -1, 'handleCommitExtraction must exist')
  const fnBody = source.slice(
    fnStart,
    source.indexOf('const handleImportGitHubRepo')
  )

  assert.match(
    fnBody,
    /onSaved\?\.\(\)/,
    'handleCommitExtraction must call onSaved after commit'
  )
  assert.match(
    fnBody,
    /setSaveKind\(/,
    'handleCommitExtraction must update saveKind'
  )
})

test('ResumeStudio calls onSaved on GitHub intelligence imports that update master resume', () => {
  const source = fs.readFileSync(resumeStudioPath, 'utf8')

  const repoImportStart = source.indexOf('const handleImportGitHubRepo')
  const repoImportBody = source.slice(
    repoImportStart,
    source.indexOf('const handleImportGitHubSkills')
  )
  assert.match(
    repoImportBody,
    /onSaved\?\.\(\)/,
    'handleImportGitHubRepo must call onSaved'
  )

  const skillsImportStart = source.indexOf('const handleImportGitHubSkills')
  const skillsImportBody = source.slice(
    skillsImportStart,
    source.indexOf('const handleDraftCoverLetter')
  )
  assert.match(
    skillsImportBody,
    /onSaved\?\.\(\)/,
    'handleImportGitHubSkills must call onSaved'
  )
})

test('ResumeStudio success banner profile sentence is conditional on master save and neutral "Saved." for other saves', () => {
  const source = fs.readFileSync(resumeStudioPath, 'utf8')

  // Check state declaration
  assert.match(
    source,
    /const\s*\[\s*saveKind\s*,\s*setSaveKind\s*\]\s*=\s*useState\(/,
    'saveKind state must be defined'
  )

  // Check conditional banner message
  assert.match(
    source,
    /saveKind\s*===\s*['"]master['"]\s*\?\s*['"][^'"]*Your resume and your internship profile are up to date\.[^'"]*['"]\s*:\s*['"][^'"]*Saved\.[^'"]*['"]/,
    'Banner must conditionally display profile sentence for master save and neutral "Saved." for other saves'
  )

  // Verify only one role="status" banner div exists for saveSuccess (no duplicated banner markup)
  const roleStatusMatches = source.match(/role="status"[^>]*aria-live="polite"[^>]*style=\{\{[^}]*#dcfce7/g)
  assert.equal(
    roleStatusMatches?.length,
    1,
    'Banner markup should not be duplicated'
  )
})
