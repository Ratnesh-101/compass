import React, { useState, useEffect } from 'react'
import {
  fetchMigrationConversations,
  importAllGuestData,
  importSelectedGuestConversations,
  skipMigration,
} from '../api/client'

export default function MigrationModal({
  isOpen,
  onClose,
  guestConversationsCount = 0,
  onMigrationComplete,
}) {
  const [view, setView] = useState('prompt') // 'prompt' | 'select' | 'importing' | 'success'
  const [conversations, setConversations] = useState([])
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [importMemory, setImportMemory] = useState(true)
  const [loadingList, setLoadingList] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const [error, setError] = useState(null)

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setView('prompt')
      setError(null)
      setImportResult(null)
    }
  }, [isOpen])

  // Fetch conversations list when switching to select view
  const handleOpenSelect = async () => {
    setView('select')
    setLoadingList(true)
    setError(null)
    try {
      const data = await fetchMigrationConversations()
      const convs = data.conversations || []
      setConversations(convs)
      // Pre-select conversations that haven't been imported yet
      const eligibleIds = convs.filter(c => !c.already_imported).map(c => c.id)
      setSelectedIds(new Set(eligibleIds))
    } catch (err) {
      setError(err.message || 'Failed to load guest conversations')
    } finally {
      setLoadingList(false)
    }
  }

  const handleToggleSelect = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const handleSelectAll = () => {
    const allEligible = conversations.filter(c => !c.already_imported).map(c => c.id)
    setSelectedIds(new Set(allEligible))
  }

  const handleDeselectAll = () => {
    setSelectedIds(new Set())
  }

  const handleImportAll = async () => {
    setView('importing')
    setError(null)
    try {
      const result = await importAllGuestData()
      setImportResult(result)
      setView('success')
      if (onMigrationComplete) onMigrationComplete(result)
    } catch (err) {
      setError(err.message || 'Failed to import conversations')
      setView('prompt')
    }
  }

  const handleImportSelected = async () => {
    if (selectedIds.size === 0 && !importMemory) {
      setError('Please select at least one conversation or memory to import.')
      return
    }
    setView('importing')
    setError(null)
    try {
      const result = await importSelectedGuestConversations(Array.from(selectedIds), importMemory)
      setImportResult(result)
      setView('success')
      if (onMigrationComplete) onMigrationComplete(result)
    } catch (err) {
      setError(err.message || 'Failed to import selected conversations')
      setView('select')
    }
  }

  const handleSkip = async () => {
    await skipMigration()
    onClose()
  }

  if (!isOpen) return null

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(5, 7, 12, 0.75)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        padding: '1rem',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && view !== 'importing') {
          handleSkip()
        }
      }}
    >
      <div
        style={{
          background: 'var(--bg-card, #121824)',
          border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
          borderRadius: '16px',
          width: '100%',
          maxWidth: view === 'select' ? '620px' : '480px',
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 24px 48px -12px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.05)',
          overflow: 'hidden',
          transition: 'max-width 0.2s ease',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '1.25rem 1.5rem',
            borderBottom: '1px solid var(--border, rgba(255, 255, 255, 0.08))',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div
              style={{
                width: '36px',
                height: '36px',
                borderRadius: '10px',
                background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(168, 85, 247, 0.2))',
                border: '1px solid rgba(139, 92, 246, 0.3)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '1.2rem',
              }}
            >
              🧭
            </div>
            <div>
              <h2
                style={{
                  margin: 0,
                  fontSize: '1.1rem',
                  fontWeight: 600,
                  color: 'var(--text-primary, #ffffff)',
                  letterSpacing: '-0.01em',
                }}
              >
                {view === 'select' ? 'Choose Conversations to Import' : 'Import Guest Conversations'}
              </h2>
              <p
                style={{
                  margin: '2px 0 0',
                  fontSize: '0.8rem',
                  color: 'var(--text-secondary, #94a3b8)',
                }}
              >
                Seamless anonymous session migration
              </p>
            </div>
          </div>
          {view !== 'importing' && (
            <button
              onClick={handleSkip}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-secondary, #94a3b8)',
                cursor: 'pointer',
                fontSize: '1.25rem',
                padding: '4px 8px',
                borderRadius: '6px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              title="Close"
            >
              ✕
            </button>
          )}
        </div>

        {/* Body Content */}
        <div style={{ padding: '1.5rem', overflowY: 'auto', flex: 1 }}>
          {error && (
            <div
              style={{
                padding: '0.75rem 1rem',
                borderRadius: '8px',
                background: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                color: '#f87171',
                fontSize: '0.85rem',
                marginBottom: '1rem',
              }}
            >
              {error}
            </div>
          )}

          {/* VIEW: PROMPT */}
          {view === 'prompt' && (
            <div>
              <div
                style={{
                  padding: '1rem',
                  borderRadius: '12px',
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.06)',
                  marginBottom: '1.25rem',
                }}
              >
                <div style={{ fontSize: '0.95rem', fontWeight: 500, color: 'var(--text-primary, #fff)', marginBottom: '0.5rem' }}>
                  Welcome back!
                </div>
                <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary, #94a3b8)', lineHeight: 1.5 }}>
                  You have{' '}
                  <strong style={{ color: 'var(--accent, #818cf8)' }}>
                    {guestConversationsCount > 0 ? guestConversationsCount : 'recent'}
                  </strong>{' '}
                  conversation{guestConversationsCount === 1 ? '' : 's'} from before you signed in.
                  Would you like to bring them into your Compass account?
                </div>
              </div>

              <div
                style={{
                  fontSize: '0.8rem',
                  color: 'var(--text-secondary, #64748b)',
                  lineHeight: 1.4,
                  marginBottom: '1.5rem',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '0.5rem',
                }}
              >
                <span>🔒</span>
                <span>
                  <strong>Data Safety Guarantee:</strong> Original guest conversations and memory will be safely preserved in your browser. You can always import them later.
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                <button
                  onClick={handleImportAll}
                  style={{
                    padding: '0.75rem 1rem',
                    borderRadius: '10px',
                    border: 'none',
                    background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
                    color: '#ffffff',
                    fontWeight: 600,
                    fontSize: '0.9rem',
                    cursor: 'pointer',
                    boxShadow: '0 4px 12px rgba(79, 70, 229, 0.35)',
                    transition: 'all 0.15s ease',
                  }}
                >
                  Import All Conversations & Context
                </button>

                <button
                  onClick={handleOpenSelect}
                  style={{
                    padding: '0.75rem 1rem',
                    borderRadius: '10px',
                    border: '1px solid var(--border, rgba(255, 255, 255, 0.15))',
                    background: 'rgba(255, 255, 255, 0.04)',
                    color: 'var(--text-primary, #ffffff)',
                    fontWeight: 500,
                    fontSize: '0.9rem',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                >
                  Choose Conversations...
                </button>

                <button
                  onClick={handleSkip}
                  style={{
                    padding: '0.6rem 1rem',
                    borderRadius: '10px',
                    border: 'none',
                    background: 'transparent',
                    color: 'var(--text-secondary, #94a3b8)',
                    fontSize: '0.85rem',
                    cursor: 'pointer',
                    transition: 'color 0.15s ease',
                  }}
                >
                  Skip for Now
                </button>
              </div>
            </div>
          )}

          {/* VIEW: SELECT */}
          {view === 'select' && (
            <div>
              {loadingList ? (
                <div style={{ textAlign: 'center', padding: '2rem 0', color: 'var(--text-secondary, #94a3b8)' }}>
                  Loading your guest conversations...
                </div>
              ) : conversations.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '2rem 0', color: 'var(--text-secondary, #94a3b8)' }}>
                  No guest conversations found to import.
                </div>
              ) : (
                <div>
                  {/* Select Controls */}
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      marginBottom: '0.75rem',
                      fontSize: '0.8rem',
                      color: 'var(--text-secondary, #94a3b8)',
                    }}
                  >
                    <span>
                      {selectedIds.size} of {conversations.filter(c => !c.already_imported).length} eligible selected
                    </span>
                    <div style={{ display: 'flex', gap: '0.75rem' }}>
                      <button
                        onClick={handleSelectAll}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: 'var(--accent, #818cf8)',
                          cursor: 'pointer',
                          padding: 0,
                          fontSize: '0.8rem',
                        }}
                      >
                        Select All
                      </button>
                      <span>•</span>
                      <button
                        onClick={handleDeselectAll}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: 'var(--text-secondary, #94a3b8)',
                          cursor: 'pointer',
                          padding: 0,
                          fontSize: '0.8rem',
                        }}
                      >
                        Deselect All
                      </button>
                    </div>
                  </div>

                  {/* Conversation List */}
                  <div
                    style={{
                      maxHeight: '280px',
                      overflowY: 'auto',
                      borderRadius: '10px',
                      border: '1px solid var(--border, rgba(255, 255, 255, 0.08))',
                      background: 'rgba(0, 0, 0, 0.2)',
                      marginBottom: '1rem',
                    }}
                  >
                    {conversations.map((conv) => {
                      const isSelected = selectedIds.has(conv.id)
                      const isAlready = Boolean(conv.already_imported)
                      return (
                        <div
                          key={conv.id}
                          onClick={() => {
                            if (!isAlready) handleToggleSelect(conv.id)
                          }}
                          style={{
                            padding: '0.75rem 1rem',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
                            background: isSelected ? 'rgba(99, 102, 241, 0.08)' : 'transparent',
                            cursor: isAlready ? 'default' : 'pointer',
                            opacity: isAlready ? 0.6 : 1,
                            transition: 'background 0.15s ease',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', minWidth: 0 }}>
                            <input
                              type="checkbox"
                              checked={isSelected || isAlready}
                              disabled={isAlready}
                              onChange={() => handleToggleSelect(conv.id)}
                              style={{
                                cursor: isAlready ? 'default' : 'pointer',
                                accentColor: '#6366f1',
                              }}
                            />
                            <div style={{ minWidth: 0 }}>
                              <div
                                style={{
                                  fontSize: '0.875rem',
                                  fontWeight: 500,
                                  color: 'var(--text-primary, #ffffff)',
                                  whiteSpace: 'nowrap',
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                }}
                              >
                                {conv.title || 'Untitled Conversation'}
                              </div>
                              <div
                                style={{
                                  fontSize: '0.75rem',
                                  color: 'var(--text-secondary, #94a3b8)',
                                  marginTop: '2px',
                                }}
                              >
                                {conv.message_count || 0} messages •{' '}
                                {conv.last_active_at ? new Date(conv.last_active_at).toLocaleDateString() : 'Recent'}
                              </div>
                            </div>
                          </div>

                          {isAlready && (
                            <span
                              style={{
                                fontSize: '0.7rem',
                                padding: '2px 8px',
                                borderRadius: '12px',
                                background: 'rgba(34, 197, 94, 0.15)',
                                color: '#4ade80',
                                border: '1px solid rgba(34, 197, 94, 0.25)',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              Already in account
                            </span>
                          )}
                        </div>
                      )
                    })}
                  </div>

                  {/* Memory Context Checkbox */}
                  <div
                    style={{
                      padding: '0.75rem 1rem',
                      borderRadius: '8px',
                      background: 'rgba(255, 255, 255, 0.03)',
                      border: '1px solid rgba(255, 255, 255, 0.06)',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.75rem',
                      marginBottom: '1.25rem',
                    }}
                  >
                    <input
                      type="checkbox"
                      id="import-memory-toggle"
                      checked={importMemory}
                      onChange={(e) => setImportMemory(e.target.checked)}
                      style={{ accentColor: '#6366f1', cursor: 'pointer' }}
                    />
                    <label
                      htmlFor="import-memory-toggle"
                      style={{
                        fontSize: '0.85rem',
                        color: 'var(--text-primary, #e2e8f0)',
                        cursor: 'pointer',
                      }}
                    >
                      Also import accumulated context and cross-session memory
                    </label>
                  </div>

                  {/* Actions */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem' }}>
                    <button
                      onClick={() => setView('prompt')}
                      style={{
                        padding: '0.6rem 1rem',
                        borderRadius: '8px',
                        border: '1px solid var(--border, rgba(255, 255, 255, 0.15))',
                        background: 'transparent',
                        color: 'var(--text-secondary, #94a3b8)',
                        cursor: 'pointer',
                        fontSize: '0.85rem',
                      }}
                    >
                      ← Back
                    </button>
                    <div style={{ display: 'flex', gap: '0.75rem' }}>
                      <button
                        onClick={handleSkip}
                        style={{
                          padding: '0.6rem 1rem',
                          borderRadius: '8px',
                          border: 'none',
                          background: 'transparent',
                          color: 'var(--text-secondary, #94a3b8)',
                          cursor: 'pointer',
                          fontSize: '0.85rem',
                        }}
                      >
                        Skip
                      </button>
                      <button
                        onClick={handleImportSelected}
                        disabled={selectedIds.size === 0 && !importMemory}
                        style={{
                          padding: '0.6rem 1.25rem',
                          borderRadius: '8px',
                          border: 'none',
                          background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
                          color: '#ffffff',
                          fontWeight: 600,
                          fontSize: '0.85rem',
                          cursor: (selectedIds.size === 0 && !importMemory) ? 'not-allowed' : 'pointer',
                          opacity: (selectedIds.size === 0 && !importMemory) ? 0.5 : 1,
                        }}
                      >
                        Import Selected ({selectedIds.size})
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* VIEW: IMPORTING */}
          {view === 'importing' && (
            <div style={{ textAlign: 'center', padding: '2.5rem 0' }}>
              <div
                style={{
                  width: '40px',
                  height: '40px',
                  border: '3px solid rgba(99, 102, 241, 0.2)',
                  borderTopColor: '#6366f1',
                  borderRadius: '50%',
                  animation: 'spin 1s linear infinite',
                  margin: '0 auto 1.25rem',
                }}
              />
              <div style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-primary, #ffffff)', marginBottom: '0.25rem' }}>
                Importing Conversations...
              </div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary, #94a3b8)' }}>
                Preserving messages, timestamps, and context safely.
              </div>
              <style>{`
                @keyframes spin {
                  to { transform: rotate(360deg); }
                }
              `}</style>
            </div>
          )}

          {/* VIEW: SUCCESS */}
          {view === 'success' && (
            <div style={{ textAlign: 'center', padding: '1.5rem 0' }}>
              <div
                style={{
                  width: '52px',
                  height: '52px',
                  borderRadius: '50%',
                  background: 'rgba(34, 197, 94, 0.15)',
                  border: '1px solid rgba(34, 197, 94, 0.3)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '1.75rem',
                  margin: '0 auto 1rem',
                  color: '#4ade80',
                }}
              >
                ✓
              </div>
              <div style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-primary, #ffffff)', marginBottom: '0.5rem' }}>
                Import Complete!
              </div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary, #94a3b8)', lineHeight: 1.5, marginBottom: '1.5rem' }}>
                {importResult?.imported_count ?? 0} conversation{importResult?.imported_count === 1 ? '' : 's'} successfully brought into your Compass account.
                <br />
                Original guest records remain safely preserved in your browser session.
              </div>
              <button
                onClick={onClose}
                style={{
                  padding: '0.7rem 1.75rem',
                  borderRadius: '8px',
                  border: 'none',
                  background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
                  color: '#ffffff',
                  fontWeight: 600,
                  fontSize: '0.9rem',
                  cursor: 'pointer',
                }}
              >
                Continue Chatting
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
