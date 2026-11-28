import React from 'react'
import { friendlyLoadError } from '../../utils/careerLoadHonesty'

/** Shared "could not load" panel with a Retry button. Never shows raw statuses. */
export default function LoadErrorPanel({ error, onRetry, what = 'resume' }) {
  const online = typeof navigator === 'undefined' ? true : navigator.onLine
  return (
    <div
      role="alert"
      style={{ margin: '24px auto', maxWidth: '560px', display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap', justifyContent: 'center', padding: '14px 18px', borderRadius: '10px', background: '#fee2e2', color: '#991b1b', fontSize: '13px' }}
    >
      <span>{friendlyLoadError(error, online, what)}</span>
      <button
        type="button"
        onClick={onRetry}
        style={{ padding: '3px 10px', borderRadius: '6px', border: '1px solid #fecaca', background: '#ffffff', color: '#991b1b', fontWeight: 700, fontSize: '12px', cursor: 'pointer' }}
      >
        Retry
      </button>
    </div>
  )
}
