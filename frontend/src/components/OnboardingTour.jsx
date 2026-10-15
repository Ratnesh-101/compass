import React, { useState } from 'react'

export default function OnboardingTour({
  onVerifyDeadlines,
  onOpenTelemetry,
  onOpenCompass,
  onOpenSeed: _onOpenSeed,
}) {
  const handleOpenCompass = onOpenCompass
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem('compass_tour_dismissed') === '1'
    } catch {
      return false
    }
  })
  const [isCollapsed, setIsCollapsed] = useState(false)

  const handleDismiss = () => {
    setDismissed(true)
    try {
      localStorage.setItem('compass_tour_dismissed', '1')
    } catch {
      /* ignore storage access error */
    }
  }

  const handleReopen = () => {
    setDismissed(false)
    setIsCollapsed(false)
    try {
      localStorage.removeItem('compass_tour_dismissed')
    } catch {
      /* ignore storage access error */
    }
  }

  if (dismissed) {
    return (
      <div style={{ marginBottom: '16px', display: 'flex', justifyContent: 'flex-end' }}>
        <button
          id="btn-reopen-tour"
          onClick={handleReopen}
          style={{
            background: 'var(--guide-close-bg)',
            border: '1px solid var(--guide-close-border)',
            color: 'var(--text-secondary)',
            fontSize: '11.5px',
            fontWeight: '600',
            padding: '5px 12px',
            borderRadius: '20px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            transition: 'all 0.15s ease',
          }}
          onMouseEnter={e => {
            e.currentTarget.style.borderColor = 'var(--brand)'
            e.currentTarget.style.color = 'var(--text-primary)'
          }}
          onMouseLeave={e => {
            e.currentTarget.style.borderColor = 'var(--guide-close-border)'
            e.currentTarget.style.color = 'var(--text-secondary)'
          }}
          title="Re-open Hackathon Judge Tour"
        >
          <span>🧭</span>
          <span>Judge Guide & Architecture</span>
        </button>
      </div>
    )
  }

  return (
    <div
      id="judge-onboarding-tour"
      style={{
        background: 'var(--guide-bg)',
        border: '1px solid var(--guide-border)',
        boxShadow: 'var(--guide-shadow)',
        borderRadius: '16px',
        padding: isCollapsed ? '12px 18px' : '20px 22px',
        marginBottom: '22px',
        position: 'relative',
        backdropFilter: 'blur(10px)',
        transition: 'all 0.2s ease',
      }}
    >
      {/* Header bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '20px' }}>🧭</span>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '14.5px', fontWeight: '800', color: 'var(--text-primary)', letterSpacing: '-0.2px' }}>
                Compass Architecture & Evaluation Guide
              </span>
              <span style={{
                fontSize: '10.5px',
                fontWeight: '700',
                background: 'var(--guide-badge-bg)',
                color: 'var(--guide-badge-text)',
                border: '1px solid var(--guide-badge-border)',
                padding: '2px 8px',
                borderRadius: '12px',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}>
                Nebius x NVIDIA
              </span>
            </div>
            {!isCollapsed && (
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)', margin: '3px 0 0 0' }}>
                Persistent multi-domain copilot combining 3-tier Nemotron MoE, Tavily schedule drift detection, and pgvector HNSW memory.
              </p>
            )}
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            onClick={() => setIsCollapsed(!isCollapsed)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              fontSize: '12px',
              padding: '4px 8px',
              borderRadius: '6px',
            }}
            title={isCollapsed ? 'Expand Guide' : 'Collapse Guide'}
          >
            {isCollapsed ? '▼ Expand' : '▲ Minimize'}
          </button>
          <button
            onClick={handleDismiss}
            style={{
              background: 'var(--guide-close-bg)',
              border: '1px solid var(--guide-close-border)',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              fontSize: '13px',
              width: '24px',
              height: '24px',
              borderRadius: '6px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              lineHeight: 1,
            }}
            title="Dismiss Guide"
          >
            ✕
          </button>
        </div>
      </div>

      {!isCollapsed && (
        <>
          {/* 4 Feature Pillars Grid */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))',
            gap: '12px',
            marginTop: '16px',
            marginBottom: '16px',
          }}>
            {/* Pillar 1: NVIDIA Architecture */}
            <div style={{
              background: 'var(--guide-pillar-bg)',
              border: '1px solid var(--guide-amber-border)',
              borderRadius: '12px',
              padding: '14px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                <span style={{ fontSize: '15px' }}>⚡</span>
                <span style={{ fontSize: '12.5px', fontWeight: '700', color: 'var(--guide-amber-text)' }}>
                  3-Tier NVIDIA MoE
                </span>
              </div>
              <p style={{ fontSize: '11.5px', color: 'var(--text-secondary)', lineHeight: '1.45', margin: 0 }}>
                <strong style={{ color: 'var(--text-primary)', fontWeight: '700' }}>Nemotron-3 Nano</strong> (30B, intent routing) → <strong style={{ color: 'var(--text-primary)', fontWeight: '700' }}>Super</strong> (120B, ReAct planning) → <strong style={{ color: 'var(--text-primary)', fontWeight: '700' }}>Ultra</strong> (550B, cross-domain synthesis) on Nebius Token Factory.
              </p>
            </div>

            {/* Pillar 2: Tavily Drift Detection */}
            <div style={{
              background: 'var(--guide-pillar-bg)',
              border: '1px solid var(--guide-cyan-border)',
              borderRadius: '12px',
              padding: '14px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                <span style={{ fontSize: '15px' }}>🔍</span>
                <span style={{ fontSize: '12.5px', fontWeight: '700', color: 'var(--guide-cyan-text)' }}>
                  Tavily Live Web Drift
                </span>
              </div>
              <p style={{ fontSize: '11.5px', color: 'var(--text-secondary)', lineHeight: '1.45', margin: 0 }}>
                Proactively scrapes official hackathon/coursework portals using Tavily to detect schedule postponements and warn before deadlines slip.
              </p>
            </div>

            {/* Pillar 3: Matryoshka Vector Memory */}
            <div style={{
              background: 'var(--guide-pillar-bg)',
              border: '1px solid var(--guide-green-border)',
              borderRadius: '12px',
              padding: '14px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                <span style={{ fontSize: '15px' }}>🧠</span>
                <span style={{ fontSize: '12.5px', fontWeight: '700', color: 'var(--guide-green-text)' }}>
                  Domain-Isolated Recall
                </span>
              </div>
              <p style={{ fontSize: '11.5px', color: 'var(--text-secondary)', lineHeight: '1.45', margin: 0 }}>
                Neon pgvector HNSW with <strong style={{ color: 'var(--text-primary)', fontWeight: '700' }}>768-dim Matryoshka</strong> embeddings. Keeps hackathon, coursework, and code contexts strictly isolated.
              </p>
            </div>

            {/* Pillar 4: Feasibility & Safety */}
            <div style={{
              background: 'var(--guide-pillar-bg)',
              border: '1px solid var(--guide-purple-border)',
              borderRadius: '12px',
              padding: '14px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                <span style={{ fontSize: '15px' }}>🛡️</span>
                <span style={{ fontSize: '12.5px', fontWeight: '700', color: 'var(--guide-purple-text)' }}>
                  Feasibility & Trust
                </span>
              </div>
              <p style={{ fontSize: '11.5px', color: 'var(--text-secondary)', lineHeight: '1.45', margin: 0 }}>
                Mathematical capacity load calculations flag impossible schedules; epistemic abstention says <em>"I don't know"</em> instead of hallucinating.
              </p>
            </div>
          </div>

          {/* Quick Action Test Buttons */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '10px',
            borderTop: '1px solid var(--guide-divider)',
            paddingTop: '12px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '11px', color: 'var(--text-secondary)', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Try 1-Click Tests:
              </span>

              {onVerifyDeadlines && (
                <button
                  id="btn-tour-verify-tavily"
                  onClick={onVerifyDeadlines}
                  style={{
                    background: 'rgba(56, 189, 248, 0.12)',
                    border: '1px solid var(--guide-cyan-border)',
                    color: 'var(--guide-cyan-text)',
                    padding: '6px 12px',
                    borderRadius: '8px',
                    fontSize: '12px',
                    fontWeight: '700',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '5px',
                    transition: 'all 0.15s ease',
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.background = 'rgba(56, 189, 248, 0.22)'
                    e.currentTarget.style.transform = 'translateY(-1px)'
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.background = 'rgba(56, 189, 248, 0.12)'
                    e.currentTarget.style.transform = 'translateY(0)'
                  }}
                  title="Run proactive Tavily web search against tasks to detect schedule drift"
                >
                  <span>🔍</span>
                  <span>Test Tavily Verification</span>
                </button>
              )}

              {onOpenTelemetry && (
                <button
                  id="btn-tour-open-telemetry"
                  onClick={onOpenTelemetry}
                  style={{
                    background: 'rgba(245, 166, 35, 0.12)',
                    border: '1px solid var(--guide-amber-border)',
                    color: 'var(--guide-amber-text)',
                    padding: '6px 12px',
                    borderRadius: '8px',
                    fontSize: '12px',
                    fontWeight: '700',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '5px',
                    transition: 'all 0.15s ease',
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.background = 'rgba(245, 166, 35, 0.22)'
                    e.currentTarget.style.transform = 'translateY(-1px)'
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.background = 'rgba(245, 166, 35, 0.12)'
                    e.currentTarget.style.transform = 'translateY(0)'
                  }}
                  title="Open live token accounting and GPU inference breakdown"
                >
                  <span>⚡</span>
                  <span>Inspect Nebius Telemetry</span>
                </button>
              )}

              {handleOpenCompass && (
                <button
                  id="btn-tour-open-compass"
                  onClick={() => handleOpenCompass("Synthesize a realistic cross-domain roadmap for this weekend")}
                  style={{
                    background: 'rgba(167, 139, 250, 0.12)',
                    border: '1px solid var(--guide-purple-border)',
                    color: 'var(--guide-purple-text)',
                    padding: '6px 12px',
                    borderRadius: '8px',
                    fontSize: '12px',
                    fontWeight: '700',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '5px',
                    transition: 'all 0.15s ease',
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.background = 'rgba(167, 139, 250, 0.22)'
                    e.currentTarget.style.transform = 'translateY(-1px)'
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.background = 'rgba(167, 139, 250, 0.12)'
                    e.currentTarget.style.transform = 'translateY(0)'
                  }}
                  title="Test Nemotron Ultra cross-domain roadmap synthesis"
                >
                  <span>🧭</span>
                  <span>Compass</span>
                </button>
              )}
            </div>

            <button
              onClick={handleDismiss}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--guide-link)',
                fontSize: '11.5px',
                cursor: 'pointer',
                textDecoration: 'underline',
              }}
            >
              Don't show this again
            </button>
          </div>
        </>
      )}
    </div>
  )
}
