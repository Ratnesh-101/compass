import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const read = rel => fs.readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')
const find = (...candidates) => {
  for (const rel of candidates) {
    if (fs.existsSync(new URL(`../src/${rel}`, import.meta.url))) return read(rel)
  }
  throw new Error(`none of these exist: ${candidates.join(', ')}`)
}

const modal = () => find('components/career/ExternalProfileImportModal.jsx', 'components/ExternalProfileImportModal.jsx')
const guide = () => find('components/career/LinkedInImportGuide.jsx', 'components/LinkedInImportGuide.jsx')
const api = () => find('services/careerApi.js', 'api/careerApi.js', 'utils/careerApi.js', 'careerApi.js')

test('careerApi exports ingestExternalProfileFile and posts FormData to the file endpoint', () => {
  const src = api()
  assert.match(src, /export\s+(async\s+)?(function|const)\s+ingestExternalProfileFile/)
  assert.ok(src.includes('/intelligence/external-profile-file'))
  assert.ok(src.includes('FormData'))
})

test('import modal accepts pdf, zip, csv and txt', () => {
  assert.match(modal(), /accept=(['"]|\{['"])\.pdf,\.zip,\.csv,\.txt/)
})

test('import modal has the upload and paste headings', () => {
  const src = modal()
  assert.ok(src.includes('Upload what LinkedIn gave you'))
  assert.ok(src.includes('Or paste it'))
})

test('import modal calls the file API and reports the profile back', () => {
  const src = modal()
  assert.ok(src.includes('ingestExternalProfileFile'))
  assert.ok(src.includes('onProfileIngested'))
})

test('import modal checks the 25 MB limit and announces status', () => {
  const src = modal()
  assert.ok(/25\s*\*\s*1024|25\s*MB/.test(src))
  assert.match(src, /role=(['"]status['"]|\{['"]status['"]\})/)
})

test('import modal uses the LinkedInImportGuide', () => {
  const src = modal()
  assert.ok(/import\s+.*LinkedInImportGuide/.test(src))
  assert.ok(src.includes('<LinkedInImportGuide'))
})

test('guide explains both LinkedIn routes and the no-scraping promise', () => {
  const src = guide()
  assert.ok(src.includes('Save to PDF'))
  assert.ok(src.includes('Get a copy of your data'))
  assert.ok(src.includes('never logs in') || src.includes('scrapes'))
})
