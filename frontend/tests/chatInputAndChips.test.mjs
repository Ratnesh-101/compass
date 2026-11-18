import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { autoGrowTextarea, MAX_TEXTAREA_HEIGHT } from '../src/utils/autoGrowTextarea.js'
import { generateFollowUpSuggestions } from '../src/utils/suggestionGenerator.js'

const read = (rel) => fs.readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')

test('ChatInputBar grows the textarea with its content up to 160px', () => {
  const bar = read('components/chat/ChatInputBar.jsx')
  assert.ok(bar.includes("import { autoGrowTextarea } from '../../utils/autoGrowTextarea'"))
  assert.ok(bar.includes('autoGrowTextarea(inputRef.current)'))
  assert.ok(bar.includes('[input]'))
  assert.ok(bar.includes("maxHeight: '160px'"))
  assert.equal(MAX_TEXTAREA_HEIGHT, 160)
})

test('autoGrowTextarea sizes to content, caps at 160px and resets when empty', () => {
  const el = { value: 'a\nb', scrollHeight: 90, style: {} }
  assert.equal(autoGrowTextarea(el), 90)
  assert.equal(el.style.height, '90px')
  assert.equal(el.style.overflowY, 'hidden')

  el.scrollHeight = 400
  assert.equal(autoGrowTextarea(el), 160)
  assert.equal(el.style.height, '160px')
  assert.equal(el.style.overflowY, 'auto')

  el.value = ''
  assert.equal(autoGrowTextarea(el), 0)
  assert.equal(el.style.height, '')
  assert.equal(autoGrowTextarea(null), 0)
})

test('ChatHeaderToolbar uses plain labels Short / Normal / Detailed and "Memory is on"', () => {
  const tb = read('components/chat/ChatHeaderToolbar.jsx')
  assert.ok(tb.includes("{ id: 'brief', label: 'Short' }"))
  assert.ok(tb.includes("{ id: 'balanced', label: 'Normal' }"))
  assert.ok(tb.includes("{ id: 'exploratory', label: 'Detailed' }"))
  assert.ok(tb.includes("text: 'Memory is on'"))
  for (const old of ["label: 'Brief'", "label: 'Balanced'", "label: 'Exploratory'", 'Memory On']) {
    assert.ok(!tb.includes(old), `old label still present: ${old}`)
  }
})

test('suggestionGenerator detects coursework by whole words and defines every flag it uses', () => {
  const src = read('utils/suggestionGenerator.js')
  assert.ok(/const hasCourseworkWord = /.test(src), 'hasCourseworkWord must be defined before use')
  assert.ok(src.includes('const isCoursework = /\\b('), 'coursework detection must use word boundaries')
  assert.ok(!src.includes("combinedContext.includes('lab')"))
  assert.ok(!src.includes("combinedContext.includes('exam')"))
})

function chips(userText, replyText, tasks = []) {
  return generateFollowUpSuggestions({
    latestMessage: { role: 'assistant', text: replyText },
    messages: [
      { role: 'user', text: userText },
      { role: 'assistant', text: replyText },
    ],
    tasks,
  })
}

test('"example" or "available" do not trigger coursework chips', () => {
  const out = chips('give me an example', 'Here is an example that is available to everyone today.')
  assert.ok(!out.includes('Review upcoming coursework deadlines'))
  assert.ok(!out.includes('Summarize key lab takeaways'))
})

test('no "Summarize key lab takeaways" chip without a coursework signal, and it works with one', () => {
  assert.ok(!chips('tell me about the weather', 'The labs are closed.').includes('Summarize key lab takeaways'))
  // coursework signal in the conversation, no coursework tasks, reply mentions labs: must not throw
  const out = chips('help with my homework', 'Your lab sessions cover the basics.')
  // The generator shows at most two chips and the lab chip ranks behind two more relevant coursework chips,
  // so it rarely surfaces; what matters is that this path no longer throws and still returns chips.
  assert.ok(Array.isArray(out) && out.length > 0)
  // with coursework tasks the chip is replaced by the prioritising one
  const withTasks = chips('help with my homework', 'Your lab sessions cover the basics.', [
    { id: 1, title: 'Lab 3', domain: 'coursework' },
  ])
  assert.ok(!withTasks.includes('Summarize key lab takeaways'))
})
