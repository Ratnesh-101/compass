import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  streamQueryFromAssistant,
  fetchConversationMessages,
} from '../src/api/chatApi.js'
import {
  failureMessage,
  PLAIN_NETWORK_ERROR_MESSAGE,
} from '../src/utils/chatRequest.js'

/**
 * Creates a mock ReadableStream that yields chunks as UTF-8 SSE lines.
 */
function createMockSseStream(chunks) {
  const encoder = new TextEncoder()
  let index = 0
  return new ReadableStream({
    pull(controller) {
      if (index < chunks.length) {
        controller.enqueue(encoder.encode(chunks[index]))
        index++
      } else {
        controller.close()
      }
    },
  })
}

test('T-005: Stream ending without done event throws error with partialResponse preserved', async () => {
  const originalFetch = globalThis.fetch
  try {
    // Simulate stream that returns a token event and closes without a done event
    globalThis.fetch = async () => ({
      ok: true,
      body: createMockSseStream([
        'data: {"type": "status", "stage": "generating", "label": "Writing answer…"}\n\n',
        'data: {"type": "token", "value": "Here is the first part of the algorithm: Bubble Sort works by "}\n\n',
      ]),
    })

    let caughtError = null
    let receivedTokens = ''
    try {
      await streamQueryFromAssistant('Tell me about sorting algorithms', 'conv-123', {
        onToken: (_chunk, full) => {
          receivedTokens = full
        },
      })
    } catch (err) {
      caughtError = err
    }

    assert.ok(caughtError, 'Must throw an error when stream closes without a done event')
    assert.strictEqual(
      caughtError.partialResponse,
      'Here is the first part of the algorithm: Bubble Sort works by ',
      'partialResponse on thrown error must match accumulated tokens'
    )
    assert.match(
      caughtError.message,
      /Stream ended abruptly|Connection closed/i,
      'Error message should indicate stream interruption'
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('T-005: Stream with token event followed by done event completes successfully', async () => {
  const originalFetch = globalThis.fetch
  try {
    globalThis.fetch = async () => ({
      ok: true,
      body: createMockSseStream([
        'data: {"type": "token", "value": "Complete answer."}\n\n',
        'data: {"type": "done", "conversation_id": "conv-123", "is_truncated": false}\n\n',
      ]),
    })

    let completedResult = null
    const res = await streamQueryFromAssistant('Hello', 'conv-123', {
      onComplete: (data) => {
        completedResult = data
      },
    })

    assert.ok(res, 'Stream must resolve with streamResult')
    assert.strictEqual(res.response, 'Complete answer.')
    assert.strictEqual(completedResult?.conversation_id, 'conv-123')
    assert.strictEqual(completedResult?.is_truncated, false)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('T-004: streamQueryFromAssistant passes continue_message_id in request payload', async () => {
  const originalFetch = globalThis.fetch
  let capturedBody = null
  try {
    globalThis.fetch = async (_url, options) => {
      capturedBody = JSON.parse(options.body)
      return {
        ok: true,
        body: createMockSseStream([
          'data: {"type": "token", "value": "continued text"}\n\n',
          'data: {"type": "done", "conversation_id": "conv-123", "is_truncated": false}\n\n',
        ]),
      }
    }

    await streamQueryFromAssistant('Continue response', 'conv-123', {
      continueMessageId: 'msg-truncated-456',
    })

    assert.ok(capturedBody, 'Fetch body must be captured')
    assert.strictEqual(
      capturedBody.continue_message_id,
      'msg-truncated-456',
      'Body must contain continue_message_id set to the truncated message id'
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('T-011: fetchConversationMessages maps is_truncated flag from API', async () => {
  const originalFetch = globalThis.fetch
  try {
    globalThis.fetch = async () => ({
      ok: true,
      json: async () => ({
        messages: [
          {
            id: 'msg-1',
            role: 'assistant',
            content: 'Full answer',
            is_truncated: false,
          },
          {
            id: 'msg-2',
            role: 'assistant',
            content: 'Truncated answer...',
            is_truncated: true,
          },
        ],
      }),
    })

    const messages = await fetchConversationMessages('conv-abc')
    assert.strictEqual(messages.length, 2)
    assert.strictEqual(messages[0].isTruncated, false)
    assert.strictEqual(messages[0].is_truncated, false)
    assert.strictEqual(messages[1].isTruncated, true)
    assert.strictEqual(messages[1].is_truncated, true)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('N-011: Status text "Continuing response (1/1)" is replaced with "Finishing the answer…"', async () => {
  const originalFetch = globalThis.fetch
  try {
    let observedLabel = null
    globalThis.fetch = async () => ({
      ok: true,
      body: createMockSseStream([
        'data: {"type": "status", "stage": "generating", "label": "Continuing response (1/1)…"}\n\n',
        'data: {"type": "token", "value": "Final words."}\n\n',
        'data: {"type": "done", "conversation_id": "conv-123"}\n\n',
      ]),
    })

    await streamQueryFromAssistant('test', 'conv-123', {
      onStatus: (evt) => {
        observedLabel = evt.label
      },
    })

    assert.strictEqual(observedLabel, 'Finishing the answer…')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('N-011: failureMessage transforms bare network error into plain language notice', () => {
  const msg1 = failureMessage({
    err: new Error('network error'),
    partialText: 'Half answer',
    prompt: 'Tell me more',
    requestId: 'req-1',
  })
  assert.strictEqual(msg1.error, PLAIN_NETWORK_ERROR_MESSAGE)
  assert.strictEqual(msg1.canRetry, true)
  assert.strictEqual(msg1.text, 'Half answer')

  const msg2 = failureMessage({
    err: new Error('TypeError: Failed to fetch'),
    partialText: '',
    prompt: 'Hello',
    requestId: 'req-2',
  })
  assert.strictEqual(msg2.error, PLAIN_NETWORK_ERROR_MESSAGE)
  assert.strictEqual(msg2.canRetry, true)
})
