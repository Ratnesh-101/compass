import React, { useState, useEffect } from 'react'
import {
  logoutUser,
  getGoogleOAuthConnectUrl,
  disconnectCalendar,
  syncCalendarNow,
  getCalendarExportUrl,
  checkGoogleOAuthStatus,
  quickConnectUser,
  setCurrentUserId,
  getKnownAccounts,
} from '../api/client'

export default function AuthModal({ isOpen, onClose, currentUser, onUserChanged }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [successMsg, setSuccessMsg] = useState(null)
  const [copiedIcs, setCopiedIcs] = useState(false)
  const [oauthStatus, setOauthStatus] = useState(null) // null = loading, object = result
  const [emailInput, setEmailInput] = useState('')

  // Check OAuth configuration every time the modal opens
  useEffect(() => {
    if (!isOpen) return
    setOauthStatus(null)
    checkGoogleOAuthStatus().then(setOauthStatus)
  }, [isOpen])

  if (!isOpen) return null

  const handleQuickLogin = async (emailToUse) => {
    const cleanEmail = (emailToUse || emailInput || '').trim().toLowerCase()
    if (!cleanEmail || !cleanEmail.includes('@')) {
      setError('Please enter a valid email address (e.g. student@vit.ac.in)')
      return
    }
    setLoading(true)
    setError(null)
    setSuccessMsg(null)
    try {
      await quickConnectUser(cleanEmail)
      setCurrentUserId(cleanEmail)
      if (onUserChanged) onUserChanged(cleanEmail)
      setSuccessMsg(`Signed in as ${cleanEmail}`)
      setEmailInput('')
    } catch {
      setCurrentUserId(cleanEmail)
      if (onUserChanged) onUserChanged(cleanEmail)
      setSuccessMsg(`Switched local identity to ${cleanEmail}`)
      setEmailInput('')
    } finally {
      setLoading(false)
    }
  }

  const handleLogout = async () => {

    setLoading(true)
    setError(null)
    try {
      await logoutUser()
      if (currentUser?.authenticated) {
        await disconnectCalendar()
      }
      if (onUserChanged) onUserChanged(null)
      onClose()
    } catch (err) {
      setError(err.message || 'Failed to sign out')
    } finally {
      setLoading(false)
    }
  }

  const handleCopyIcs = () => {
    const url = getCalendarExportUrl()
    const fullUrl = url.startsWith('http') ? url : `${window.location.origin}${url}`
    navigator.clipboard.writeText(fullUrl)
    setCopiedIcs(true)
    setTimeout(() => setCopiedIcs(false), 2500)
  }

  const activeEmail = currentUser?.authenticated ? currentUser.email : (
    (currentUser?.email && currentUser.email.includes('@')) ? currentUser.email : (
      typeof localStorage !== 'undefined'
        ? (localStorage.getItem('compass_user_email') || (localStorage.getItem('compass_user_id')?.includes('@') ? localStorage.getItem('compass_user_id') : null))
        : null
    )
  )
  const isLiveCalendarLinked = Boolean(
    currentUser?.calendar?.connected &&
    currentUser?.calendar?.mode === 'live' &&
    !currentUser?.calendar?.is_simulated
  )
  const isDemoCalendarLinked = Boolean(
    currentUser?.calendar?.connected &&
    (!isLiveCalendarLinked || currentUser?.calendar?.is_simulated)
  )

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(15, 23, 42, 0.45)',
        backdropFilter: 'blur(4px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1100,
        padding: '20px'
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: 'var(--bg-card)',
          borderRadius: '16px',
          border: '1px solid var(--border)',
          width: '100%',
          maxWidth: '560px',
          maxHeight: '90vh',
          overflowY: 'auto',
          padding: '26px',
          boxShadow: 'var(--shadow-lg)',
          color: 'var(--text-primary)'
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontSize: '24px' }}>👤</span>
            <div>
              <h3 style={{ fontSize: '18px', fontWeight: '800', margin: 0, color: 'var(--text-primary)' }}>
                Account & Google Calendar
              </h3>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)', margin: '2px 0 0' }}>
                Select your account and manage individual memory isolation
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'var(--bg-card-soft)',
              border: '1px solid var(--border)',
              color: 'var(--text-secondary)',
              width: '28px',
              height: '28px',
              borderRadius: '7px',
              cursor: 'pointer',
              fontSize: '14px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}
          >
            ✕
          </button>
        </div>

        {/* Status Banners */}
        {error && (
          <div style={{
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            color: '#dc2626',
            padding: '10px 14px',
            borderRadius: '8px',
            fontSize: '13px',
            marginBottom: '16px'
          }}>
            ⚠️ {error}
          </div>
        )}
        {successMsg && (
          <div style={{
            background: 'rgba(16, 185, 129, 0.1)',
            border: '1px solid rgba(16, 185, 129, 0.3)',
            color: '#059669',
            padding: '10px 14px',
            borderRadius: '8px',
            fontSize: '13px',
            marginBottom: '16px'
          }}>
            ✓ {successMsg}
          </div>
        )}

        {/* Current Session Overview */}
        <div style={{
          background: 'var(--bg-card-soft)',
          border: '1px solid var(--border)',
          borderRadius: '12px',
          padding: '16px',
          marginBottom: '20px'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)', fontWeight: '700' }}>
                Active Account
              </div>
              <div style={{ fontSize: '15px', fontWeight: '700', color: activeEmail ? 'var(--primary)' : 'var(--text-secondary)', marginTop: '2px' }}>
                {activeEmail || 'Guest Mode (No active account)'}
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                background: activeEmail ? '#10b981' : '#94a3b8',
                boxShadow: activeEmail ? '0 0 8px #10b981' : 'none'
              }} />
              <span style={{ fontSize: '12px', color: activeEmail ? '#059669' : 'var(--text-muted)', fontWeight: '600' }}>
                {activeEmail ? 'Isolated Memory Active' : 'Unauthenticated'}
              </span>
            </div>
          </div>

          <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--text-secondary)', lineHeight: '1.5' }}>
            🔒 <strong>Per-Account Privacy:</strong> Deadlines, tasks, and assistant memory chunks belong strictly to your active account. Switching accounts automatically isolates all workspace state.
          </div>
        </div>

        {/* Authentication Status & Actions */}
        <div style={{ marginBottom: '24px' }}>
          <h4 style={{ fontSize: '13px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-secondary)', fontWeight: '700', marginBottom: '12px' }}>
            1. Identity & Sign-In
          </h4>

          {currentUser?.authenticated ? (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '14px',
              borderRadius: '10px',
              background: 'rgba(16, 185, 129, 0.08)',
              border: '1px solid rgba(16, 185, 129, 0.25)'
            }}>
              <div>
                <div style={{ fontSize: '13.5px', fontWeight: '700', color: '#059669' }}>
                  ✓ Authenticated as {activeEmail}
                </div>
                <div style={{ fontSize: '11.5px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                  Session verified and active.
                </div>
              </div>
              <button
                onClick={handleLogout}
                disabled={loading}
                style={{
                  padding: '7px 14px',
                  borderRadius: '6px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-card)',
                  color: 'var(--danger)',
                  fontSize: '12px',
                  fontWeight: '600',
                  cursor: 'pointer'
                }}
              >
                Sign Out
              </button>
            </div>
          ) : (
            <div style={{
              padding: '18px',
              borderRadius: '12px',
              background: 'var(--bg-card-soft)',
              border: '1px solid var(--border)',
              display: 'flex',
              flexDirection: 'column',
              gap: '16px'
            }}>
              {/* Instant Email Sign-In */}
              <div>
                <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '4px' }}>
                  Instant Sign-In (Select or Enter Email)
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '10px' }}>
                  Enter your email to sign in instantly with isolated memory.
                </div>

                <form
                  onSubmit={e => {
                    e.preventDefault()
                    handleQuickLogin(emailInput)
                  }}
                  style={{ display: 'flex', gap: '8px', marginBottom: '10px' }}
                >
                  <input
                    type="email"
                    placeholder="student@vit.ac.in"
                    value={emailInput}
                    onChange={e => setEmailInput(e.target.value)}
                    style={{
                      flex: 1,
                      padding: '8px 12px',
                      borderRadius: '8px',
                      border: '1px solid var(--border)',
                      background: 'var(--bg-card)',
                      color: 'var(--text-primary)',
                      fontSize: '13px',
                      outline: 'none'
                    }}
                  />
                  <button
                    type="submit"
                    disabled={loading || !emailInput.trim()}
                    style={{
                      padding: '8px 16px',
                      borderRadius: '8px',
                      background: 'var(--primary)',
                      color: '#ffffff',
                      border: 'none',
                      fontSize: '13px',
                      fontWeight: '700',
                      cursor: 'pointer',
                      opacity: (loading || !emailInput.trim()) ? 0.6 : 1
                    }}
                  >
                    Sign In →
                  </button>
                </form>

                {/* Quick Presets */}
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
                  <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Quick Presets:</span>
                  {['student@vit.ac.in', 'demo@compass.app', 'researcher@compass.app'].map(preset => (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => handleQuickLogin(preset)}
                      style={{
                        padding: '3px 8px',
                        borderRadius: '6px',
                        border: '1px solid var(--border)',
                        background: 'var(--bg-card)',
                        color: 'var(--text-secondary)',
                        fontSize: '11px',
                        fontWeight: '500',
                        cursor: 'pointer'
                      }}
                    >
                      {preset}
                    </button>
                  ))}
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', margin: '2px 0' }}>
                <div style={{ flex: 1, height: '1px', background: 'var(--border)' }} />
                <span style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>OR</span>
                <div style={{ flex: 1, height: '1px', background: 'var(--border)' }} />
              </div>

              {/* Google OAuth Button */}
              <div style={{ textAlign: 'center' }}>
                {oauthStatus?.configured ? (
                  <a
                    href={getGoogleOAuthConnectUrl(true)}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '8px',
                      padding: '10px 20px',
                      borderRadius: '8px',
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      color: 'var(--text-primary)',
                      fontSize: '13px',
                      fontWeight: '700',
                      textDecoration: 'none'
                    }}
                  >
                    <span>🔑</span> Sign in with Google OAuth
                  </a>
                ) : (
                  <button
                    type="button"
                    onClick={() => setError('Google OAuth is not configured in .env (GOOGLE_CLIENT_ID missing). Use Instant Sign-In above or see setup instructions below.')}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '8px',
                      padding: '10px 20px',
                      borderRadius: '8px',
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      color: 'var(--text-muted)',
                      fontSize: '13px',
                      fontWeight: '600',
                      cursor: 'pointer'
                    }}
                  >
                    <span>🔑</span> Sign in with Google (Setup Required)
                  </button>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Google Calendar Section */}
        <div style={{
          borderTop: '1px solid var(--border)',
          paddingTop: '20px',
          marginBottom: '20px'
        }}>
          <h4 style={{ fontSize: '13px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-secondary)', fontWeight: '700', marginBottom: '12px' }}>
            2. Google Calendar Linking
          </h4>

          {isLiveCalendarLinked ? (
            <div style={{
              background: 'rgba(16, 185, 129, 0.08)',
              border: '1px solid rgba(16, 185, 129, 0.25)',
              borderRadius: '10px',
              padding: '14px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: '10px',
              marginBottom: '16px'
            }}>
              <div>
                <div style={{ fontSize: '13px', fontWeight: '700', color: '#059669' }}>
                  ✓ Google Calendar Live Sync Connected
                </div>
                <div style={{ fontSize: '11.5px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                  Account: {currentUser?.calendar?.account_email || activeEmail}
                </div>
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  onClick={async () => {
                    setLoading(true)
                    setError(null)
                    setSuccessMsg(null)
                    try {
                      const res = await syncCalendarNow()
                      if (res.is_live && res.live_count > 0) {
                        setSuccessMsg(`Synchronized ${res.live_count} task(s) directly to your Google Calendar!`)
                      } else if (res.is_live) {
                        setSuccessMsg('Google Calendar connected! No pending scheduled tasks or deadlines to sync.')
                      } else {
                        setError(res.message || 'Could not sync with Google Calendar API. Please check your OAuth connection.')
                      }
                    } catch (e) {
                      setError(e.message)
                    } finally {
                      setLoading(false)
                    }
                  }}
                  style={{
                    padding: '6px 12px', borderRadius: '6px',
                    border: '1px solid var(--border)', background: 'var(--bg-card)',
                    color: 'var(--text-primary)', fontSize: '12px', fontWeight: '600', cursor: 'pointer'
                  }}
                >
                  ⚡ Sync Now
                </button>
                <button
                  onClick={async () => {
                    await disconnectCalendar()
                    if (onUserChanged) onUserChanged(activeEmail)
                  }}
                  style={{
                    padding: '6px 12px', borderRadius: '6px',
                    border: '1px solid rgba(239, 68, 68, 0.3)',
                    background: 'rgba(239, 68, 68, 0.08)',
                    color: '#dc2626', fontSize: '12px', fontWeight: '600', cursor: 'pointer'
                  }}
                >
                  Disconnect
                </button>
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {isDemoCalendarLinked && (
                <div style={{
                  background: 'rgba(245, 158, 11, 0.08)',
                  border: '1px solid rgba(245, 158, 11, 0.28)',
                  borderRadius: '10px',
                  padding: '12px 14px',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: '10px'
                }}>
                  <div>
                    <div style={{ fontSize: '12.5px', fontWeight: '700', color: '#b45309' }}>
                      ⚡ Demo Mode Active (Simulated Calendar)
                    </div>
                    <div style={{ fontSize: '11.5px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                      Mock calendar commitments active. Connect genuine Google OAuth below to sync live events to Google Calendar.
                    </div>
                  </div>
                  <button
                    onClick={async () => {
                      await disconnectCalendar()
                      if (onUserChanged) onUserChanged(activeEmail)
                    }}
                    style={{
                      padding: '5px 10px', borderRadius: '6px',
                      border: '1px solid rgba(239, 68, 68, 0.3)',
                      background: 'rgba(239, 68, 68, 0.08)',
                      color: '#dc2626', fontSize: '11px', fontWeight: '600', cursor: 'pointer', flexShrink: 0
                    }}
                  >
                    Reset Demo
                  </button>
                </div>
              )}

              {/* ── Option A: Google OAuth ──────────────────────────────── */}
              <div style={{
                background: 'var(--bg-card-soft)', border: '1px solid var(--border)',
                borderRadius: '10px', padding: '14px'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary)' }}>
                      Option A: Connect with Google OAuth
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px', lineHeight: '1.4' }}>
                      Links your Google Calendar for live two-way sync.
                    </div>
                  </div>

                  {/* Show connect button only when credentials are configured */}
                  {oauthStatus === null ? (
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)', padding: '8px' }}>Checking…</div>
                  ) : oauthStatus.configured ? (
                    <a
                      href={getGoogleOAuthConnectUrl(activeEmail)}
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: '6px',
                        padding: '8px 14px', borderRadius: '8px',
                        background: 'var(--primary)',
                        color: '#ffffff', fontSize: '12.5px', fontWeight: '600',
                        textDecoration: 'none', flexShrink: 0
                      }}
                    >
                      Connect Google →
                    </a>
                  ) : (
                    <span style={{
                      fontSize: '11px', color: '#b45309', fontWeight: '600',
                      background: 'rgba(245, 158, 11, 0.12)',
                      border: '1px solid rgba(245, 158, 11, 0.3)',
                      borderRadius: '6px', padding: '5px 9px', flexShrink: 0
                    }}>
                      ⚙️ Setup Required
                    </span>
                  )}
                </div>

                {oauthStatus?.configured && (
                  <div style={{
                    marginTop: '12px',
                    padding: '8px 12px',
                    background: 'rgba(99, 102, 241, 0.08)',
                    border: '1px solid rgba(99, 102, 241, 0.2)',
                    borderRadius: '6px',
                    fontSize: '11.5px',
                    color: 'var(--text-secondary)',
                    lineHeight: '1.5'
                  }}>
                    💡 <strong>Test App Setup Note:</strong> If Google blocks sign-in with <em>Error 403: access_denied ("App has not completed verification")</em>, add your email ({activeEmail || 'your email'}) under <strong>Google Cloud Console → OAuth consent screen → Test users</strong>.
                  </div>
                )}

                {/* Setup Guide shown when OAuth is not configured */}
                {oauthStatus && !oauthStatus.configured && (
                  <div style={{
                    marginTop: '14px',
                    background: 'var(--bg-app)',
                    border: '1px solid var(--border)',
                    borderRadius: '8px',
                    padding: '14px'
                  }}>
                    <div style={{ fontSize: '12px', fontWeight: '700', color: '#b45309', marginBottom: '10px' }}>
                      📋 One-time Google Cloud setup (5 minutes)
                    </div>
                    <ol style={{ fontSize: '11.5px', color: 'var(--text-secondary)', lineHeight: '1.8', margin: 0, paddingLeft: '18px' }}>
                      <li>
                        Go to{' '}
                        <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noreferrer"
                          style={{ color: 'var(--primary)' }}>
                          console.cloud.google.com/apis/credentials
                        </a>
                      </li>
                      <li>Click <strong style={{ color: 'var(--text-primary)' }}>"+ Create Credentials" → "OAuth client ID"</strong></li>
                      <li>Set Application type: <strong style={{ color: 'var(--text-primary)' }}>Web application</strong></li>
                      <li>
                        Add Authorised redirect URI:{' '}
                        <code style={{
                          background: 'var(--bg-card)', padding: '2px 6px', borderRadius: '4px',
                          border: '1px solid var(--border)',
                          color: 'var(--primary)', fontSize: '11px'
                        }}>
                          http://localhost:8000/api/calendar/callback
                        </code>
                      </li>
                      <li>Copy the <strong style={{ color: 'var(--text-primary)' }}>Client ID</strong> and <strong style={{ color: 'var(--text-primary)' }}>Client Secret</strong></li>
                      <li>
                        Add to your{' '}
                        <code style={{
                          background: 'var(--bg-card)', padding: '2px 6px', borderRadius: '4px',
                          border: '1px solid var(--border)',
                          color: 'var(--primary)', fontSize: '11px'
                        }}>
                          .env
                        </code>
                        {' '}file:
                        <div style={{
                          marginTop: '8px',
                          background: 'var(--bg-card)',
                          border: '1px solid var(--border)',
                          borderRadius: '6px',
                          padding: '10px 12px',
                          fontFamily: "'JetBrains Mono', monospace",
                          fontSize: '11px',
                          color: 'var(--text-primary)',
                          lineHeight: '1.8',
                          userSelect: 'all'
                        }}>
                          GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com<br />
                          GOOGLE_CLIENT_SECRET=GOCSPX-your-secret
                        </div>
                      </li>
                      <li>Restart the backend server — then come back and click <strong style={{ color: 'var(--text-primary)' }}>"Connect Google"</strong></li>
                    </ol>
                    <div style={{ marginTop: '10px', fontSize: '11px', color: 'var(--text-muted)' }}>
                      💡 Also add your Gmail to <strong>"Test users"</strong> in the OAuth consent screen if your app is in development/testing mode.
                    </div>
                  </div>
                )}
              </div>

              {/* ── Option B: iCal Subscription ───────────────────────── */}
              <div style={{
                background: 'var(--bg-card-soft)', border: '1px solid var(--border)',
                borderRadius: '10px', padding: '14px'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary)' }}>
                      Option B: Instant 1-Click Google Calendar Subscription (RFC 5545)
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px', lineHeight: '1.4' }}>
                      Zero OAuth setup required! In Google Calendar, click{' '}
                      <strong style={{ color: 'var(--text-primary)' }}>Other calendars '+' → 'From URL'</strong> and paste this link:
                    </div>
                  </div>
                  <button
                    onClick={handleCopyIcs}
                    style={{
                      padding: '8px 14px', borderRadius: '8px',
                      border: '1px solid var(--border)',
                      background: copiedIcs ? 'rgba(16, 185, 129, 0.15)' : 'var(--bg-card)',
                      color: copiedIcs ? '#059669' : 'var(--text-primary)',
                      fontSize: '12px', fontWeight: '600', cursor: 'pointer', flexShrink: 0
                    }}
                  >
                    {copiedIcs ? '✓ Link Copied!' : '📋 Copy Calendar URL'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div style={{
          borderTop: '1px solid var(--border)',
          paddingTop: '16px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          {activeEmail ? (
            <button
              onClick={handleLogout}
              disabled={loading}
              style={{
                padding: '8px 16px',
                borderRadius: '8px',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                background: 'rgba(239, 68, 68, 0.08)',
                color: '#dc2626',
                fontSize: '12.5px',
                fontWeight: '600',
                cursor: 'pointer'
              }}
            >
              Sign Out of {activeEmail}
            </button>
          ) : <div />}

          <button
            onClick={onClose}
            style={{
              padding: '8px 18px',
              borderRadius: '8px',
              border: '1px solid var(--border)',
              background: 'var(--bg-card-soft)',
              color: 'var(--text-primary)',
              fontSize: '12.5px',
              fontWeight: '500',
              cursor: 'pointer'
            }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
