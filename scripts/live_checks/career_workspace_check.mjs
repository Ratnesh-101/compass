import { createRequire } from 'node:module'
import fs from 'node:fs'
// Live check against the deployed Compass site. Needs Node 18+ and playwright-core (set PLAYWRIGHT_CORE to its path
// if it is not resolvable). See scripts/live_checks/README.md. Writes screenshots to the current directory.
// A resume file is required: set RESUME_FILE to the path of a .docx/.pdf/.txt resume.
const RESUME_FILE = process.env.RESUME_FILE
if (!RESUME_FILE) { console.error('Set RESUME_FILE to a resume file path'); process.exit(2) }
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core')
const APP = 'https://compass-farmlytics.vercel.app/', RESUME = RESUME_FILE, TITLE = 'GSoC 2026 Open Source Contributor'
const out = 'career-fixes-live3'; fs.mkdirSync(out, { recursive: true })
const cl = s => String(s).replace(/\s+/g, ' '); const body = p => p.locator('body').innerText()
const report = (ok, name, d = '') => console.log((ok ? 'PASS ' : 'FAIL ') + name + (d ? '  -- ' + cl(d).slice(0, 300) : ''))
const b = await chromium.launch({ headless: true })
const p = await (await b.newContext({ viewport: { width: 1366, height: 1000 } })).newPage()
await p.goto(APP, { timeout: 90000 }); await p.waitForTimeout(4000)
await p.locator('aside, nav').getByText('Radar, Resumes & Apps', { exact: true }).first().click()
await p.locator('input[type=file]').first().setInputFiles(RESUME)
await p.getByText(/Looks right, save and find internships/i).first().waitFor({ timeout: 90000 }); await p.getByText(/Looks right, save and find internships/i).first().click(); await p.waitForTimeout(40000)
const cardBtn = () => p.locator(`xpath=(//*[contains(normalize-space(.),'${TITLE}') and .//button[contains(.,'Prepare Application')]])[last()]//button[contains(.,'Prepare Application')]`).first()
const openChecklist = async () => { await cardBtn().scrollIntoViewIfNeeded(); await cardBtn().click(); await p.waitForTimeout(40000); await p.getByText(/^\s*Checklist/).first().click().catch(() => {}); await p.waitForTimeout(2500) }
const center = async () => { await p.getByText('Application Center', { exact: true }).first().click(); await p.waitForTimeout(4500) }
const dateIn = () => p.locator('input[type=date]').first()
const closeModal = async () => { await p.getByRole('button', { name: /Done & Return to Radar/i }).first().click(); await p.waitForTimeout(2500) }
try {
  await openChecklist(); const first = await dateIn().inputValue(); console.log('INFO prepared with automatic deadline:', first)
  await dateIn().fill(''); await p.getByRole('button', { name: /Save Status/i }).first().click(); await p.waitForTimeout(6000); await closeModal()
  await center(); const t1 = await body(p); const listed = t1.includes(first); await p.screenshot({ path: `${out}/center-after-clear.png` })
  await p.getByText('Internship Radar', { exact: true }).first().click(); await p.waitForTimeout(3000)
  await openChecklist(); const reopened = await dateIn().inputValue(); await p.screenshot({ path: `${out}/reopened.png` })
  report(first !== '' && !listed && reopened === '', 'fix7 a cleared deadline stays cleared (Application Center and after reopening the same application)', `prepared="${first}" still-in-list=${listed} reopened="${reopened}"`)
  // fix 2 on the same application
  await p.getByText('Official Submission', { exact: true }).first().click().catch(() => {}); await p.waitForTimeout(2000)
  const ext = p.getByText(/I submitted this externally/i).first()
  if (!(await ext.count())) { console.log('INFO fix2 button not found; buttons:', cl((await p.locator('button').allInnerTexts()).join(' | ')).slice(0, 300)); await p.screenshot({ path: `${out}/fix2-nobutton.png` }) }
  else {
    await ext.scrollIntoViewIfNeeded(); await ext.click(); await p.waitForTimeout(7000); await p.screenshot({ path: `${out}/fix2-clicked.png` })
    const toast = (await body(p)).match(/You marked this as submitted[^\n]{0,90}/)?.[0] || '(no toast text)'
    await closeModal(); await center(); const t2 = await body(p); await p.screenshot({ path: `${out}/fix2-center.png` })
    const plus14 = new Date(Date.now() + 14 * 864e5).toISOString().slice(0, 10)
    report(/Applied \(1\)/.test(t2) && t2.includes(plus14), 'fix2 "I submitted this externally" moves it to Applied and schedules the follow-up about 14 days out', `toast="${toast}" Applied(1)=${/Applied \(1\)/.test(t2)} follow-up ${plus14} shown=${t2.includes(plus14)}`)
  }
} catch (e) { console.log('FAIL script error: ' + String(e).split('\n')[0].slice(0, 220)) }
await b.close()
