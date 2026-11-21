// Live check against the deployed Compass site. Needs Node 18+ and playwright-core (set PLAYWRIGHT_CORE to its path
// if it is not resolvable). See scripts/live_checks/README.md. Writes screenshots to the current directory.
// Compass browser check. Usage: node e2e.mjs <baseUrl> <outDir> [local|live]
// Runs as a brand-new guest. Prints PASS/FAIL/SKIP per check and writes screenshots + results.json.
import { createRequire } from 'node:module'
import fs from 'node:fs'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core')

const [base, outDir, mode = 'local'] = process.argv.slice(2)
fs.mkdirSync(outDir, { recursive: true })
const results = []
const consoleErrors = []
const pageErrors = []

function record(name, status, note = '') {
  results.push({ name, status, note })
  console.log(`${status.padEnd(4)}  ${name}${note ? '  -- ' + note : ''}`)
}

const browser = await chromium.launch({ headless: true })

function attach(page) {
  page.on('pageerror', e => pageErrors.push(String(e.message).slice(0, 200)))
  page.on('console', m => {
    if (m.type() !== 'error') return
    const t = m.text()
    if (/Failed to load resource|net::ERR|status of (401|403|404|429)/i.test(t)) return // network noise, judged elsewhere
    consoleErrors.push(t.slice(0, 200))
  })
}

async function step(page, name, fn) {
  try {
    const note = await fn()
    record(name, 'PASS', note || '')
    return true
  } catch (e) {
    record(name, 'FAIL', String(e.message).split('\n')[0].slice(0, 220))
    try { await page.screenshot({ path: `${outDir}/FAIL-${name.replace(/[^a-z0-9]+/gi, '_').slice(0, 50)}.png` }) } catch {}
    return false
  }
}

async function goTab(page, label) {
  const loc = page.locator('aside, nav').getByText(label, { exact: true }).first()
  await loc.click({ timeout: 8000 })
  await page.waitForTimeout(600)
}

const bodyText = async page => (await page.locator('body').innerText()).replace(/\n{2,}/g, '\n')

// ------------------------------------------------------------------ desktop
const ctx = await browser.newContext({ viewport: { width: 1366, height: 768 } })
const page = await ctx.newPage()
attach(page)

let t0 = Date.now()
await step(page, 'D1 first screen loads with the plain welcome', async () => {
  await page.goto(base, { waitUntil: 'domcontentloaded', timeout: 150000 })
  await page.getByText(/Compass keeps your deadlines, coursework and internship hunt/i).first().waitFor({ timeout: 150000 })
  await page.screenshot({ path: `${outDir}/01-first-screen.png` })
  return `${Date.now() - t0} ms to the welcome`
})

await step(page, 'D2 no engineer jargon, cost counter or database name on the first screen', async () => {
  const t = await bodyText(page)
  const bad = t.match(/Load Judge Persona|pgvector|HNSW|Neon Connected|Telemetry inspection|\$\s?0\.\d{3,}|\d+ calls\b/i)
  if (bad) throw new Error('found: ' + bad[0])
})

await step(page, 'D3 tour card and the three big buttons are there', async () => {
  for (const re of [/New here\? Take the 60-second tour/i, /1\. Load a sample week/i, /Find internships/i, /Plan my week/i, /Ask a question/i]) {
    await page.getByText(re).first().waitFor({ timeout: 5000 })
  }
})

await step(page, 'D4 tour step 1 loads a sample week through the confirm card (Enter confirms)', async () => {
  await page.getByText(/1\. Load a sample week/i).first().click()
  // wait for the CONFIRM CARD (the user's own message also says 8 tasks), not for that text
  await page.getByText(/Nothing (has been added|is saved)/i).first().waitFor({ timeout: 90000 })
  await page.locator('#btn-intake-confirm, button:has-text("Add all")').first().waitFor({ timeout: 90000 })
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${outDir}/02-sample-week-card.png` })
  const focused = await page.evaluate(() => document.activeElement && (document.activeElement.id || document.activeElement.innerText || '').slice(0, 40))
  if (!/btn-intake-confirm|Add all/i.test(focused || '')) throw new Error('the confirm button is not focused (focus is on: ' + focused + ')')
  await page.keyboard.press('Enter')
  await page.getByText(/Added 8 task/i).first().waitFor({ timeout: 60000 })
  await page.screenshot({ path: `${outDir}/03-sample-week-added.png` })
})

await step(page, 'D5 the 8 sample tasks appear on the Timeline', async () => {
  await goTab(page, 'Timeline')
  await page.getByText('Operating Systems assignment').first().waitFor({ timeout: 20000 })
  const t = await bodyText(page)
  for (const title of ['Hackathon project proposal', 'Fix login bug in portfolio site', 'Write unit tests for the API']) {
    if (!t.includes(title)) throw new Error('missing task: ' + title)
  }
  await page.screenshot({ path: `${outDir}/04-timeline.png` })
})

await step(page, 'D6 dashboard counts the 8 tasks', async () => {
  await goTab(page, 'Dashboard')
  await page.waitForTimeout(1200)
  const t = await bodyText(page)
  if (!/TOTAL TASKS\s*\n?\s*8\b/i.test(t)) throw new Error('total tasks is not 8')
  await page.screenshot({ path: `${outDir}/05-dashboard-8.png` })
})

let chatInput = null
await step(page, 'D7 chat input says "Ask anything, for example: Plan my week"', async () => {
  await goTab(page, 'Assistant & planner')
  chatInput = page.locator('textarea').first()
  await chatInput.waitFor({ timeout: 15000 })
  const ph = await chatInput.getAttribute('placeholder')
  if (!/Ask anything, for example: Plan my week/i.test(ph || '')) throw new Error('placeholder is: ' + ph)
  await page.screenshot({ path: `${outDir}/06-chat-empty.png` })
})

await step(page, 'D8 plain labels in the chat toolbar (no Brief/Balanced/Exploratory, no "Connected, memory on")', async () => {
  const t = await bodyText(page)
  const bad = t.match(/Exploratory|Connected, memory on/)
  if (bad) throw new Error('still shows: ' + bad[0])
})

await step(page, 'D9 "hi" gets an instant friendly reply (no model wait)', async () => {
  const start = Date.now()
  await chatInput.fill('hi')
  await page.keyboard.press('Enter')
  await page.getByText(/I'm Compass\. I can plan your week/i).first().waitFor({ timeout: 15000 })
  const ms = Date.now() - start
  await page.screenshot({ path: `${outDir}/07-hi-reply.png` })
  if (ms > 6000) throw new Error(`took ${ms} ms`)
  return `${ms} ms`
})

await step(page, 'D10 chat input grows with a long message', async () => {
  const before = (await chatInput.boundingBox())?.height || 0
  await chatInput.fill(Array.from({ length: 7 }, (_, i) => `line ${i + 1} of a long planning question`).join('\n'))
  await page.waitForTimeout(400)
  const after = (await chatInput.boundingBox())?.height || 0
  if (!(after > before + 20)) throw new Error(`height ${before} -> ${after}`)
  await chatInput.fill('')
})

await step(page, 'D11 Schedule: no misleading "Edit hours" control', async () => {
  await goTab(page, 'Schedule')
  await page.waitForTimeout(1200)
  const t = await bodyText(page)
  if (/Edit hours/i.test(t)) throw new Error('"Edit hours" is still shown')
  if (!/Planning hours/i.test(t)) throw new Error('no "Planning hours" text')
  await page.screenshot({ path: `${outDir}/08-schedule.png` })
})

await step(page, 'D12 Career: resume-first start and plain wording', async () => {
  await goTab(page, 'Career Copilot')
  await page.waitForTimeout(2500)
  const t = await bodyText(page)
  if (!/Upload your resume to begin/i.test(t)) throw new Error('no "Upload your resume to begin"')
  const bad = t.match(/Evidence-Based Resume Studio|Master Source of Truth|Zero Hallucination|Live Intel|Manual Handoff/)
  if (bad) throw new Error('jargon still shown: ' + bad[0])
  await page.screenshot({ path: `${outDir}/09-career.png` })
})

await step(page, 'D13 sidebar section is "My areas"; "About / for judges" opens', async () => {
  await goTab(page, 'Dashboard')
  const t = await bodyText(page)
  if (!/My areas/i.test(t) || /Context Domains/i.test(t)) throw new Error('sidebar heading wrong')
  await page.getByText('About / for judges').first().click()
  await page.waitForTimeout(900)
  await page.screenshot({ path: `${outDir}/10-about-judges.png` })
  await page.keyboard.press('Escape')
})

// ------------------------------------------------------------------ live-only (needs the AI model)
if (mode === 'live') {
  await step(page, 'L1 "next Wednesday" shows a preview with the right weekday before saving', async () => {
    await goTab(page, 'Assistant & planner')
    const input = page.locator('textarea').first()
    await input.fill('remind me to submit my lab report by next Wednesday')
    await page.keyboard.press('Enter')
    await page.getByText(/remind me to submit my lab report/i).last().waitFor({ timeout: 10000 })
    const btn = page.locator('#btn-intake-confirm, button:has-text("Add")').last()
    await btn.waitFor({ timeout: 90000 })
    await page.waitForTimeout(800)
    const t = await bodyText(page)
    if (!/Wed/.test(t.split('remind me to submit my lab report').pop())) throw new Error('the preview does not show Wednesday')
    await page.screenshot({ path: `${outDir}/L1-wednesday-preview.png` })
    await page.keyboard.press('Enter')
    await page.getByText(/Added 1 task/i).first().waitFor({ timeout: 60000 })
  })
  await step(page, 'L2 the README prompt reaches a web search and answers', async () => {
    const input = page.locator('textarea').first()
    await input.fill('What is the official submission deadline for the Nebius x NVIDIA AI Hackathon?')
    await page.keyboard.press('Enter')
    await page.waitForFunction(() => /deadline|devpost|october|november|december/i.test(document.body.innerText.split('Nebius x NVIDIA AI Hackathon?').pop() || ''), null, { timeout: 120000 })
    await page.waitForTimeout(4000)
    await page.screenshot({ path: `${outDir}/L2-readme-prompt.png` })
  })
  await step(page, 'L3 a long answer finishes, or Continue extends the SAME bubble', async () => {
    const input = page.locator('textarea').first()
    await input.fill('Explain 12 sorting algorithms with a short python example each. End with the exact line END-OF-LIST.')
    await page.keyboard.press('Enter')
    await page.waitForTimeout(8000)
    await page.waitForFunction(() => /END-OF-LIST/.test(document.body.innerText) || /Continue response/.test(document.body.innerText), null, { timeout: 150000 })
    await page.waitForTimeout(3000)
    let note = 'finished with END-OF-LIST'
    const cont = page.getByRole('button', { name: /Continue response/ }).first()
    if (await cont.count()) {
      const userBubblesBefore = await page.getByText('Continue response', { exact: true }).count()
      await cont.click()
      await page.waitForTimeout(15000)
      await page.waitForFunction(() => !/Continuing…/.test(document.body.innerText), null, { timeout: 150000 })
      const userBubblesAfter = await page.getByText('Continue response', { exact: true }).count()
      if (userBubblesAfter > userBubblesBefore) throw new Error('Continue added a new "Continue response" question bubble')
      note = 'was cut off; Continue extended the same answer'
    }
    await page.screenshot({ path: `${outDir}/L3-long-answer.png` })
    return note
  })
}

// ------------------------------------------------------------------ phone width
const mctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
const mp = await mctx.newPage()
attach(mp)
await step(mp, 'M1 phone: first screen fits with no sideways scrolling', async () => {
  await mp.goto(base, { waitUntil: 'domcontentloaded', timeout: 150000 })
  await mp.getByText(/Compass keeps your deadlines/i).first().waitFor({ timeout: 150000 })
  await mp.waitForTimeout(1500)
  const w = await mp.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }))
  await mp.screenshot({ path: `${outDir}/M1-phone-first.png` })
  if (w.sw > w.iw + 2) throw new Error(`page is ${w.sw}px wide in a ${w.iw}px window`)
})
for (const [label, shot] of [['Timeline', 'M2'], ['Compass', 'M3'], ['Schedule', 'M4'], ['Career', 'M5']]) {
  await step(mp, `${shot} phone: ${label} fits with no sideways scrolling`, async () => {
    const nav = mp.locator('nav, [role="navigation"], footer').getByText(new RegExp(`^${label}`, 'i')).last()
    await nav.click({ timeout: 8000 })
    await mp.waitForTimeout(2000)
    const w = await mp.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }))
    await mp.screenshot({ path: `${outDir}/${shot}-phone-${label}.png` })
    if (w.sw > w.iw + 2) throw new Error(`page is ${w.sw}px wide in a ${w.iw}px window`)
  })
}

// ------------------------------------------------------------------ errors
if (pageErrors.length) record('E1 no uncaught JavaScript errors', 'FAIL', pageErrors.slice(0, 3).join(' | '))
else record('E1 no uncaught JavaScript errors', 'PASS')
if (consoleErrors.length) record('E2 console errors', 'WARN', `${consoleErrors.length}: ` + consoleErrors.slice(0, 2).join(' | '))
else record('E2 console errors', 'PASS')

fs.writeFileSync(`${outDir}/results.json`, JSON.stringify(results, null, 2))
const c = s => results.filter(r => r.status === s).length
console.log(`\nSUMMARY: ${c('PASS')} pass, ${c('FAIL')} fail, ${c('WARN')} warn`)
await browser.close()
