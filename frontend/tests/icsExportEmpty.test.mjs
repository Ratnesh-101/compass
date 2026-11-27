import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const read = rel => fs.readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')

test('downloadAuthedFile accepts an options argument with minEvents', () => {
  const src = read('api/baseClient.js')
  const m = src.match(/export async function downloadAuthedFile\(([^)]*)\)/)
  assert.ok(m, 'downloadAuthedFile signature not found')
  const params = m[1].split(',').map(s => s.trim())
  assert.ok(params.length >= 3, `expected an options parameter, got: ${m[1]}`)
  assert.match(src, /minEvents/)
})

test('error text "Nothing to export yet" exists', () => {
  assert.match(read('api/baseClient.js'), /Nothing to export yet/)
})

test('CalendarView export handler passes { minEvents: 1 }', () => {
  const src = read('components/CalendarView.jsx')
  assert.match(src, /downloadAuthedFile\([^\n]*\{\s*minEvents:\s*1\s*\}\s*\)/)
})

test('IcsExportModal button passes { minEvents: 1 }', () => {
  const src = read('components/calendar/CalendarModals.jsx')
  assert.match(src, /downloadAuthedFile\([^\n]*\{\s*minEvents:\s*1\s*\}\s*\)/)
})

test('behaviour: zero-event feed rejects with "Nothing to export yet" when minEvents is 1', async () => {
  const { downloadAuthedFile } = await import('../src/api/baseClient.js')
  const realFetch = globalThis.fetch
  const empty = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n'
  globalThis.fetch = async () => ({
    ok: true,
    status: 200,
    headers: new Headers({ 'x-compass-event-count': '0', 'content-type': 'text/calendar' }),
    blob: async () => new Blob([empty]),
    text: async () => empty,
  })
  try {
    await assert.rejects(
      () => downloadAuthedFile('/api/calendar/export.ics', 'x.ics', { minEvents: 1 }),
      /Nothing to export yet/,
    )
  } finally {
    globalThis.fetch = realFetch
  }
})
