import { createRequire } from 'node:module'
import fs from 'node:fs'
// Live check against the deployed Compass site. Needs Node 18+ and playwright-core (set PLAYWRIGHT_CORE to its path
// if it is not resolvable). See scripts/live_checks/README.md. Writes screenshots to the current directory.
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core')
const APP = 'https://compass-farmlytics.vercel.app/'
const out = 'judges-live4'; fs.mkdirSync(out, { recursive: true })
const log = (...a) => console.log(...a)
const clean = s => String(s).replace(/\s+/g, ' ')
const b = await chromium.launch({ headless: true })
const p = await (await b.newContext({ viewport: { width: 1366, height: 900 } })).newPage()
const body = () => p.locator('body').innerText()
const nav = async l => { await p.locator('aside, nav').getByText(l, { exact: true }).first().click(); await p.waitForTimeout(1500) }
const run = async (id, fn) => { try { await fn() } catch (e) { log('FAIL ' + id + ' -- script error: ' + String(e).split('\n')[0].slice(0, 170)) } }

await p.goto(APP, { timeout: 90000 }); await p.waitForTimeout(4000)
await p.getByText(/1\. Load a sample week/i).first().click()
await p.locator('#btn-intake-confirm, button:has-text("Add all")').first().waitFor({ timeout: 90000 }); await p.keyboard.press('Enter')
await p.getByText(/Added 8 task/i).first().waitFor({ timeout: 60000 }); await p.waitForTimeout(1500)
await nav('Timeline'); const tlBefore = clean((await body()).match(/Showing[\s\S]*/)?.[0] || '')

await nav('Assistant & planner'); await p.getByText('Planner', { exact: true }).first().click(); await p.waitForTimeout(1200)
const input = p.locator('input[placeholder^="Ask a question"]').first()
async function ask(goal, label, waitFor, maxS = 150) {
  await input.fill(goal); const t0 = Date.now(); await p.getByText('Ask Assistant', { exact: true }).first().click()
  let hit = null
  for (let i = 0; i < maxS; i++) { await p.waitForTimeout(1000); const t = await body()
    if (waitFor.test(t)) { hit = Math.round((Date.now() - t0) / 1000); break } }
  await p.waitForTimeout(800); await p.screenshot({ path: `${out}/${label}.png` })
  return hit
}

// --- approval gate, three attempts (was 9s once and a 120s timeout once)
for (let n = 1; n <= 3; n++) {
  await run('gate' + n, async () => {
    const s = await ask('Reschedule my coursework tasks to finish the hackathon demo today', 'gate' + n, /Authorize Changes|Reject \/ Re-plan/i, 150)
    log(`${s ? 'PASS' : 'FAIL'} J4 attempt ${n}: approval gate ${s ? 'shown after ' + s + 's' : 'NOT shown within 150s'}`)
    if (!s) log('   page tail:', clean((await body()).slice(-500)))
    if (s && n === 1) {
      const card = (await body()).match(/Action Confirmation Gate[\s\S]{0,230}/); log('   card:', clean(card ? card[0] : ''))
      await p.locator('textarea[placeholder*="revision" i], input[placeholder*="revision" i], textarea[placeholder*="guidance" i], input[placeholder*="guidance" i]').first().fill('Do not postpone my Operating Systems assignment')
      await p.getByRole('button', { name: /Reject/i }).first().click()
      let finished = false; for (let i = 0; i < 120; i++) { await p.waitForTimeout(1000); if (i > 6 && !(await p.getByText('Stop', { exact: true }).count()) && !(await p.getByText(/Still thinking/i).count())) { finished = true; break } }
      await p.screenshot({ path: `${out}/replan.png` })
      log(`${finished ? 'PASS' : 'FAIL'} J4b reject + guidance → re-plan finished; tail:`, clean((await body()).split('Ask Assistant').pop()).slice(0, 300))
    } else if (s) { // leave the pending action alone but reject so the next ask is clean
      await p.getByRole('button', { name: /Reject/i }).first().click().catch(() => {}); await p.waitForTimeout(15000)
    }
  })
}
await run('unchanged', async () => {
  await nav('Timeline'); const tlAfter = clean((await body()).match(/Showing[\s\S]*/)?.[0] || '')
  log(`${tlBefore === tlAfter ? 'PASS' : 'FAIL'} J4c task list identical after rejected / abandoned plans`)
})

// --- ingest in the Planner
await run('ingest', async () => {
  await nav('Assistant & planner'); await p.getByText('Planner', { exact: true }).first().click().catch(() => {}); await p.waitForTimeout(1200)
  const s = await ask('Ingest contest schedule: https://nebiusglobalaihackathon.devpost.com/details/dates', 'ingest', /Authorize Changes|Reject \/ Re-plan|requires approval/i, 150)
  const t = await body(); log(`${s ? 'PASS' : 'FAIL'} J6 ingest in the Planner stops for approval (${s || '>150'}s):`, clean((t.match(/Action Confirmation Gate[\s\S]{0,260}/) || [t.slice(-300)])[0]))
  if (s && await p.getByRole('button', { name: /Authorize Changes/i }).count()) {
    await p.getByRole('button', { name: /Authorize Changes/i }).first().click()
    let fin = false; for (let i = 0; i < 120; i++) { await p.waitForTimeout(1000); if (i > 5 && !(await p.getByText('Stop', { exact: true }).count()) && !(await p.getByText(/Still thinking/i).count())) { fin = true; break } }
    await p.screenshot({ path: `${out}/ingest-authorised.png` })
    log(`${fin ? 'PASS' : 'FAIL'} J6b authorised ingest completes; tail:`, clean((await body()).split('Ask Assistant').pop()).slice(0, 320))
    const r = await ask('What did we ingest from Devpost dates?', 'recall', /Past Plans \(\d+\)[\s\S]{40,}/, 90); await p.waitForTimeout(8000)
    log('INFO J6c recall:', clean((await body()).split('Ask Assistant').pop()).slice(0, 320))
  }
})

// --- share link end to end
await run('share', async () => {
  await nav('Assistant & planner'); await p.getByText('Chat', { exact: true }).first().click().catch(() => {}); await p.waitForTimeout(1500)
  await p.getByText(/History & Memory/).first().click(); await p.waitForTimeout(2000)
  const menu = p.locator('button[aria-label*="more" i], button[aria-label*="options" i], button[title*="more" i]').first(); if (await menu.count()) { await menu.click().catch(() => {}); await p.waitForTimeout(800) }
  await p.getByText(/^Share/).first().click(); await p.waitForTimeout(2000)
  await p.getByRole('button', { name: /Create share link/i }).click(); await p.waitForTimeout(5000)
  await p.screenshot({ path: `${out}/share-created.png` })
  const html = await p.content(); const m = html.match(/https?:\/\/[^"'\s<>]*[?&]share=[^"'\s<>]+/); const val = m ? m[0] : (await p.locator('input[readonly], input[value*="share="]').first().inputValue().catch(() => ''))
  const link = (val || '').replace(/&amp;/g, '&')
  if (!link) { log('FAIL J7 no share link text found after creating'); return }
  const p2 = await (await b.newContext({ viewport: { width: 1280, height: 800 } })).newPage(); await p2.goto(link); await p2.waitForTimeout(7000)
  const t2 = await p2.locator('body').innerText(); await p2.screenshot({ path: `${out}/share-stranger.png` })
  log(`${t2.length > 300 && /sample|task|Operating|deadline/i.test(t2) ? 'PASS' : 'FAIL'} J7 shared link opens for a stranger:`, clean(t2).slice(0, 240))
})
await b.close()
