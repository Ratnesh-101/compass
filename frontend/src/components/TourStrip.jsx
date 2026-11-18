import React from 'react'
import { TourButtons } from './TourCard'
import { TOUR_HEADING } from '../utils/tourSample'

// Shown above the chat when the app is opened with ?tour=1.
export default function TourStrip({ onRun, onClose }) {
  return (
    <div
      id="chat-tour-strip"
      role="region"
      aria-label="60-second tour"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '10px',
        padding: '10px 16px',
        background: 'var(--bg-card)',
        borderBottom: '1px solid var(--border)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '10px', minWidth: 0 }}>
        <strong style={{ fontSize: '13px', color: 'var(--text-primary)' }}>{TOUR_HEADING}</strong>
        <TourButtons onRun={onRun} compact />
      </div>
      <button
        type="button"
        onClick={onClose}
        className="btn-secondary"
        aria-label="Hide the tour"
        style={{ minHeight: '32px', padding: '0 10px', fontSize: '12px' }}
      >
        Hide
      </button>
    </div>
  )
}
