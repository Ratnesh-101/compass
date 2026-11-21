import { createRequire } from 'node:module'
// Live check against the deployed Compass site. Needs Node 18+ and playwright-core (set PLAYWRIGHT_CORE to its path
// if it is not resolvable). See scripts/live_checks/README.md. Writes screenshots to the current directory.
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core')
const APP = 'https://compass-farmlytics.vercel.app/'
const b = await chromium.launch({ headless: true })
const p = await (await b.newContext({ viewport: { width: 1366, height: 900 } })).newPage()
const body = () => p.locator('body').innerText(); const cl = s => s.replace(/\s+/g, ' ')
const nav = async l => { await p.locator('aside, nav').getByText(l, { exact: true }).first().click(); await p.waitForTimeout(1800) }
await p.goto(APP, { timeout: 90000 }); await p.waitForTimeout(4000)
// 1. About page
await p.getByText('About / for judges').first().click(); await p.waitForTimeout(1500)
let t = await body(); const claims = t.match(/Nemotron-3[^\n]{0,80}|Llama[^\n]{0,60}|Qwen[^\n]{0,60}/g) || []
console.log(/Nano 30B/.test(t) && /Super 120B/.test(t) && /Ultra 550B/.test(t) && !/Llama|8B MoE|405B/.test(t) ? 'PASS' : 'FAIL', 'About page model names:', claims.join(' || '))
await p.keyboard.press('Escape'); await p.waitForTimeout(600); const x = p.locator('button[aria-label*="lose" i]').first(); if (await x.count()) await x.click().catch(() => {})
// 2. sample week, then tour chat title in history
await p.getByText(/1\. Load a sample week/i).first().click()
await p.locator('#btn-intake-confirm, button:has-text("Add all")').first().waitFor({ timeout: 90000 }); await p.keyboard.press('Enter')
await p.getByText(/Added 8 task/i).first().waitFor({ timeout: 60000 }); await p.waitForTimeout(2500)
await p.getByText(/History & Memory/).first().click(); await p.waitForTimeout(3000); t = await body()
console.log(/Load a sample week/.test(t.split('RECENT CHATS').pop() || t) && !/Add these 8 tasks to my dea/.test(t.split('RECENT CHATS').pop() || '') ? 'PASS' : 'FAIL', 'tour chat title in Recent chats:', cl((t.split('RECENT CHATS').pop() || '').slice(0, 120)))
await p.keyboard.press('Escape'); await p.waitForTimeout(500)
// 3. approval card names the task
await nav('Assistant & planner'); await p.getByText('Planner', { exact: true }).first().click(); await p.waitForTimeout(1200)
const input = p.locator('input[placeholder^="Ask a question"]').first(); let seen = []
for (let attempt = 1; attempt <= 3 && !seen.some(s => /Update task|Schedule \d|Mark|remove/.test(s)); attempt++) {
  await input.fill('Reschedule my coursework tasks to finish the hackathon demo today'); await p.getByText('Ask Assistant', { exact: true }).first().click()
  let got = false; for (let i = 0; i < 100; i++) { await p.waitForTimeout(1000); if (await p.getByRole('button', { name: /Reject/i }).count()) { got = true; break } }
  if (got) { const m = (await body()).match(/Action Confirmation Gate[\s\S]{0,230}/); const card = cl(m ? m[0] : ''); seen.push(card); console.log('attempt', attempt, 'card:', card); await p.screenshot({ path: `verify-card-${attempt}.png` }); await p.getByRole('button', { name: /Reject/i }).first().click(); await p.waitForTimeout(20000) } else console.log('attempt', attempt, 'no approval gate shown')
}
const ok = seen.length > 0 && seen.every(s => !/Task #\d+/.test(s) && !/time slot for "event"/.test(s))
console.log(ok ? 'PASS' : 'FAIL', 'approval cards use plain wording (no "Task #id", no "event" placeholder)')
await b.close()
