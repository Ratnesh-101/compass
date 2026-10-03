import React from 'react'
import {
  Plus,
  Sparkles,
  Cpu,
  ShieldCheck,
} from 'lucide-react'

export default function TimelineHeader({
  today,
  onOpenTelemetry,
  onVerifyAll,
  verifyingDeadlines,
  onSeedJudgePersona,
  seedingPersona,
  seedSuccess,
  onOpenNewTask,
  verificationSummary,
  onClearVerificationSummary,
}) {
  return (
    <>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          marginBottom: '24px',
          gap: '16px',
          flexWrap: 'wrap',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <h2
              style={{
                fontSize: '26px',
                fontWeight: '800',
                color: '#0f172a',
                letterSpacing: '-0.5px',
                margin: 0,
              }}
            >
              Executive Dashboard
            </h2>
            <span
              style={{
                fontSize: '12px',
                fontWeight: '600',
                color: '#64748b',
                background: '#e2e8f0',
                padding: '2px 8px',
                borderRadius: '6px',
              }}
            >
              {today}
            </span>
          </div>
          <p style={{ fontSize: '13.5px', color: '#64748b', marginTop: '4px', marginBottom: 0 }}>
            Unified view of cross-domain deadlines, focus allocation, and cognitive guardrails.
          </p>
        </div>

        {/* Global Executive Actions */}
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
          {onOpenTelemetry && (
            <button
              id="btn-open-telemetry"
              type="button"
              onClick={onOpenTelemetry}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '7px',
                background: '#ffffff',
                color: '#0f172a',
                border: '1px solid #e2e8f0',
                padding: '9px 14px',
                borderRadius: '10px',
                fontSize: '13px',
                fontWeight: '600',
                cursor: 'pointer',
                boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.borderColor = '#cbd5e1'
                e.currentTarget.style.background = '#f8fafc'
              }}
              onMouseLeave={e => {
                e.currentTarget.style.borderColor = '#e2e8f0'
                e.currentTarget.style.background = '#ffffff'
              }}
              title="Inspect live Nebius Token Factory token consumption and NVIDIA MoE hierarchy"
            >
              <Cpu size={15} color="#f59e0b" />
              <span>Nebius Telemetry</span>
            </button>
          )}

          <button
            id="btn-verify-all-deadlines"
            type="button"
            onClick={onVerifyAll}
            disabled={verifyingDeadlines}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '7px',
              background: '#ffffff',
              color: '#0284c7',
              border: '1px solid #e0f2fe',
              padding: '9px 14px',
              borderRadius: '10px',
              fontSize: '13px',
              fontWeight: '600',
              cursor: verifyingDeadlines ? 'wait' : 'pointer',
              boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
              transition: 'all 0.15s ease',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.background = '#f0f9ff'
              e.currentTarget.style.borderColor = '#bae6fd'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.background = '#ffffff'
              e.currentTarget.style.borderColor = '#e0f2fe'
            }}
            title="Verify deadlines against authoritative sources"
          >
            <ShieldCheck size={15} color="#0284c7" />
            <span>{verifyingDeadlines ? 'Verifying...' : 'Verify Deadlines'}</span>
          </button>

          <button
            id="btn-seed-judge-persona"
            type="button"
            onClick={onSeedJudgePersona}
            disabled={seedingPersona}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '7px',
              background: seedSuccess ? '#ecfdf5' : '#ffffff',
              color: seedSuccess ? '#059669' : '#4f46e5',
              border: `1px solid ${seedSuccess ? '#a7f3d0' : '#e0e7ff'}`,
              padding: '9px 14px',
              borderRadius: '10px',
              fontSize: '13px',
              fontWeight: '600',
              cursor: seedingPersona ? 'wait' : 'pointer',
              boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
              transition: 'all 0.15s ease',
            }}
            onMouseEnter={e => {
              if (!seedSuccess) e.currentTarget.style.background = '#eef2ff'
            }}
            onMouseLeave={e => {
              if (!seedSuccess) e.currentTarget.style.background = '#ffffff'
            }}
            title="Load judge demonstration persona with multi-domain tasks & semantic memory"
          >
            <Sparkles size={15} color={seedSuccess ? '#059669' : '#4f46e5'} />
            <span>{seedingPersona ? 'Loading...' : seedSuccess ? 'Persona Loaded!' : 'Demo Persona'}</span>
          </button>

          <button
            id="btn-add-deadline"
            onClick={onOpenNewTask}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              background: 'linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)',
              color: '#ffffff',
              border: 'none',
              padding: '9px 16px',
              borderRadius: '10px',
              fontSize: '13.5px',
              fontWeight: '600',
              cursor: 'pointer',
              boxShadow: '0 4px 12px rgba(37, 99, 235, 0.25)',
              transition: 'all 0.15s ease',
              flexShrink: 0,
            }}
            onMouseEnter={e => {
              e.currentTarget.style.transform = 'translateY(-1px)'
              e.currentTarget.style.boxShadow = '0 6px 16px rgba(37, 99, 235, 0.35)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.transform = 'translateY(0)'
              e.currentTarget.style.boxShadow = '0 4px 12px rgba(37, 99, 235, 0.25)'
            }}
          >
            <Plus size={16} strokeWidth={2.5} />
            <span>New Task</span>
          </button>
        </div>
      </div>

      {/* Verification Feedback Banner */}
      {verificationSummary && (
        <div
          style={{
            background: verificationSummary.error ? '#fef2f2' : '#f0f9ff',
            border: `1px solid ${verificationSummary.error ? '#fecaca' : '#bae6fd'}`,
            color: verificationSummary.error ? '#991b1b' : '#0369a1',
            padding: '12px 18px',
            borderRadius: '12px',
            marginBottom: '22px',
            fontSize: '13px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '12px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <ShieldCheck size={18} color={verificationSummary.error ? '#dc2626' : '#0284c7'} />
            <div>
              <span style={{ fontWeight: '700' }}>
                {verificationSummary.error ? 'Verification Alert: ' : 'Verification Complete: '}
              </span>
              <span>
                {verificationSummary.error
                  ? verificationSummary.error
                  : `Checked ${verificationSummary.total} active task(s). ${
                      verificationSummary.drift > 0
                        ? `⚠️ ${verificationSummary.drift} schedule drift(s) detected via live search!`
                        : 'All deadlines confirmed matching authoritative sources.'
                    }`}
              </span>
            </div>
          </div>
          <button
            onClick={onClearVerificationSummary}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#64748b',
              cursor: 'pointer',
              fontSize: '14px',
              padding: '4px',
            }}
          >
            ✕
          </button>
        </div>
      )}
    </>
  )
}
