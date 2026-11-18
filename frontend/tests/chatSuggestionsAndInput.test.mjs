import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { generateFollowUpSuggestions } from '../src/utils/suggestionGenerator.js'
import {
  STARTER_QUESTIONS,
  filterDuplicateTaskList,
} from '../src/components/chat/chatGreetings.js'

test('N-021: Generic follow-up chips are NOT shown for internship queries', () => {
  const suggestions = generateFollowUpSuggestions({
    latestMessage: {
      role: 'assistant',
      text: 'No verified opportunities currently matching your search query in the database. You can check the Career page.',
    },
    messages: [
      { role: 'user', text: 'hi, can you help me find a summer internship? i am a 3rd year computer science student in pune' },
      {
        role: 'assistant',
        text: 'No verified opportunities currently matching your search query in the database. You can check the Career page.',
      },
    ],
    tasks: [],
  })

  // Must NOT include the generic technical chips flagged in N-021
  assert.strictEqual(suggestions.includes('Why did we choose this approach?'), false)
  assert.strictEqual(suggestions.includes('What are the tradeoffs?'), false)
  assert.strictEqual(suggestions.includes('How can we optimize performance?'), false)
  assert.strictEqual(suggestions.includes('Summarize key lab takeaways'), false)

  // Should include career-focused follow-ups
  assert.ok(suggestions.includes('Find matching internships'))
})

test('N-021: When unsure, suggestion generator shows NO chips (returns empty array)', () => {
  const suggestions = generateFollowUpSuggestions({
    latestMessage: {
      role: 'assistant',
      text: 'The weather today is cloudy with a light breeze.',
    },
    messages: [
      { role: 'user', text: 'How is the weather outside?' },
      { role: 'assistant', text: 'The weather today is cloudy with a light breeze.' },
    ],
    tasks: [],
  })

  assert.deepStrictEqual(suggestions, [], 'Unsure contexts must return an empty array instead of random fallback chips')
})

test('N-023: Starter questions include the 4 requested examples', () => {
  assert.ok(Array.isArray(STARTER_QUESTIONS))
  assert.strictEqual(STARTER_QUESTIONS.length, 4)
  assert.ok(STARTER_QUESTIONS.includes('Find internships for me'))
  assert.ok(STARTER_QUESTIONS.includes('Plan my week'))
  assert.ok(STARTER_QUESTIONS.includes('Add a reminder'))
  assert.ok(STARTER_QUESTIONS.includes('Help me with my deadlines'))
})

test('N-025: filterDuplicateTaskList removes duplicate task list lines from assistant message', () => {
  const rawMsgText = [
    'I found 3 tasks to add:',
    '1. arrays - tomorrow',
    '2. linked lists - thursday',
    '3. trees - friday',
    'Nothing is saved until you confirm.',
    "Reply 'Confirm' to proceed.",
  ].join('\n')

  const items = [
    { title: 'arrays', due_label: 'tomorrow' },
    { title: 'linked lists', due_label: 'thursday' },
    { title: 'trees', due_label: 'friday' },
  ]

  const filtered = filterDuplicateTaskList(rawMsgText, items)
  assert.strictEqual(filtered, 'I found 3 tasks to add:')
  assert.ok(!filtered.includes('arrays'))
  assert.ok(!filtered.includes('linked lists'))
  assert.ok(!filtered.includes('Nothing is saved until you confirm'))
})

test('N-023 / T-028: ChatInputBar component contract for textarea and accessible label', () => {
  const source = fs.readFileSync(
    new URL('../src/components/chat/ChatInputBar.jsx', import.meta.url),
    'utf8'
  )
  assert.ok(source.includes('<textarea'), 'Must render a <textarea> element')
  assert.ok(source.includes('aria-label="Message Compass"'), 'Must have accessible label for chat input')
  assert.ok(source.includes("e.key === 'Enter' && !e.shiftKey"), 'Enter sends and Shift+Enter inserts newline')
  assert.ok(!source.includes('Specialist Agent...'), 'Must remove Specialist Agent jargon from placeholder')
})

test('N-025: IntakePreviewCard component contract for primary Confirm and secondary Cancel', () => {
  const source = fs.readFileSync(
    new URL('../src/components/chat/IntakePreviewCard.jsx', import.meta.url),
    'utf8'
  )
  assert.ok(source.includes('btn-intake-confirm'), 'Must have confirm button id')
  assert.ok(source.includes('btn-intake-cancel'), 'Must have cancel button id')
  assert.ok(source.includes('minHeight: \'38px\''), 'Confirm button must be primary and larger')
})

test('T-012: AgentPanel component contract for terminal event check and resumeRun', () => {
  const source = fs.readFileSync(
    new URL('../src/components/AgentPanel.jsx', import.meta.url),
    'utf8'
  )
  assert.ok(source.includes('sawTerminal'), 'Must track terminal events')
  assert.ok(source.includes('resumeRun'), 'Must implement resumeRun')
  assert.ok(source.includes('/api/agent/runs/'), 'Must call agent runs endpoint on resume')
  assert.ok(source.includes('buffer.trim()'), 'Must process residual buffer on stream close')
})

test('N-022: ChatPanel component contract for automatic reopen of most recent conversation', () => {
  const source = fs.readFileSync(
    new URL('../src/components/ChatPanel.jsx', import.meta.url),
    'utf8'
  )
  assert.ok(source.includes('autoReopenedRef'), 'Must track auto-reopen state')
  assert.ok(source.includes('handleSelectPastChat(sorted[0].id)'), 'Must reopen sorted[0].id on initial mount')
})
