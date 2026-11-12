import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseSlashCommand } from '../src/api/specialistRegistry.js'

const here = dirname(fileURLToPath(import.meta.url))
const chatPanel = readFileSync(join(here, '..', 'src', 'components', 'ChatPanel.jsx'), 'utf8')
const inputBar = readFileSync(join(here, '..', 'src', 'components', 'chat', 'ChatInputBar.jsx'), 'utf8')

test('a fully typed /research message resolves to the research specialist and the bare question', () => {
  const parsed = parseSlashCommand('/research Compare X and Y')
  assert.ok(parsed)
  assert.equal(parsed.specialist.id, 'research')
  assert.equal(parsed.text, 'Compare X and Y')
})

test('every registered command word parses, including /auto', () => {
  assert.equal(parseSlashCommand('/auto what is due').specialist.id, 'auto-dispatcher')
  assert.equal(parseSlashCommand('/coursework lab 3').specialist.id, 'coursework')
  assert.equal(parseSlashCommand('/calendar free slots').specialist.id, 'calendar')
  assert.equal(parseSlashCommand('/memory pgvector').specialist.id, 'memory')
})

test('multi-line questions keep their full text', () => {
  const parsed = parseSlashCommand('/research line one\nline two')
  assert.equal(parsed.text, 'line one\nline two')
})

test('unknown commands, bare commands and plain text are not treated as slash commands', () => {
  assert.equal(parseSlashCommand('/nope do it'), null)
  assert.equal(parseSlashCommand('/research'), null)
  assert.equal(parseSlashCommand('/research   '), null)
  assert.equal(parseSlashCommand('compare /research things'), null)
  assert.equal(parseSlashCommand(''), null)
  assert.equal(parseSlashCommand(null), null)
})

test('handleSend applies a typed slash command before choosing the specialist id', () => {
  const start = chatPanel.indexOf('const handleSend = async')
  assert.notEqual(start, -1)
  const body = chatPanel.slice(start, start + 4000)
  const parse = body.indexOf('parseSlashCommand(text)')
  const pick = body.indexOf('const specialistIdToUse')
  const stream = body.indexOf('streamQueryFromAssistant(text')
  assert.ok(parse !== -1 && pick !== -1 && stream !== -1)
  assert.ok(parse < pick && pick < stream)
})

test('the slash picker closes once a space follows the command word', () => {
  assert.match(inputBar, /val\.match\(\/\^\\\/\(\[a-zA-Z0-9_-\]\*\)\$\/\)/)
})
