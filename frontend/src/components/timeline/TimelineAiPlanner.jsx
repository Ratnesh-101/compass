import React from 'react'
import {
  Sparkles,
  ArrowRight,
} from 'lucide-react'

export default function TimelineAiPlanner({
  quickAiPrompt,
  setQuickAiPrompt,
  onQuickAiSubmit,
  onOpenCompass,
}) {
  const handleOpenCompass = onOpenCompass
  return (
    <div
      style={{
        background: 'linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%)',
        borderRadius: '14px',
        padding: '20px 24px',
        marginBottom: '26px',
        color: '#ffffff',
        boxShadow: '0 4px 20px rgba(30, 27, 75, 0.15)',
        border: '1px solid rgba(99, 102, 241, 0.25)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', flexWrap: 'wrap', gap: '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'rgba(99, 102, 241, 0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Sparkles size={17} color="#c7d2fe" />
          </div>
          <div>
            <div style={{ fontSize: '15px', fontWeight: '700', letterSpacing: '-0.2px' }}>
              Compass
            </div>
            <div style={{ fontSize: '12px', color: '#94a3b8' }}>
              Powered by NVIDIA Nemotron MoE on Nebius Token Factory
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            type="button"
            onClick={() => handleOpenCompass && handleOpenCompass('Propose an optimized conflict-free schedule for today')}
            style={{
              fontSize: '12px',
              fontWeight: '600',
              padding: '6px 12px',
              borderRadius: '8px',
              background: 'rgba(255, 255, 255, 0.08)',
              border: '1px solid rgba(255, 255, 255, 0.15)',
              color: '#e2e8f0',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.16)'}
            onMouseLeave={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.08)'}
          >
            🗓️ Auto-Schedule
          </button>
          <button
            type="button"
            onClick={() => handleOpenCompass && handleOpenCompass('Detect any cognitive overload or overlapping deadlines')}
            style={{
              fontSize: '12px',
              fontWeight: '600',
              padding: '6px 12px',
              borderRadius: '8px',
              background: 'rgba(255, 255, 255, 0.08)',
              border: '1px solid rgba(255, 255, 255, 0.15)',
              color: '#e2e8f0',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.16)'}
            onMouseLeave={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.08)'}
          >
            🧠 Analyze Conflicts
          </button>
        </div>
      </div>

      {/* Quick Prompt Input */}
      <form onSubmit={onQuickAiSubmit} style={{ display: 'flex', gap: '10px' }}>
        <input
          type="text"
          placeholder="Ask Compass: e.g. 'Break down my next milestone into 3 focused tasks'..."
          value={quickAiPrompt}
          onChange={e => setQuickAiPrompt(e.target.value)}
          style={{
            flex: 1,
            background: 'rgba(255, 255, 255, 0.06)',
            border: '1px solid rgba(255, 255, 255, 0.18)',
            borderRadius: '10px',
            padding: '10px 14px',
            fontSize: '13.5px',
            color: '#ffffff',
            outline: 'none',
            transition: 'all 0.15s ease',
          }}
          onFocus={e => (e.target.style.borderColor = '#818cf8')}
          onBlur={e => (e.target.style.borderColor = 'rgba(255, 255, 255, 0.18)')}
        />
        <button
          type="submit"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            background: '#6366f1',
            border: 'none',
            borderRadius: '10px',
            padding: '0 18px',
            fontSize: '13px',
            fontWeight: '700',
            color: '#ffffff',
            cursor: 'pointer',
            boxShadow: '0 2px 10px rgba(99, 102, 241, 0.4)',
            transition: 'all 0.15s ease',
          }}
          onMouseEnter={e => (e.currentTarget.style.background = '#4f46e5')}
          onMouseLeave={e => (e.currentTarget.style.background = '#6366f1')}
        >
          <span>Plan</span>
          <ArrowRight size={14} />
        </button>
      </form>
    </div>
  )
}
