import React from 'react'
import { Target, Sparkles, Clock, Star, ClipboardList } from 'lucide-react'

export default function RadarOverviewCards({
  stats,
  profile,
  onOpenProfile,
  onSelectTab,
}) {
  const missingProfileFields = profile?.missing_fields_limiting_eligibility || []
  const hasIncompleteProfile = missingProfileFields.includes('academic_year') || missingProfileFields.includes('grad_year')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginBottom: '24px' }}>
      {hasIncompleteProfile && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '12px 18px',
            borderRadius: 'var(--radius-card, 8px)',
            background: 'rgba(245, 166, 35, 0.12)',
            border: '1px solid rgba(245, 166, 35, 0.35)',
            color: 'var(--text-primary)',
            flexWrap: 'wrap',
            gap: '12px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Target size={18} strokeWidth={1.8} color="var(--brand)" />
            <div>
              <div style={{ fontWeight: 600, fontSize: '14px' }}>
                Complete your Candidate Profile in Resume Studio
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                Update your academic qualifications, skills, and graduation cohort in Resume Studio to unlock deterministic eligibility.
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onOpenProfile}
            style={{
              padding: '6px 14px',
              borderRadius: 'var(--radius-btn, 6px)',
              background: 'var(--brand)',
              color: 'var(--accent-text, #1b1a17)',
              border: 'none',
              fontWeight: 600,
              fontSize: '12px',
              cursor: 'pointer',
            }}
          >
            Manage in Resume Studio
          </button>
        </div>
      )}

      {/* 5-Column Responsive Metric Highlights */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '12px',
        }}
      >
        {/* 1. Verified Active */}
        <div
          onClick={() => onSelectTab('open')}
          style={{
            padding: '16px',
            borderRadius: 'var(--radius-card, 8px)',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            boxShadow: 'var(--shadow-sm)',
            cursor: 'pointer',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Active Now
            </span>
            <span
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                background: '#10b981',
                boxShadow: '0 0 6px rgba(16, 185, 129, 0.6)',
              }}
            />
          </div>
          <div style={{ fontSize: '26px', fontWeight: 700, color: 'var(--text-primary)' }}>
            {stats?.open_count ?? 0}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Open confirmed opportunities
          </div>
        </div>

        {/* 2. Eligible Strong Matches */}
        <div
          onClick={() => onSelectTab('recommended')}
          style={{
            padding: '16px',
            borderRadius: 'var(--radius-card, 8px)',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            boxShadow: 'var(--shadow-sm)',
            cursor: 'pointer',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Eligible Matches
            </span>
            <Sparkles size={16} strokeWidth={1.8} color="var(--brand)" />
          </div>
          <div style={{ fontSize: '26px', fontWeight: 700, color: 'var(--text-primary)' }}>
            {stats?.strong_matches_count ?? 0}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Satisfies your academic criteria
          </div>
        </div>

        {/* 3. Opening Soon */}
        <div
          onClick={() => onSelectTab('upcoming')}
          style={{
            padding: '16px',
            borderRadius: 'var(--radius-card, 8px)',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            boxShadow: 'var(--shadow-sm)',
            cursor: 'pointer',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Opening Soon
            </span>
            <Clock size={16} strokeWidth={1.8} color="#3b82f6" />
          </div>
          <div style={{ fontSize: '26px', fontWeight: 700, color: 'var(--text-primary)' }}>
            {stats?.opening_soon_count ?? 0}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Upcoming & cycle forecasts
          </div>
        </div>

        {/* 4. Watchlist */}
        <div
          onClick={() => onSelectTab('watchlist')}
          style={{
            padding: '16px',
            borderRadius: 'var(--radius-card, 8px)',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            boxShadow: 'var(--shadow-sm)',
            cursor: 'pointer',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Watchlist
            </span>
            <Star size={16} strokeWidth={1.8} color="var(--accent, #f5a623)" />
          </div>
          <div style={{ fontSize: '26px', fontWeight: 700, color: 'var(--text-primary)' }}>
            {stats?.saved_count ?? 0}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Saved opportunities
          </div>
        </div>

        {/* 5. In Progress Applications */}
        <div
          onClick={() => onSelectTab('applications')}
          style={{
            padding: '16px',
            borderRadius: 'var(--radius-card, 8px)',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            boxShadow: 'var(--shadow-sm)',
            cursor: 'pointer',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Applications
            </span>
            <ClipboardList size={16} strokeWidth={1.8} color="#db2777" />
          </div>
          <div style={{ fontSize: '26px', fontWeight: 700, color: 'var(--text-primary)' }}>
            {stats?.applications_in_progress_count ?? 0}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Active tracker pipeline
          </div>
        </div>
      </div>
    </div>
  )
}
