import React, { useState, useEffect, useRef } from 'react'

export default function ChatPanel({ messages, setMessages, onSendMessage, isTyping }) {
  const [input, setInput] = useState('')
  const [streamingText, setStreamingText] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const messagesEndRef = useRef(null)
  const streamTimerRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  // Auto-scroll whenever messages, streaming tokens, or typing status changes
  useEffect(() => {
    scrollToBottom()
  }, [messages, streamingText, isTyping])

  // Cleanup timer if component unmounts mid-stream
  useEffect(() => {
    return () => {
      if (streamTimerRef.current) {
        clearInterval(streamTimerRef.current)
      }
    }
  }, [])

  /**
   * Token Streaming & Typewriter Mechanism
   * Chunks 3–5 characters or 1 token every 18ms for realistic sub-400ms progressive delivery.
   */
  const streamAssistantResponse = (fullText) => {
    setIsStreaming(true)
    setStreamingText('')

    // Divide text into token-like chunks (3 to 6 characters or word chunks)
    const chunks = []
    let cursor = 0
    while (cursor < fullText.length) {
      const nextSpace = fullText.indexOf(' ', cursor)
      let take = 4
      if (nextSpace !== -1 && nextSpace - cursor <= 6) {
        take = nextSpace - cursor + 1
      }
      chunks.push(fullText.slice(cursor, cursor + take))
      cursor += take
    }

    let chunkIndex = 0
    let accumulated = ''

    if (streamTimerRef.current) {
      clearInterval(streamTimerRef.current)
    }

    streamTimerRef.current = setInterval(() => {
      if (chunkIndex < chunks.length) {
        accumulated += chunks[chunkIndex]
        setStreamingText(accumulated)
        chunkIndex++
        // Continuous auto-scroll keeping the generation centered
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
      } else {
        clearInterval(streamTimerRef.current)
        streamTimerRef.current = null
        setIsStreaming(false)
        setStreamingText('')
        setMessages(prev => [...prev, { role: 'assistant', text: fullText }])
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
      }
    }, 18)
  }

  const handleSend = async (textToSend) => {
    const text = (textToSend || input).trim()
    if (!text || isStreaming || isTyping) return
    setInput('')

    const reply = await onSendMessage(text)
    if (reply) {
      streamAssistantResponse(reply)
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    handleSend()
  }

  const handleQuickPrompt = () => {
    if (isStreaming || isTyping) return
    const prompt = 'What tasks do I have coming up?'
    setInput(prompt)
    handleSend(prompt)
  }

  /**
   * Preserves formatting, line breaks, bullet points, and router latency chips
   */
  const renderFormattedMessage = (text) => {
    if (!text) return null
    const lines = text.split('\n')

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
        {lines.map((line, i) => {
          const trimmed = line.trim()

          // 1. Router Latency Badge Chip (⚡ [Routed via Nemotron-3 Nano in 342ms])
          if (line.includes('Routed via Nemotron-3 Nano') || line.includes('⚡')) {
            return (
              <div key={i} className="router-chip">
                <span style={{ fontSize: '13px' }}>⚡</span>
                <span>{line.replace('⚡', '').trim()}</span>
              </div>
            )
          }

          // 2. Coursework Deliverables Heading
          if (line.includes('Coursework') && (line.includes('📚') || line.includes('CS 61C'))) {
            return (
              <div key={i} style={{ marginTop: '10px', marginBottom: '4px', color: '#60a5fa', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className="badge-coursework" style={{ padding: '2px 8px', borderRadius: '4px', fontSize: '11px', textTransform: 'uppercase' }}>
                  Coursework
                </span>
                <span>{line.replace(/^\d+\.\s*/, '').replace('📚', '').trim()}</span>
              </div>
            )
          }

          // 3. Hackathon Deliverables Heading
          if (line.includes('Hackathon') && (line.includes('🚀') || line.includes('Nebius'))) {
            return (
              <div key={i} style={{ marginTop: '10px', marginBottom: '4px', color: '#fbbf24', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className="badge-hackathon" style={{ padding: '2px 8px', borderRadius: '4px', fontSize: '11px', textTransform: 'uppercase' }}>
                  Hackathon
                </span>
                <span>{line.replace(/^\d+\.\s*/, '').replace('🚀', '').trim()}</span>
              </div>
            )
          }

          // 4. Actionable Next Step Callout
          if (line.includes('Next Step:')) {
            return (
              <div key={i} style={{ marginTop: '12px', padding: '10px 14px', borderRadius: '8px', background: '#090d14', border: '1px solid #1e293b', color: '#34d399', fontSize: '12.5px', fontFamily: 'JetBrains Mono, monospace', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ color: '#10b981' }}>❯</span>
                <span>{line}</span>
              </div>
            )
          }

          // 5. Bullet Points (• or -)
          if (trimmed.startsWith('•') || trimmed.startsWith('-')) {
            return (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', margin: '3px 0 3px 6px', color: '#e2e8f0', fontSize: '13px' }}>
                <span style={{ color: '#818cf8', fontWeight: '700', lineHeight: '1.4' }}>•</span>
                <span style={{ lineHeight: '1.4' }}>{trimmed.replace(/^[•\-]\s*/, '')}</span>
              </div>
            )
          }

          // 6. Empty Lines / Spacing
          if (!trimmed) {
            return <div key={i} style={{ height: '6px' }} />
          }

          // 7. Regular Text Paragraph
          return (
            <p key={i} style={{ margin: '2px 0', lineHeight: '1.5', color: '#f1f5f9' }}>
              {line}
            </p>
          )
        })}
      </div>
    )
  }

  const isInputDisabled = isStreaming || isTyping

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, padding: '20px', height: 'calc(100vh - 60px)', minWidth: 0 }}>
      {/* Message Feed Container */}
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '14px', marginBottom: '14px', paddingRight: '4px' }}>
        {messages.map((msg, idx) => (
          <div key={idx} style={{ display: 'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
            <div style={{
              maxWidth: '85%',
              padding: '12px 16px',
              borderRadius: '12px',
              background: msg.role === 'user' ? '#2563eb' : '#111827',
              color: '#fff',
              fontSize: '13.5px',
              lineHeight: '1.5',
              border: msg.role === 'user' ? 'none' : '1px solid #1f2937',
              boxShadow: msg.role === 'user' ? '0 2px 8px rgba(37,99,235,0.3)' : '0 2px 8px rgba(0,0,0,0.2)'
            }}>
              {msg.role === 'user' ? msg.text : renderFormattedMessage(msg.text)}
            </div>
          </div>
        ))}

        {/* Active Progressive Token Streaming Bubble */}
        {isStreaming && (
          <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
            <div style={{
              maxWidth: '85%',
              padding: '12px 16px',
              borderRadius: '12px',
              background: '#111827',
              color: '#fff',
              fontSize: '13.5px',
              lineHeight: '1.5',
              border: '1px solid #374151',
              boxShadow: '0 0 16px rgba(99, 102, 241, 0.2)'
            }}>
              {renderFormattedMessage(streamingText)}
              <span className="streaming-caret" />
            </div>
          </div>
        )}

        {/* Loading Indicator */}
        {isTyping && !isStreaming && (
          <div style={{ color: '#94a3b8', fontSize: '12px', fontStyle: 'italic', display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 12px' }}>
            <span style={{ display: 'inline-block', width: '7px', height: '7px', borderRadius: '50%', background: '#6366f1', boxShadow: '0 0 8px #6366f1' }} />
            Thinking...
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Demo Preset Trigger Pill */}
      <div style={{ marginBottom: '10px' }}>
        <button
          type="button"
          onClick={handleQuickPrompt}
          disabled={isInputDisabled}
          style={{
            width: '100%',
            textAlign: 'left',
            padding: '9px 14px',
            borderRadius: '8px',
            background: isInputDisabled ? 'rgba(30, 41, 59, 0.4)' : 'rgba(30, 41, 59, 0.7)',
            border: '1px solid rgba(59, 130, 246, 0.5)',
            color: isInputDisabled ? '#64748b' : '#93c5fd',
            fontSize: '12px',
            cursor: isInputDisabled ? 'not-allowed' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            transition: 'all 0.15s ease'
          }}>
          <span style={{ fontSize: '14px' }}>📋</span>
          <span>Quick prompt: <strong>"What tasks do I have coming up?"</strong></span>
        </button>
      </div>

      {/* Input Form Bar */}
      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '8px' }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={isStreaming ? 'Streaming response...' : 'Ask me anything, or say "add a task"...'}
          disabled={isInputDisabled}
          style={{
            flex: 1,
            padding: '12px 16px',
            borderRadius: '8px',
            background: isInputDisabled ? '#0d131f' : '#111827',
            border: '1px solid #374151',
            color: isInputDisabled ? '#64748b' : '#fff',
            fontSize: '13px',
            outline: 'none',
            cursor: isInputDisabled ? 'not-allowed' : 'text'
          }}
        />
        <button
          type="submit"
          disabled={isInputDisabled || !input.trim()}
          style={{
            padding: '0 22px',
            borderRadius: '8px',
            background: '#6366f1',
            border: 'none',
            color: '#fff',
            fontWeight: '600',
            fontSize: '13px',
            cursor: (isInputDisabled || !input.trim()) ? 'not-allowed' : 'pointer',
            opacity: (!input.trim() || isInputDisabled) ? 0.5 : 1,
            transition: 'opacity 0.15s ease'
          }}>
          Send
        </button>
      </form>
    </div>
  )
}
