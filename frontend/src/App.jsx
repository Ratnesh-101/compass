import React, { useState, useEffect } from 'react'
import Sidebar from './components/Sidebar.jsx'
import Timeline from './components/Timeline.jsx'
import ChatPanel from './components/ChatPanel.jsx'
import { fetchHealth, fetchTasks, sendChatMessage, INITIAL_MOCK_TASKS } from './api/client.js'

export default function App() {
  const [tasks, setTasks] = useState(INITIAL_MOCK_TASKS)
  const [selectedDomain, setSelectedDomain] = useState('all')
  const [activeTab, setActiveTab] = useState('timeline') // 'timeline' | 'chat'
  const [backendStatus, setBackendStatus] = useState('Checking...')
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      text: 'Compass Cognitive Core ready. Ask anything across your hackathons, coursework, or repos.'
    }
  ])
  const [isTyping, setIsTyping] = useState(false)

  // Poll system health and fetch initial tasks
  useEffect(() => {
    fetchHealth().then(status => {
      setBackendStatus(status.statusText)
    })
    fetchTasks().then(loadedTasks => {
      if (loadedTasks && loadedTasks.length > 0) {
        setTasks(loadedTasks)
      }
    })
  }, [])

  // Domain counter aggregations
  const domainCounts = {
    hackathon: tasks.filter(t => t.domain === 'hackathon').length,
    coursework: tasks.filter(t => t.domain === 'coursework').length,
    code: tasks.filter(t => t.domain === 'code').length
  }

  const handleDomainSelect = (domain) => {
    setSelectedDomain(domain)
    setActiveTab('timeline')
  }

  const handleSendMessage = async (userPrompt) => {
    setMessages(prev => [...prev, { role: 'user', text: userPrompt }])
    setIsTyping(true)

    const response = await sendChatMessage(userPrompt)
    setMessages(prev => [...prev, { role: 'assistant', text: response.text }])
    setIsTyping(false)

    // Refresh tasks in case new task was added via chat
    fetchTasks().then(loadedTasks => {
      if (loadedTasks && loadedTasks.length > 0) {
        setTasks(loadedTasks)
      }
    })
  }

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100vw', background: '#0b0f17', overflow: 'hidden' }}>
      {/* 1. Sidebar */}
      <Sidebar
        activeDomain={selectedDomain}
        onSelectDomain={handleDomainSelect}
        domainCounts={domainCounts}
        backendStatus={backendStatus}
      />

      {/* 2. Main Content View */}
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#0b0f17', minWidth: 0 }}>
        {/* Top Header Navigation Tabs */}
        <header style={{
          height: '64px',
          borderBottom: '1px solid #1e293b',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 28px'
        }}>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={() => setActiveTab('timeline')}
              style={{
                padding: '8px 16px',
                borderRadius: '6px',
                border: 'none',
                background: activeTab === 'timeline' ? '#1e293b' : 'transparent',
                color: activeTab === 'timeline' ? '#fff' : '#64748b',
                cursor: 'pointer',
                fontWeight: '500',
                transition: 'all 0.15s'
              }}>
              Timeline View
            </button>
            <button
              onClick={() => setActiveTab('chat')}
              style={{
                padding: '8px 16px',
                borderRadius: '6px',
                border: 'none',
                background: activeTab === 'chat' ? '#1e293b' : 'transparent',
                color: activeTab === 'chat' ? '#fff' : '#64748b',
                cursor: 'pointer',
                fontWeight: '500',
                transition: 'all 0.15s'
              }}>
              AI Assistant Chat
            </button>
          </div>

          <div>
            <span style={{ fontSize: '12px', color: '#64748b' }}>
              Mode: <strong style={{ color: '#94a3b8' }}>Nebius Token Factory + Neon DB</strong>
            </span>
          </div>
        </header>

        {/* Tab Content Display */}
        {activeTab === 'timeline' ? (
          <Timeline
            tasks={tasks}
            activeDomain={selectedDomain}
            onSelectDomain={setSelectedDomain}
          />
        ) : (
          <ChatPanel
            messages={messages}
            onSendMessage={handleSendMessage}
            isTyping={isTyping}
          />
        )}
      </main>
    </div>
  )
}
