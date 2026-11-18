import React from 'react'
import {
  TOUR_HEADING,
  TOUR_SUBLINE,
  TOUR_STEP_LOAD_LABEL,
  TOUR_STEP_FEASIBILITY_LABEL,
  TOUR_STEP_INTERNSHIPS_LABEL,
  TOUR_FEASIBILITY_TEXT,
  TOUR_INTERNSHIPS_TEXT,
  buildSampleWeekMessage,
} from '../utils/tourSample'

// The three tour steps. Each one calls onRun(messageText); the caller opens the chat and sends it.
// The sample-week dates are computed here, at click time, so they are never stale.
export function TourButtons({ onRun, compact = false }) {
  const steps = [
    { id: 'tour-btn-load-week', label: TOUR_STEP_LOAD_LABEL, text: () => buildSampleWeekMessage(new Date()) },
    { id: 'tour-btn-feasibility', label: TOUR_STEP_FEASIBILITY_LABEL, text: () => TOUR_FEASIBILITY_TEXT },
    { id: 'tour-btn-internships', label: TOUR_STEP_INTERNSHIPS_LABEL, text: () => TOUR_INTERNSHIPS_TEXT },
  ]
  return (
    <div
      className="tour-buttons"
      style={{ display: 'flex', flexWrap: 'wrap', gap: compact ? '8px' : '10px' }}
    >
      {steps.map((step, index) => (
        <button
          key={step.id}
          type="button"
          id={step.id}
          onClick={() => onRun && onRun(step.text())}
          className={index === 0 ? 'btn-primary-amber' : 'btn-secondary'}
          style={{
            minHeight: compact ? '36px' : '44px',
            padding: compact ? '0 12px' : '0 16px',
            fontSize: compact ? '12.5px' : '13.5px',
            fontWeight: '600',
            borderRadius: 'var(--radius-btn, 6px)',
            cursor: 'pointer',
            textAlign: 'left',
          }}
        >
          {step.label}
        </button>
      ))}
    </div>
  )
}

export default function TourCard({ onRun }) {
  return (
    <div
      id="dashboard-tour-card"
      className="tour-card"
      role="region"
      aria-label="60-second tour"
      style={{
        marginTop: '16px',
        paddingTop: '16px',
        borderTop: '1px solid var(--border)',
      }}
    >
      <h4 style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)', margin: '0 0 2px 0' }}>
        {TOUR_HEADING}
      </h4>
      <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: '0 0 12px 0' }}>
        {TOUR_SUBLINE}
      </p>
      <TourButtons onRun={onRun} />
    </div>
  )
}
