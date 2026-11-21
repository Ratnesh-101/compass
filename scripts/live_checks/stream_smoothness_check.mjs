import { createRequire } from 'node:module'
// Live check against the deployed Compass site. Needs Node 18+ and playwright-core (set PLAYWRIGHT_CORE to its path
// if it is not resolvable). See scripts/live_checks/README.md. Writes screenshots to the current directory.
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core')
const url = process.argv[2], label = process.argv[3]
const b = await chromium.launch({ headless: true })
const p = await (await b.newContext({ viewport: { width: 1280, height: 720 } })).newPage()
await p.goto(url); await p.waitForTimeout(3500)
await p.locator('aside, nav').getByText('Assistant & planner', { exact: true }).first().click(); await p.waitForTimeout(1000)
await p.evaluate(() => { window.__s = []; const t0 = performance.now(); const f = () => { const m = document.querySelectorAll('.chat-msg-bubble'); const last = m[m.length - 1]; window.__s.push([Math.round(performance.now() - t0), last ? last.innerText.length : 0]); window.__raf = requestAnimationFrame(f) }; f() })
await p.locator('textarea').first().fill('Explain how a hash map works in three short paragraphs.')
await p.keyboard.press('Enter')
let last = -1, same = 0
for (let i = 0; i < 70; i++) { await p.waitForTimeout(1000); const n = await p.evaluate(() => { const s = window.__s; return s[s.length - 1][1] }); if (n > 120 && n === last) { if (++same >= 5) break } else same = 0; last = n }
const s = await p.evaluate(() => { cancelAnimationFrame(window.__raf); return window.__s })
let prev = 0, steps = [], grew = 0, firstGrow = null, lastGrow = null
for (const [t, len] of s) { if (len > prev && prev > 20) { steps.push(len - prev); grew++; firstGrow ??= t; lastGrow = t } prev = len }
steps.sort((a, c) => a - c)
console.log(label, '| final chars:', prev, '| growing frames:', grew, '| median step:', steps[Math.floor(steps.length / 2)] ?? 0, '| max step:', steps[steps.length - 1] ?? 0, '| growth span ms:', lastGrow - firstGrow)
await p.screenshot({ path: `anim2-${label}.png` }); await b.close()
