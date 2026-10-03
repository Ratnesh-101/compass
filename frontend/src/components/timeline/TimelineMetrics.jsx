import React from 'react'
import {
  CheckCircle2,
  Clock,
  AlertTriangle,
  BrainCircuit,
} from 'lucide-react'

export default function TimelineMetrics({ metrics }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
        gap: '16px',
        marginBottom: '24px',
      }}
    >
      {/* Metric 1: Daily Progress */}
      <div
        style={{
          background: '#ffffff',
          border: '1px solid #e2e8f0',
          borderRadius: '14px',
          padding: '18px 20px',
          boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <span style={{ fontSize: '12.5px', fontWeight: '600', color: '#64748b' }}>Daily Completion</span>
          <div style={{ width: '28px', height: '28px', borderRadius: '7px', background: '#ecfdf5', color: '#10b981', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <CheckCircle2 size={16} />
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
          <span style={{ fontSize: '24px', fontWeight: '800', color: '#0f172a' }}>{metrics.completed}</span>
          <span style={{ fontSize: '13px', color: '#94a3b8' }}>/ {metrics.total} tasks</span>
        </div>
        {/* Progress Bar */}
        <div style={{ width: '100%', height: '6px', background: '#f1f5f9', borderRadius: '3px', marginTop: '10px', overflow: 'hidden' }}>
          <div
            style={{
              width: `${metrics.progressPct}%`,
              height: '100%',
              background: 'linear-gradient(90deg, #10b981 0%, #059669 100%)',
              borderRadius: '3px',
              transition: 'width 0.4s ease',
            }}
          />
        </div>
        <div style={{ fontSize: '11px', color: '#64748b', marginTop: '6px', fontWeight: '600' }}>
          {metrics.progressPct}% of goal accomplished
        </div>
      </div>

      {/* Metric 2: Scheduled Focus Time */}
      <div
        style={{
          background: '#ffffff',
          border: '1px solid #e2e8f0',
          borderRadius: '14px',
          padding: '18px 20px',
          boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <span style={{ fontSize: '12.5px', fontWeight: '600', color: '#64748b' }}>Scheduled Focus</span>
          <div style={{ width: '28px', height: '28px', borderRadius: '7px', background: '#eff6ff', color: '#3b82f6', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Clock size={16} />
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
          <span style={{ fontSize: '24px', fontWeight: '800', color: '#0f172a' }}>{metrics.focusHours}</span>
          <span style={{ fontSize: '13px', color: '#94a3b8' }}>hours planned</span>
        </div>
        <div style={{ fontSize: '11px', color: '#64748b', marginTop: '12px' }}>
          Distributed across {metrics.open} pending tasks
        </div>
      </div>

      {/* Metric 3: Critical & Impending */}
      <div
        style={{
          background: '#ffffff',
          border: '1px solid #e2e8f0',
          borderRadius: '14px',
          padding: '18px 20px',
          boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <span style={{ fontSize: '12.5px', fontWeight: '600', color: '#64748b' }}>Critical Deadlines</span>
          <div
            style={{
              width: '28px',
              height: '28px',
              borderRadius: '7px',
              background: metrics.urgent > 0 ? '#fef2f2' : '#f8fafc',
              color: metrics.urgent > 0 ? '#ef4444' : '#64748b',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <AlertTriangle size={16} />
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
          <span style={{ fontSize: '24px', fontWeight: '800', color: metrics.urgent > 0 ? '#ef4444' : '#0f172a' }}>
            {metrics.urgent}
          </span>
          <span style={{ fontSize: '13px', color: '#94a3b8' }}>urgent / due soon</span>
        </div>
        <div style={{ fontSize: '11px', color: metrics.overdue > 0 ? '#ef4444' : '#64748b', marginTop: '12px', fontWeight: metrics.overdue > 0 ? '700' : '400' }}>
          {metrics.overdue > 0 ? `⚠️ ${metrics.overdue} task(s) overdue` : 'No overdue items'}
        </div>
      </div>

      {/* Metric 4: Cognitive Workload Guardrail */}
      <div
        style={{
          background: '#ffffff',
          border: '1px solid #e2e8f0',
          borderRadius: '14px',
          padding: '18px 20px',
          boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <span style={{ fontSize: '12.5px', fontWeight: '600', color: '#64748b' }}>Cognitive Guardrail</span>
          <div style={{ width: '28px', height: '28px', borderRadius: '7px', background: '#f5f3ff', color: '#8b5cf6', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <BrainCircuit size={16} />
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
          <span style={{ fontSize: '20px', fontWeight: '800', color: Number(metrics.focusHours) > 8 ? '#f59e0b' : '#10b981' }}>
            {Number(metrics.focusHours) > 8 ? 'High Workload' : 'Optimal Capacity'}
          </span>
        </div>
        <div style={{ fontSize: '11px', color: '#64748b', marginTop: '12px' }}>
          Burnout & schedule collision protection active
        </div>
      </div>
    </div>
  )
}
