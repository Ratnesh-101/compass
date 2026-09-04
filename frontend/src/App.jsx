import React, { useState, useEffect } from 'react'
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

  useEffect(() => {
    checkBackendHealth().then(status => setBackendStatus(status))
    fetchTasks().then(data => setTasks(data))
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
    setMessages(prev => [...prev, { role: 'assistant', text: reply }])
    setIsTyping(false)
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

      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#0b0f17' }}>
        <header style={{ height: '64px', borderBottom: '1px solid #1e293b', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 28px' }}>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={() => setActiveTab('timeline')}
              style={{ padding: '8px 16px', borderRadius: '6px', border: 'none', background: activeTab === 'timeline' ? '#1e293b' : 'transparent', color: activeTab === 'timeline' ? '#fff' : '#64748b', cursor: 'pointer', fontWeight: '500' }}>
              Timeline Feed
            </button>
            <button
              onClick={() => setActiveTab('chat')}
              style={{ padding: '8px 16px', borderRadius: '6px', border: 'none', background: activeTab === 'chat' ? '#1e293b' : 'transparent', color: activeTab === 'chat' ? '#fff' : '#64748b', cursor: 'pointer', fontWeight: '500' }}>
              Assistant Chat
            </button>
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
            onSendMessage={handleSendMessage}
            isTyping={isTyping}
          />
        )}
      </main>
    </div>
  )
}
