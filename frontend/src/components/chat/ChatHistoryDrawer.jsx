import React, { useState, useEffect } from 'react'
import { updateConversation, deleteConversation } from '../../api/client'
import ChatConversationItem from './ChatConversationItem'

export default function ChatHistoryDrawer({
  isOpen,
  onClose,
  pastConversations,
  setPastConversations,
  pastPlans,
  conversationId,
  guestMigrationCount,
  onOpenMigration,
  onSelectPastChat,
  onNewChat,
  onSelectPastPlan,
  onCheckScheduleClashes,
  showToast,
  tasks = [],
}) {
  const [historyTab, setHistoryTab] = useState('chats') // 'chats' | 'plans' | 'memory'
  const [openMenuConvId, setOpenMenuConvId] = useState(null)
  const [editingConvId, setEditingConvId] = useState(null)
  const [editingTitle, setEditingTitle] = useState('')
  const [confirmDeleteConv, setConfirmDeleteConv] = useState(null)
  const [showArchived, setShowArchived] = useState(false)

  // Close context menu on outside click
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (!e.target.closest('.chat-item-menu-container') && !e.target.closest('.chat-item-menu-btn')) {
        setOpenMenuConvId(null)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  if (!isOpen) return null

  const handleStartRename = (conv) => {
    setOpenMenuConvId(null)
    setEditingConvId(conv.id)
    setEditingTitle(conv.title || '')
  }

  const handleSaveRename = async (convId) => {
    const clean = editingTitle.trim()
    if (!clean) {
      setEditingConvId(null)
      return
    }
    setPastConversations(prev => prev.map(c => c.id === convId ? { ...c, title: clean } : c))
    setEditingConvId(null)
    await updateConversation(convId, { title: clean })
    showToast('Chat renamed ✏️')
  }

  const handleCancelRename = () => {
    setEditingConvId(null)
  }

  const handleTogglePin = async (conv) => {
    setOpenMenuConvId(null)
    const nextPinned = !conv.is_pinned
    setPastConversations(prev => {
      const updated = prev.map(c => c.id === conv.id ? { ...c, is_pinned: nextPinned } : c)
      return [...updated].sort((a, b) => {
        if (Boolean(a.is_pinned) !== Boolean(b.is_pinned)) return a.is_pinned ? -1 : 1
        return new Date(b.last_active_at) - new Date(a.last_active_at)
      })
    })
    await updateConversation(conv.id, { is_pinned: nextPinned })
    showToast(nextPinned ? 'Chat pinned to top 📌' : 'Chat unpinned')
  }

  const handleToggleArchive = async (conv) => {
    setOpenMenuConvId(null)
    const nextArchived = !conv.is_archived
    setPastConversations(prev => prev.map(c => c.id === conv.id ? { ...c, is_archived: nextArchived } : c))
    await updateConversation(conv.id, { is_archived: nextArchived })
    showToast(nextArchived ? 'Chat moved to Archive 🗃️' : 'Chat unarchived')
  }

  const handleOpenDeleteConfirm = (conv) => {
    setOpenMenuConvId(null)
    setConfirmDeleteConv(conv)
  }

  const handleExecuteDelete = async () => {
    if (!confirmDeleteConv) return
    const convId = confirmDeleteConv.id
    setConfirmDeleteConv(null)
    const ok = await deleteConversation(convId)
    if (ok) {
      setPastConversations(prev => prev.filter(c => c.id !== convId))
      if (conversationId === convId) {
        onNewChat()
      }
      showToast('Chat deleted 🗑️')
    } else {
      showToast('Failed to delete chat')
    }
  }

  const visibleConversations = pastConversations.filter(c => showArchived ? Boolean(c.is_archived) : !c.is_archived)
  const archivedCount = pastConversations.filter(c => c.is_archived).length

  return (
    <>
      <aside style={{
        width: '320px',
        minWidth: '280px',
        maxWidth: '360px',
        background: 'var(--bg-card)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
        boxShadow: 'var(--shadow-md)',
        zIndex: 10,
      }}>
        {/* Drawer Header */}
        <div style={{
          padding: '14px 16px',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--bg-card-soft)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '16px' }}>📜</span>
            <span style={{ fontSize: '13px', fontWeight: '800', color: 'var(--text-primary)' }}>
              History & Memory
            </span>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none', border: 'none', color: 'var(--text-muted)',
              fontSize: '16px', cursor: 'pointer', padding: '2px 6px'
            }}
            title="Close drawer"
          >
            ✕
          </button>
        </div>

        {/* New Chat Primary Action */}
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
          <button
            onClick={onNewChat}
            style={{
              width: '100%',
              padding: '9px 14px',
              borderRadius: '8px',
              background: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
              color: '#ffffff',
              border: 'none',
              fontSize: '12.5px',
              fontWeight: '700',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '6px',
              boxShadow: '0 3px 10px rgba(37, 99, 235, 0.3)'
            }}
          >
            <span>+</span> Start New Chat
          </button>
        </div>

        {guestMigrationCount > 0 && onOpenMigration && (
          <div style={{
            margin: '8px 12px',
            padding: '8px 12px',
            borderRadius: '8px',
            background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.15), rgba(168, 85, 247, 0.15))',
            border: '1px solid rgba(139, 92, 246, 0.3)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '8px',
          }}>
            <div style={{ fontSize: '11px', color: 'var(--text-primary)' }}>
              📦 <strong>{guestMigrationCount} guest chat{guestMigrationCount === 1 ? '' : 's'}</strong> available
            </div>
            <button
              onClick={onOpenMigration}
              style={{
                padding: '3px 8px',
                borderRadius: '5px',
                border: 'none',
                background: '#6366f1',
                color: '#fff',
                fontSize: '10px',
                fontWeight: '600',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              Import
            </button>
          </div>
        )}

        {/* Drawer Sub-tab selector */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', padding: '6px 12px', gap: '6px', background: 'var(--bg-app)' }}>
          {[
            { key: 'chats', label: `Chats (${pastConversations.length})`, icon: '💬' },
            { key: 'plans', label: `Plans (${pastPlans.length})`, icon: '📋' },
            { key: 'memory', label: 'Memory Bank', icon: '🧠' },
          ].map(tab => (
            <button
              key={tab.key}
              onClick={() => setHistoryTab(tab.key)}
              style={{
                flex: 1,
                padding: '6px 4px',
                borderRadius: '6px',
                border: 'none',
                background: historyTab === tab.key ? 'var(--bg-card)' : 'transparent',
                color: historyTab === tab.key ? 'var(--text-primary)' : 'var(--text-secondary)',
                fontWeight: historyTab === tab.key ? '700' : '500',
                fontSize: '11px',
                cursor: 'pointer',
                boxShadow: historyTab === tab.key ? 'var(--shadow-sm)' : 'none',
                textAlign: 'center',
                whiteSpace: 'nowrap'
              }}
            >
              {tab.icon} {tab.label}
            </button>
          ))}
        </div>

        {/* Drawer Body Items */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px' }}>
          {historyTab === 'chats' && (
            <div>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: '8px',
                padding: '0 4px',
                fontSize: '11px',
                color: 'var(--text-muted)'
              }}>
                <span style={{ fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  {showArchived ? `Archived (${archivedCount})` : 'Recent Chats'}
                </span>
                {archivedCount > 0 && (
                  <button
                    onClick={() => setShowArchived(v => !v)}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: 'var(--brand)',
                      cursor: 'pointer',
                      fontSize: '11px',
                      fontWeight: '700',
                      padding: '2px 4px'
                    }}
                  >
                    {showArchived ? '← Active Chats' : `Archived (${archivedCount})`}
                  </button>
                )}
              </div>

              {visibleConversations.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '30px 12px', color: 'var(--text-muted)', fontSize: '12px' }}>
                  <div style={{ fontSize: '24px', marginBottom: '8px' }}>{showArchived ? '🗃️' : '💬'}</div>
                  <div>{showArchived ? 'No archived chats.' : 'No previous chats yet.'}</div>
                  <div style={{ fontSize: '11px', marginTop: '4px' }}>
                    {showArchived ? 'Chats you archive will be stored here.' : 'Chats are automatically stored and remembered across sessions.'}
                  </div>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {visibleConversations.map(conv => (
                    <ChatConversationItem
                      key={conv.id}
                      conv={conv}
                      isCurrent={conversationId === conv.id}
                      isMenuOpen={openMenuConvId === conv.id}
                      onToggleMenu={() => setOpenMenuConvId(openMenuConvId === conv.id ? null : conv.id)}
                      isEditing={editingConvId === conv.id}
                      editingTitle={editingTitle}
                      setEditingTitle={setEditingTitle}
                      onSelect={onSelectPastChat}
                      onStartRename={handleStartRename}
                      onSaveRename={handleSaveRename}
                      onCancelRename={handleCancelRename}
                      onTogglePin={handleTogglePin}
                      onToggleArchive={handleToggleArchive}
                      onOpenDeleteConfirm={handleOpenDeleteConfirm}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {historyTab === 'plans' && (
            pastPlans.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '30px 12px', color: 'var(--text-muted)', fontSize: '12px' }}>
                <div style={{ fontSize: '24px', marginBottom: '8px' }}>📋</div>
                <div>No previous plans yet.</div>
                <div style={{ fontSize: '11px', marginTop: '4px' }}>Goals decomposed by the Planner will be recorded here.</div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {pastPlans.map(plan => (
                  <div
                    key={plan.id}
                    onClick={() => onSelectPastPlan(plan)}
                    style={{
                      padding: '10px 12px',
                      borderRadius: '8px',
                      border: '1px solid var(--border)',
                      background: 'var(--bg-card)',
                      cursor: 'pointer',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '6px',
                      transition: 'all 0.15s ease',
                    }}
                    onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--brand)'}
                    onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--border)'}
                    title="Click to reference this plan in chat"
                  >
                    <div style={{ fontSize: '12.5px', fontWeight: '700', color: 'var(--text-primary)', lineHeight: 1.3 }}>
                      {plan.goal}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '11px' }}>
                      <span style={{
                        padding: '2px 7px',
                        borderRadius: '6px',
                        fontSize: '10px',
                        fontWeight: '700',
                        background: plan.status === 'completed' ? 'var(--code-bg)' : 'var(--hackathon-bg)',
                        color: plan.status === 'completed' ? 'var(--code-text)' : 'var(--hackathon-text)',
                        textTransform: 'uppercase'
                      }}>
                        {plan.status}
                      </span>
                      <span style={{ color: 'var(--text-muted)', fontSize: '10.5px' }}>
                        {new Date(plan.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )
          )}

          {historyTab === 'memory' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ padding: '12px', borderRadius: '8px', background: 'var(--code-bg)', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12.5px', fontWeight: '700', color: 'var(--code-text)', marginBottom: '4px' }}>
                  <span>🟢</span> Cross-Session Recall Active
                </div>
                <p style={{ margin: 0, fontSize: '11.5px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                  Compass automatically recalls your past chats, deadlines, and schedule commitments in new chats so schedules never clash.
                </p>
              </div>

              <div style={{ padding: '12px', borderRadius: '8px', background: 'var(--bg-card)', border: '1px solid var(--border)' }}>
                <div style={{ fontSize: '12px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '8px' }}>
                  Memory Metrics
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11.5px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                  <span>Active Tasks & Deadlines:</span>
                  <strong style={{ color: 'var(--text-primary)' }}>{tasks.length}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11.5px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                  <span>Recorded Conversations:</span>
                  <strong style={{ color: 'var(--text-primary)' }}>{pastConversations.length}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11.5px', color: 'var(--text-secondary)' }}>
                  <span>Executed Agent Plans:</span>
                  <strong style={{ color: 'var(--text-primary)' }}>{pastPlans.length}</strong>
                </div>
              </div>

              <button
                onClick={() => {
                  onClose()
                  if (onCheckScheduleClashes) onCheckScheduleClashes()
                }}
                style={{
                  padding: '9px 12px',
                  borderRadius: '8px',
                  background: 'var(--bg-card-soft)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-primary)',
                  fontSize: '12px',
                  fontWeight: '600',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '6px'
                }}
              >
                <span>🔍</span> Check for Schedule Clashes Now
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* Delete Confirmation Modal */}
      {confirmDeleteConv && (
        <div
          onClick={() => setConfirmDeleteConv(null)}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.65)',
            backdropFilter: 'blur(3px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '16px',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              borderRadius: '14px',
              padding: '22px',
              maxWidth: '400px',
              width: '100%',
              boxShadow: 'var(--shadow-lg)',
              display: 'flex',
              flexDirection: 'column',
              gap: '14px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <div style={{
                width: '38px', height: '38px', borderRadius: '10px',
                background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444',
                display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px', flexShrink: 0
              }}>
                🗑️
              </div>
              <div>
                <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '800', color: 'var(--text-primary)' }}>
                  Delete chat?
                </h3>
                <p style={{ margin: '2px 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
                  This action cannot be undone.
                </p>
              </div>
            </div>

            <p style={{ margin: 0, fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              This will permanently delete <strong>"{confirmDeleteConv.title || 'Chat Session'}"</strong> and all associated messages from your workspace memory.
            </p>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '6px' }}>
              <button
                onClick={() => setConfirmDeleteConv(null)}
                style={{
                  padding: '8px 15px', borderRadius: '8px', border: '1px solid var(--border)',
                  background: 'transparent', color: 'var(--text-primary)', fontSize: '12.5px',
                  fontWeight: '600', cursor: 'pointer'
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleExecuteDelete}
                style={{
                  padding: '8px 18px', borderRadius: '8px', border: 'none',
                  background: '#ef4444', color: '#ffffff', fontSize: '12.5px',
                  fontWeight: '700', cursor: 'pointer', boxShadow: '0 2px 8px rgba(239, 68, 68, 0.35)'
                }}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
