import React, { useState, useEffect, useRef } from 'react'
import Sidebar from './components/Sidebar'
import Timeline from './components/Timeline'
import ChatPanel from './components/ChatPanel'
import { checkBackendHealth, fetchTasks, sendQueryToAssistant } from './api/client'

export default function App() {
  const [tasks, setTasks] = useState([])
  const [activeTab, setActiveTab] = useState('timeline')
  const [selectedDomain, setSelectedDomain] = useState('all')
  const [backendStatus, setBackendStatus] = useState('Connecting...')
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      text: 'Compass Cognitive Core initialized. Vector context and multi-domain memory are active.'
    }
  ])
  const [isTyping, setIsTyping] = useState(false)
  const previousTasksJsonRef = useRef('')

  useEffect(() => {
    let isMounted = true

    const poll = async () => {
      try {
        const status = await checkBackendHealth()
        if (isMounted) setBackendStatus(status)

        const data = await fetchTasks()
        if (isMounted && Array.isArray(data) && data.length > 0) {
          const serialized = JSON.stringify(data)
          // Quietly updates without causing layout shifts or scroll resets
          if (serialized !== previousTasksJsonRef.current) {
            previousTasksJsonRef.current = serialized
            setTasks(data)
          }
        }
      } catch {
        // Silently preserve current view during blips
      }
    }

    poll()
    // 2.5 second polling interval for smooth live demo sync
    const interval = setInterval(poll, 2500)

    return () => {
      isMounted = false
      clearInterval(interval)
    }
  }, [])

  const domainCounts = {
    hackathon: tasks.filter(t => t.domain === 'hackathon').length,
    coursework: tasks.filter(t => t.domain === 'coursework').length,
    code: tasks.filter(t => t.domain === 'code').length
  }

  const handleSendMessage = async (userText) => {
    setMessages(prev => [...prev, { role: 'user', text: userText }])
    setIsTyping(true)
    const reply = await sendQueryToAssistant(userText)
    setIsTyping(false)
    return reply
  }

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100vw', background: '#0b0f17', overflow: 'hidden' }}>
      <Sidebar
        activeDomain={selectedDomain}
        onSelectDomain={setSelectedDomain}
        domainCounts={domainCounts}
        backendStatus={backendStatus}
        activeTab={activeTab}
        onSelectTab={setActiveTab}
      />

      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#0b0f17', minWidth: 0, overflow: 'hidden' }}>
        <header style={{ height: '60px', borderBottom: '1px solid #1e293b', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 20px', flexShrink: 0 }}>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={() => setActiveTab('timeline')}
              style={{ padding: '7px 14px', borderRadius: '6px', border: 'none', background: activeTab === 'timeline' ? '#1e293b' : 'transparent', color: activeTab === 'timeline' ? '#fff' : '#64748b', cursor: 'pointer', fontWeight: '500', fontSize: '13px' }}>
              📅 Timeline Feed
            </button>
            <button
              onClick={() => setActiveTab('chat')}
              style={{ padding: '7px 14px', borderRadius: '6px', border: 'none', background: activeTab === 'chat' ? '#1e293b' : 'transparent', color: activeTab === 'chat' ? '#fff' : '#64748b', cursor: 'pointer', fontWeight: '500', fontSize: '13px' }}>
              💬 Assistant Chat
            </button>
          </div>
          <div style={{ fontSize: '11px', color: '#64748b', fontFamily: 'JetBrains Mono, monospace' }}>
            pgvector HNSW • 768-dim
          </div>
        </header>

        {activeTab === 'timeline' ? (
          <Timeline
            tasks={tasks}
            activeDomain={selectedDomain}
            onSelectDomain={setSelectedDomain}
          />
        ) : (
          <ChatPanel
            messages={messages}
            setMessages={setMessages}
            onSendMessage={handleSendMessage}
            isTyping={isTyping}
          />
        )}
      </main>
    </div>
  )
}
