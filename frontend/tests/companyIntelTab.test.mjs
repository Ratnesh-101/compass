import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const srcDir = path.resolve(__dirname, '../src')

test('Frontend 11-15: Static contract audit of Company Intel Tab in ApplicationWorkspaceModal', () => {
  const code = fs.readFileSync(path.join(srcDir, 'components/career/ApplicationWorkspaceModal.jsx'), 'utf8')

  // 1. Order of four short sections
  const orderCheck = [
    'What they care about',
    'What this role works on',
    'Challenges to know',
    'Talking points for your application',
  ]
  let lastPos = 0
  for (const title of orderCheck) {
    const pos = code.indexOf(title)
    assert.ok(pos > lastPos, `Section "${title}" must appear in correct sequence`)
    lastPos = pos
  }

  // 2. Real headings (h3) and lists (ul and li)
  assert.ok(code.includes('Company intel for {opportunity.company_name}'), 'Must have real header for real company')
  assert.ok(code.includes('<ul'), 'Lists must use ul')
  assert.ok(code.includes('<li'), 'Lists must use li')

  // 3. Line icons in currentColor (Target, Briefcase, AlertCircle, MessageSquare)
  assert.ok(code.includes('sec.icon size={16}'), 'Section icons must use 16px line icon')
  assert.ok(code.includes("color: 'currentColor'"), 'Section icons must be in currentColor')

  // 4. Sources collapsible and secure links
  assert.ok(code.includes('Sources ({companyIntel.sources.length})'), 'Must show Sources count')
  assert.ok(code.includes('rel="noopener noreferrer"'), 'Sources links must have rel="noopener noreferrer"')
  assert.ok(code.includes('target="_blank"'), 'Sources links must open in new tab')

  // 5. Loading skeleton, error, and empty states
  assert.ok(code.includes('aria-busy="true"'), 'Loading skeleton must designate aria-busy')
  assert.ok(code.includes('Refresh Intel'), 'Single retry action must be provided via Refresh Intel button in header')
  assert.ok(!code.includes('Try again'), 'Duplicate Try again buttons must be removed from empty and error boxes')
  assert.ok(code.includes('We could not find enough reliable information about this company.'), 'Empty state message must match spec')
  assert.ok(code.includes("We couldn't generate company intel right now. Please try again with Refresh Intel."), 'Error state guidance message must match spec')

  // 6. Old brief fallback notice
  assert.ok(
    code.includes('This summary is from an older version. Refresh Intel for a clearer one.'),
    'Old briefs must show the upgrade notice'
  )

  // 7. No em dashes in interface code
  assert.ok(!code.includes('\u2014'), 'Code must not contain em dashes')

  // 8. No pill buttons or colored left borders in Company Intel
  assert.ok(!code.includes('borderLeft: \'3px solid var(--brand)\''), 'Must remove colored left borders')
  assert.ok(!code.includes('borderLeft: \'3px solid #ef4444\''), 'Must remove colored red borders')
  assert.ok(!code.includes('borderLeft: \'3px solid #3b82f6\''), 'Must remove colored blue borders')

  // 9. Accessibility
  assert.ok(code.includes('aria-live="polite"'), 'Refresh state must be announced via aria-live')
  assert.ok(code.includes('refreshBtnRef'), 'Focus must be maintained on refresh button')
})

test('Frontend 16-17: Overflow wrap and responsive 2-column to 1-column layout', () => {
  const css = fs.readFileSync(path.join(srcDir, 'index.css'), 'utf8')
  assert.ok(css.includes('.company-intel-grid'), 'index.css must define .company-intel-grid')
  assert.ok(css.includes('grid-template-columns: repeat(2, minmax(0, 1fr));'), 'Must use 2-column grid on desktop')
  assert.ok(css.includes('grid-template-columns: 1fr;'), 'Must collapse to 1-column on mobile')

  const code = fs.readFileSync(path.join(srcDir, 'components/career/ApplicationWorkspaceModal.jsx'), 'utf8')
  assert.ok(code.includes('overflowWrap: \'break-word\''), 'Must wrap long words to prevent overflow')
  assert.ok(code.includes('wordBreak: \'break-word\''), 'Must break long unbroken tokens')
})

test('Frontend 18-20: Other tabs integrity and clean API layer', () => {
  const code = fs.readFileSync(path.join(srcDir, 'components/career/ApplicationWorkspaceModal.jsx'), 'utf8')

  // Verify all other tabs remain untouched and active
  const expectedTabs = ['overview', 'company_intel', 'job_analysis', 'resume', 'cover_letter', 'checklist', 'handoff']
  for (const t of expectedTabs) {
    assert.ok(code.includes(`key: '${t}'`), `Tab ${t} must remain defined`)
  }

  // Refresh Intel button keeps same secondary style
  assert.ok(code.includes('radar-card-btn radar-card-btn-secondary'), 'Refresh button must use standard secondary class')
})
