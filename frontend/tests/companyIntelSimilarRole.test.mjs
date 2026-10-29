import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

test('Company Intel labels weakly matched role bullets as from a similar role listing', () => {
  const code = fs.readFileSync(path.resolve(__dirname, '../src/components/career/ApplicationWorkspaceModal.jsx'), 'utf8')
  assert.ok(code.includes('p.similar_role'))
  assert.ok(code.includes('from a similar role listing'))
})
