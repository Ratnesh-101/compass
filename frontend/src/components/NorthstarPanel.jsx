import React, { useState, useEffect } from 'react'
import ChatPanel from './ChatPanel'
import AgentPanel from './AgentPanel'
import SpecialistPanel from './SpecialistPanel'

export default function NorthstarPanel({
  initialSubTab = 'assistant',
  messages,
  setMessages,
  conversationId,
  setConversationId,
  onSendMessage,
  isTyping,
  onChatComplete,
  onTaskMutated,
  tasks = [],
  backendStatus = 'Live • Neon Connected',
  onSelectTab,
  pendingPrompt,
  onClearPendingPrompt,
}) {
  const [activeSubTab, setActiveSubTab] = useState(initialSubTab)

  useEffect(() => {
    if (initialSubTab) {
      setActiveSubTab(initialSubTab)
    }
  }, [initialSubTab])

  useEffect(() => {
    if (pendingPrompt) {
      setActiveSubTab('assistant')
    }
  }, [pendingPrompt])

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100vh', minWidth: 0, overflow: 'hidden', background: 'var(--bg-app)' }}>
      {/* Northstar Header Sub-bar */}
      <div style={{
        height: '52px',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-card)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 20px',
        flexShrink: 0,
        gap: '12px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
          <span style={{ fontSize: '18px' }}>🧭</span>
          <span style={{ fontSize: '14px', fontWeight: '800', color: 'var(--text-primary)', letterSpacing: '-0.2px' }}>
            Northstar AI
          </span>
          <span style={{
            fontSize: '11px',
            color: 'var(--text-muted)',
            background: 'var(--bg-card-soft)',
            border: '1px solid var(--border)',
            padding: '2px 8px',
            borderRadius: '10px',
            whiteSpace: 'nowrap'
          }}>
            All-in-One Copilot & Autonomous Agents
          </span>
        </div>

        {/* View Toggle */}
        <div style={{ display: 'flex', background: 'var(--bg-card-soft)', padding: '3px', borderRadius: '8px', border: '1px solid var(--border)', flexShrink: 0 }}>
          <button
            id="northstar-subtab-chat"
            onClick={() => setActiveSubTab('assistant')}
            style={{
              padding: '5px 14px',
              borderRadius: '6px',
              border: 'none',
              background: activeSubTab === 'assistant' ? 'var(--bg-card)' : 'transparent',
              color: activeSubTab === 'assistant' ? 'var(--text-primary)' : 'var(--text-secondary)',
              boxShadow: activeSubTab === 'assistant' ? 'var(--shadow-sm)' : 'none',
              fontSize: '12.5px',
              fontWeight: activeSubTab === 'assistant' ? '700' : '500',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}>
            💬 Chat Copilot
          </button>
          <button
            id="northstar-subtab-planner"
            onClick={() => setActiveSubTab('planner')}
            style={{
              padding: '5px 14px',
              borderRadius: '6px',
              border: 'none',
              background: activeSubTab === 'planner' ? 'var(--bg-card)' : 'transparent',
              color: activeSubTab === 'planner' ? 'var(--text-primary)' : 'var(--text-secondary)',
              boxShadow: activeSubTab === 'planner' ? 'var(--shadow-sm)' : 'none',
              fontSize: '12.5px',
              fontWeight: activeSubTab === 'planner' ? '700' : '500',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}>
            📋 Goal Planner
          </button>
          <button
            id="northstar-subtab-specialist"
            onClick={() => setActiveSubTab('specialist')}
            style={{
              padding: '5px 14px',
              borderRadius: '6px',
              border: 'none',
              background: activeSubTab === 'specialist' ? 'var(--bg-card)' : 'transparent',
              color: activeSubTab === 'specialist' ? 'var(--text-primary)' : 'var(--text-secondary)',
              boxShadow: activeSubTab === 'specialist' ? 'var(--shadow-sm)' : 'none',
              fontSize: '12.5px',
              fontWeight: activeSubTab === 'specialist' ? '700' : '500',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}>
            🧠 Specialist Agents
          </button>
        </div>
      </div>

      {/* Main Unified View Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden' }}>
        {activeSubTab === 'assistant' ? (
          <ChatPanel
            messages={messages}
            setMessages={setMessages}
            conversationId={conversationId}
            setConversationId={setConversationId}
            onSendMessage={onSendMessage}
            isTyping={isTyping}
            onChatComplete={onChatComplete}
            tasks={tasks}
            backendStatus={backendStatus}
            initialPrompt={pendingPrompt}
            onClearInitialPrompt={onClearPendingPrompt}
          />
        ) : activeSubTab === 'planner' ? (
          <AgentPanel
            onTaskMutated={onTaskMutated}
            conversationId={conversationId}
          />
        ) : (
          <SpecialistPanel
            onTaskMutated={onTaskMutated}
            onSelectTab={onSelectTab}
          />
        )}
      </div>
    </div>
  )
}
