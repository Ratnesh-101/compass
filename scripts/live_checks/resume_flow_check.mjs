import { createRequire } from 'node:module'
import fs from 'node:fs'
// Live check against the deployed Compass site. Needs Node 18+ and playwright-core (set PLAYWRIGHT_CORE to its path
// if it is not resolvable). See scripts/live_checks/README.md. Writes screenshots to the current directory.
// A resume file is required: set RESUME_FILE to the path of a .docx/.pdf/.txt resume.
const RESUME_FILE = process.env.RESUME_FILE
if (!RESUME_FILE) { console.error('Set RESUME_FILE to a resume file path'); process.exit(2) }
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core')
const out = 'resume-live'; fs.mkdirSync(out, { recursive: true })
const b = await chromium.launch({ headless: true }); const p = await (await b.newContext({ viewport:{width:1366,height:900}})).newPage()
const body = () => p.locator('body').innerText()
await p.goto('https://compass-farmlytics.vercel.app/'); await p.waitForTimeout(4000)
await p.locator('aside, nav').getByText('Radar, Resumes & Apps', { exact: false }).first().click(); await p.waitForTimeout(2500)
await p.screenshot({ path: `${out}/1-career.png` })
await p.locator('input[type=file]').first().setInputFiles(RESUME_FILE)
await p.getByText(/Looks right, save and find internships/i).first().waitFor({ timeout: 90000 })
await p.screenshot({ path: `${out}/2-after-upload.png` })
await p.getByText(/Looks right, save and find internships/i).first().click(); await p.waitForTimeout(60000)
await p.screenshot({ path: `${out}/2b-matches.png` })
let t = await body()
console.log('raw errors:', /Traceback|\[object|Internal Server|undefined/.test(t), '| Confirmed eligible:', /Confirmed eligible/.test(t), '| worldwide chip:', /open worldwide/i.test(t))
const cards = p.locator('button:has-text("Prepare Application"):not([disabled])')
console.log('enabled prepare buttons:', await cards.count())
if (await cards.count()) { await cards.first().scrollIntoViewIfNeeded(); await cards.first().click(); await p.waitForTimeout(60000); await p.screenshot({ path: `${out}/3-prepared.png` })
  t = await body(); { const k=t.indexOf('Verified Matching'); console.log('SKILLS:', t.slice(Math.max(0,k-5), k+260).split(String.fromCharCode(10)).join(' | ')) } console.log('cover letter shown:', /cover letter/i.test(t), '| mark as applied count:', await p.getByText(/Mark as applied/i).count(), '| raw error:', /Traceback|\[object|Internal Server/.test(t))
  const sub = p.getByText(/I submitted this externally/i)
  for (const tab of ['Checklist', 'Submit', 'Submission', 'Apply']) { if (await sub.count()) break; const tb = p.getByRole('tab', { name: new RegExp(tab, 'i') }).or(p.locator('button', { hasText: new RegExp('^\s*' + tab, 'i') })).first(); if (await tb.count()) { await tb.click().catch(()=>{}); await p.waitForTimeout(1500) } }
  console.log('submitted-externally button found:', await sub.count())
  if (await sub.count()) { await sub.first().scrollIntoViewIfNeeded(); await sub.first().click(); await p.waitForTimeout(5000); await p.screenshot({ path: `${out}/4-submitted.png` }); const tt = await body(); console.log('marked submitted:', /You marked this as submitted/.test(tt)) }
}
fs.writeFileSync(`${out}/text.txt`, t); await b.close()
