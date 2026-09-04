import React, { useState, useEffect, useRef } from 'react'

export default function ChatPanel({ messages, setMessages, onSendMessage, isTyping }) {
  const [input, setInput] = useState('')
  const [streamingText, setStreamingText] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const messagesEndRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, streamingText, isTyping])

  const streamAssistantResponse = (fullText) => {
    setIsStreaming(true)
    setStreamingText('')
    
    // Stream token-by-token (words / token chunks) for realistic AI generation
    const tokens = fullText.split(/(\s+)/)
    let current = ''
    let idx = 0

    const interval = setInterval(() => {
      if (idx < tokens.length) {
        current += tokens[idx]
        setStreamingText(current)
        idx++
      } else {
        clearInterval(interval)
        setIsStreaming(false)
        setStreamingText('')
        setMessages(prev => [...prev, { role: 'assistant', text: fullText }])
      }
    }, 22)
  }

  const handleSend = async (textToSend) => {
    const text = textToSend || input
    if (!text.trim() || isStreaming) return
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
    const prompt = 'What are my top deliverables across coursework and hackathon before Friday?'
    setInput(prompt)
    handleSend(prompt)
  }

  const renderFormattedMessage = (text) => {
    const lines = text.split('\n')
    return (
      <div>
        {lines.map((line, i) => {
          if (line.includes('Routed via Nemotron-3 Nano')) {
            return (
              <div key={i} className="router-chip">
                <span>⚡</span>
                <strong>{line.replace('⚡', '').trim()}</strong>
              </div>
            )
          }
          if (line.includes('Coursework (CS 61C)')) {
            return (
              <div key={i} style={{ marginTop: '10px', marginBottom: '4px', color: '#60a5fa', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span className="badge-coursework" style={{ padding: '2px 8px', borderRadius: '4px', fontSize: '11px' }}>COURSEWORK</span>
                <span>{line}</span>
              </div>
            )
          }
          if (line.includes('Hackathon (Nebius Token Factory)')) {
            return (
              <div key={i} style={{ marginTop: '10px', marginBottom: '4px', color: '#fbbf24', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span className="badge-hackathon" style={{ padding: '2px 8px', borderRadius: '4px', fontSize: '11px' }}>HACKATHON</span>
                <span>{line}</span>
              </div>
            )
          }
          if (line.includes('Next Step:')) {
            return (
              <div key={i} style={{ marginTop: '12px', padding: '8px 12px', borderRadius: '6px', background: '#090d14', border: '1px solid #1e293b', color: '#34d399', fontSize: '13px', fontFamily: 'JetBrains Mono, monospace' }}>
                {line}
              </div>
            )
          }
          return <p key={i} style={{ margin: line.trim() ? '3px 0' : '6px 0' }}>{line}</p>
        })}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, padding: '20px', height: 'calc(100vh - 60px)', minWidth: 0 }}>
      {/* Message Feed */}
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '14px', marginBottom: '14px', paddingRight: '4px' }}>
        {messages.map((msg, idx) => (
          <div key={idx} style={{ display: 'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
            <div style={{
              maxWidth: '82%',
              padding: '12px 16px',
              borderRadius: '12px',
              background: msg.role === 'user' ? '#2563eb' : '#111827',
              color: '#fff',
              fontSize: '13.5px',
              lineHeight: '1.5',
              border: msg.role === 'user' ? 'none' : '1px solid #1f2937',
              boxShadow: '0 2px 8px rgba(0,0,0,0.2)'
            }}>
              {msg.role === 'user' ? msg.text : renderFormattedMessage(msg.text)}
            </div>
          </div>
        ))}

        {/* Live Token Streaming Bubble */}
        {isStreaming && (
          <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
            <div style={{
              maxWidth: '82%',
              padding: '12px 16px',
              borderRadius: '12px',
              background: '#111827',
              color: '#fff',
              fontSize: '13.5px',
              lineHeight: '1.5',
              border: '1px solid #374151',
              boxShadow: '0 0 12px rgba(99, 102, 241, 0.15)'
            }}>
              {renderFormattedMessage(streamingText)}
              <span className="streaming-caret" />
            </div>
          </div>
        )}

        {isTyping && !isStreaming && (
          <div style={{ color: '#94a3b8', fontSize: '12px', fontStyle: 'italic', display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 12px' }}>
            <span style={{ display: 'inline-block', width: '7px', height: '7px', borderRadius: '50%', background: '#6366f1', boxShadow: '0 0 8px #6366f1' }} />
            ⚡ Nemotron-3 Nano dispatching function calls & synthesizing context...
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Demo Script Preset Prompt Pill */}
      <div style={{ marginBottom: '10px' }}>
        <button
          onClick={handleQuickPrompt}
          disabled={isStreaming || isTyping}
          style={{
            width: '100%',
            textAlign: 'left',
            padding: '8px 12px',
            borderRadius: '8px',
            background: 'rgba(30, 41, 59, 0.7)',
            border: '1px solid #3b82f6',
            color: '#93c5fd',
            fontSize: '12px',
            cursor: (isStreaming || isTyping) ? 'not-allowed' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px'
          }}>
          💡 Click to test: <strong>"What are my top deliverables across coursework and hackathon before Friday?"</strong>
        </button>
      </div>

      {/* Input Bar */}
      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '8px' }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask Compass across your hackathons, coursework, or repos..."
          disabled={isStreaming || isTyping}
          style={{
            flex: 1,
            padding: '12px 16px',
            borderRadius: '8px',
            background: '#111827',
            border: '1px solid #374151',
            color: '#fff',
            fontSize: '13px',
            outline: 'none'
          }}
        />
        <button
          type="submit"
          disabled={isStreaming || isTyping || !input.trim()}
          style={{
            padding: '0 20px',
            borderRadius: '8px',
            background: '#6366f1',
            border: 'none',
            color: '#fff',
            fontWeight: '600',
            fontSize: '13px',
            cursor: (isStreaming || isTyping || !input.trim()) ? 'not-allowed' : 'pointer',
            opacity: (!input.trim() || isStreaming || isTyping) ? 0.6 : 1
          }}>
          Send
        </button>
      </form>
    </div>
  )
}
