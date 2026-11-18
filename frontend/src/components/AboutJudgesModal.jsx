import React from 'react'
import Dialog from './Dialog'
import Logo from './Logo'
import { X, Cpu, Database, ExternalLink, ShieldCheck } from 'lucide-react'

export default function AboutJudgesModal({
  isOpen,
  onClose,
  usageStats,
  backendStatus = 'Online',
  onOpenTelemetry,
  onVerifyDeadlines,
  isOnline = true,
}) {
  if (!isOpen) return null

  return (
    <Dialog
      onClose={onClose}
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(15, 23, 42, 0.5)',
        backdropFilter: 'blur(3px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1150,
        padding: '20px',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--bg-card)',
          borderRadius: 'var(--radius-card, 8px)',
          border: '1px solid var(--border)',
          width: '100%',
          maxWidth: '580px',
          maxHeight: '90vh',
          overflowY: 'auto',
          padding: '24px',
          boxShadow: 'var(--shadow-lg)',
          color: 'var(--text-primary)',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '18px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Logo size={28} alt="Compass Logo" />
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <h3 style={{ fontSize: '18px', fontWeight: '700', margin: 0, color: 'var(--text-primary)' }}>
                  About Compass
                </h3>
                <span
                  style={{
                    fontSize: '11px',
                    fontWeight: '600',
                    background: 'rgba(245, 166, 35, 0.12)',
                    color: 'var(--text-primary)',
                    border: '1px solid rgba(245, 166, 35, 0.3)',
                    padding: '2px 8px',
                    borderRadius: '4px',
                  }}
                >
                  Hackathon Evaluation Guide
                </span>
              </div>
              <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', margin: '2px 0 0' }}>
                Architecture, Nebius AI telemetry, and evaluation resources for judges.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="btn-touch-target"
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--text-secondary)',
              padding: '4px',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* 3-Tier Architecture Highlights */}
        <div
          style={{
            background: 'var(--bg-card-soft)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            padding: '14px 16px',
            marginBottom: '16px',
          }}
        >
          <div style={{ fontSize: '12px', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-secondary)', marginBottom: '8px' }}>
            System Architecture (NVIDIA & Nebius MoE)
          </div>
          <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
            <li>
              <strong>Router & Fast Classifier:</strong> Nemotron-3 8B MoE for intent classification and low-latency planning.
            </li>
            <li>
              <strong>Specialist & Synthesis:</strong> Llama-3.1-70B / 405B MoE via Nebius Token Factory for complex multi-domain reasoning.
            </li>
            <li>
              <strong>Hybrid Memory:</strong> PostgreSQL 16 with pgvector HNSW indexing (768-dim embeddings) for cross-session semantic recall.
            </li>
          </ul>
        </div>

        {/* Live Telemetry Overview */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '16px' }}>
          <div style={{ padding: '12px', background: 'var(--bg-card-soft)', borderRadius: '6px', border: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
              <Database size={14} style={{ color: 'var(--accent)' }} />
              <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Database</span>
            </div>
            <div style={{ fontSize: '13.5px', fontWeight: '600', color: 'var(--text-primary)' }}>
              {backendStatus || (isOnline ? 'Online' : 'Connecting')}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              PostgreSQL 16 · pgvector
            </div>
          </div>

          <div style={{ padding: '12px', background: 'var(--bg-card-soft)', borderRadius: '6px', border: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
              <Cpu size={14} style={{ color: 'var(--accent)' }} />
              <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Nebius Telemetry</span>
            </div>
            <div style={{ fontSize: '13.5px', fontWeight: '600', color: 'var(--text-primary)' }}>
              {usageStats?.total_requests ?? 0} calls · ${Number(usageStats?.total_estimated_cost_usd ?? 0).toFixed(5)}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              Nebius Token Factory
            </div>
          </div>
        </div>

        {/* Quick Actions for Judges */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '16px' }}>
          {onOpenTelemetry && (
            <button
              type="button"
              id="about-btn-open-telemetry"
              onClick={() => {
                onClose()
                onOpenTelemetry()
              }}
              className="btn-secondary"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '10px 14px',
                fontSize: '13px',
                minHeight: '44px',
                fontWeight: '600',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Cpu size={16} style={{ color: 'var(--accent)' }} />
                <span>Inspect Nebius Token Consumption</span>
              </div>
              <ExternalLink size={14} style={{ color: 'var(--text-secondary)' }} />
            </button>
          )}

          {onVerifyDeadlines && (
            <button
              type="button"
              id="about-btn-verify-tavily"
              onClick={() => {
                onClose()
                onVerifyDeadlines()
              }}
              className="btn-secondary"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '10px 14px',
                fontSize: '13px',
                minHeight: '44px',
                fontWeight: '600',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <ShieldCheck size={16} style={{ color: '#10b981' }} />
                <span>Verify deadlines with Tavily web search</span>
              </div>
              <ExternalLink size={14} style={{ color: 'var(--text-secondary)' }} />
            </button>
          )}
        </div>

        {/* Footer */}
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <button
            type="button"
            onClick={onClose}
            className="btn-secondary"
            style={{ minHeight: '36px', padding: '0 16px', fontSize: '13px' }}
          >
            Close
          </button>
        </div>
      </div>
    </Dialog>
  )
}
