import React, { useState, useEffect, useCallback } from 'react'
import {
  fetchMigrationConversations,
  importAllGuestData,
  importSelectedGuestConversations,
  skipMigration,
} from '../api/client'
import { X, Check, Lock } from 'lucide-react'
import Logo from './Logo'

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

  // The success view is the one place where closing means "finished", not "skip for now".
  const handleDone = useCallback(() => {
    if (typeof onMigrationComplete === 'function') onMigrationComplete(importResult)
    if (typeof onClose === 'function') onClose()
  }, [onMigrationComplete, onClose, importResult])

  const handleSkip = useCallback(() => {
    if (view === 'success') {
      handleDone()
      return
    }
    // 1. Immediately dismiss modal so UI responds without blocking on network I/O
    if (typeof onClose === 'function') {
      onClose()
    }
    // 2. Persist session-level dismissal to prevent immediate reopening during auth hydration / polling
    try {
      if (typeof window !== 'undefined' && window.sessionStorage) {
        window.sessionStorage.setItem('compass_migration_dismissed', '1')
      }
    } catch {
      /* ignore storage access error */
    }
    // 3. Notify backend asynchronously to record preference in cookie (preserves all guest data)
    skipMigration().catch((err) => {
      console.warn('[Migration] Skip notification failed:', err)
    })
  }, [onClose, view, handleDone])

  // Close dialog on Escape key when interactive (not importing)
  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && view !== 'importing') {
        e.preventDefault()
        handleSkip()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen, view, handleSkip])

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
    } catch (err) {
      setError(err.message || 'Failed to import selected conversations')
      setView('select')
    }
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
        background: 'rgba(27, 26, 23, 0.45)',
        backdropFilter: 'blur(3px)',
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
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-card, 8px)',
          width: '100%',
          maxWidth: view === 'select' ? '620px' : '480px',
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 8px 30px rgba(0, 0, 0, 0.12)',
          overflow: 'hidden',
          transition: 'max-width 0.2s ease',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '1.25rem 1.5rem',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <Logo size={36} alt="" />
            <div>
              <h2
                style={{
                  margin: 0,
                  fontSize: '1.1rem',
                  fontWeight: 600,
                  color: 'var(--text-primary)',
                  letterSpacing: '-0.01em',
                }}
              >
                {view === 'select' ? 'Choose Conversations to Import' : 'Import Guest Conversations'}
              </h2>
              <p
                style={{
                  margin: '2px 0 0',
                  fontSize: '0.8rem',
                  color: 'var(--text-secondary)',
                }}
              >
                Seamless anonymous session migration
              </p>
            </div>
          </div>
          {view !== 'importing' && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                handleSkip()
              }}
              style={{
                background: 'var(--bg-card-soft, rgba(255, 255, 255, 0.05))',
                border: '1px solid var(--border)',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                width: '32px',
                height: '32px',
                minWidth: '32px',
                minHeight: '32px',
                borderRadius: 'var(--radius-btn, 6px)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: 0,
                transition: 'background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease',
              }}
              title="Close"
              aria-label="Close import dialog"
            >
              <X size={16} strokeWidth={1.8} />
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
                <Lock size={14} strokeWidth={1.8} style={{ flexShrink: 0, marginTop: '2px' }} />
                <span>
                  <strong>Data Safety Guarantee:</strong> Original guest conversations and memory will be safely preserved in your browser. You can always import them later.
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                <button
                  onClick={handleImportAll}
                  className="btn-touch-target btn-primary-amber"
                  style={{
                    padding: '0.75rem 1rem',
                    borderRadius: 'var(--radius-btn, 6px)',
                    fontSize: '0.9rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    minHeight: '44px',
                  }}
                >
                  Import All Conversations & Context
                </button>

                <button
                  onClick={handleOpenSelect}
                  className="btn-touch-target btn-secondary"
                  style={{
                    padding: '0.75rem 1rem',
                    borderRadius: 'var(--radius-btn, 6px)',
                    fontSize: '0.9rem',
                    fontWeight: 500,
                    cursor: 'pointer',
                    minHeight: '44px',
                  }}
                >
                  Choose Conversations...
                </button>

                <button
                  onClick={handleSkip}
                  className="btn-touch-target btn-secondary"
                  style={{
                    padding: '0.6rem 1rem',
                    borderRadius: 'var(--radius-btn, 6px)',
                    fontSize: '0.85rem',
                    cursor: 'pointer',
                    minHeight: '44px',
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
                        className="btn-touch-target btn-secondary"
                        style={{
                          padding: '0.6rem 1rem',
                          borderRadius: 'var(--radius-btn, 6px)',
                          color: 'var(--text-secondary)',
                          cursor: 'pointer',
                          fontSize: '0.85rem',
                          minHeight: '44px',
                        }}
                      >
                        Skip
                      </button>
                      <button
                        onClick={handleImportSelected}
                        disabled={selectedIds.size === 0 && !importMemory}
                        className="btn-touch-target btn-primary-amber"
                        style={{
                          padding: '0.6rem 1.25rem',
                          borderRadius: 'var(--radius-btn, 6px)',
                          fontWeight: 600,
                          fontSize: '0.85rem',
                          cursor: (selectedIds.size === 0 && !importMemory) ? 'not-allowed' : 'pointer',
                          opacity: (selectedIds.size === 0 && !importMemory) ? 0.5 : 1,
                          minHeight: '44px',
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
                  border: '3px solid var(--border)',
                  borderTopColor: 'var(--accent)',
                  borderRadius: '50%',
                  animation: 'spin 1s linear infinite',
                  margin: '0 auto 1.25rem',
                }}
              />
              <div style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.25rem' }}>
                Importing Conversations...
              </div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
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
                  borderRadius: 'var(--radius-card, 8px)',
                  background: 'var(--bg-card-soft)',
                  border: '1px solid var(--border)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  margin: '0 auto 1rem',
                  color: 'var(--code)',
                }}
              >
                <Check size={28} strokeWidth={1.8} />
              </div>
              <div style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
                Import Complete!
              </div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: '1.5rem' }}>
                {importResult?.imported_count ?? 0} conversation{importResult?.imported_count === 1 ? '' : 's'} successfully brought into your Compass account.
                <br />
                Original guest records remain safely preserved in your browser session.
              </div>
              <button
                id="migration-success-done"
                onClick={handleDone}
                className="btn-touch-target btn-primary-amber"
                style={{
                  padding: '0.7rem 1.75rem',
                  borderRadius: 'var(--radius-btn, 6px)',
                  fontWeight: 600,
                  fontSize: '0.9rem',
                  cursor: 'pointer',
                  minHeight: '44px',
                }}
              >
                Done
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
