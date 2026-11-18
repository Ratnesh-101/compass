import React from 'react'
import { getValidationCardState } from '../../utils/careerUiHelpers'

export default function ValidationReportCard({ validationReport }) {
  if (!validationReport) return null

  const cardState = getValidationCardState(validationReport)
  const { isNotEnoughData, isConsistent, isIncomplete, missingFields, warnings } = cardState

  const badgeConfig = isIncomplete
    ? {
        label: cardState.incompleteLabel,
        bg: '#fee2e2',
        color: '#991b1b',
        tooltip: 'The resume is missing required details, so it cannot be treated as ready.',
        explanation: cardState.hint,
      }
    : isNotEnoughData
    ? {
        label: 'NOT ENOUGH DATA',
        bg: '#fef3c7',
        color: '#92400e',
        tooltip: 'Your saved resume does not have enough detail (summary, skills, projects, experience) to check this copy against it.',
        explanation: 'Add a few more details to your resume so this copy can be checked.',
      }
    : isConsistent
    ? {
        label: 'CONSISTENT WITH MASTER',
        bg: '#dcfce7',
        color: '#166534',
        tooltip: 'Every skill, degree and project on this copy is also on your saved resume.',
        explanation: 'Checked against your saved resume: everything here is something you told us.',
      }
    : {
        label: 'INCONSISTENT WITH MASTER',
        bg: '#fee2e2',
        color: '#991b1b',
        tooltip: 'This copy has skills or claims that are not on your saved resume.',
        explanation: 'Some items here are not on your saved resume. Remove them or add them to My resume.',
      }

  return (
    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '12px', padding: '18px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
        <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: 'var(--text-primary)' }}>
          Resume check
        </h3>
        <span
          title={badgeConfig.tooltip}
          style={{
            fontSize: '12px',
            fontWeight: '800',
            padding: '4px 10px',
            borderRadius: '12px',
            background: badgeConfig.bg,
            color: badgeConfig.color,
            cursor: 'help',
          }}
        >
          {badgeConfig.label}
        </span>
      </div>

      <p style={{ margin: '0 0 12px 0', fontSize: '12px', color: 'var(--text-secondary)' }}>
        ℹ️ {badgeConfig.explanation}
      </p>

      {/* Missing required fields */}
      {missingFields.length > 0 && (
        <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '8px', padding: '10px 12px', marginBottom: '12px' }}>
          <div style={{ fontWeight: '700', color: '#991b1b', fontSize: '12px', marginBottom: '4px' }}>
            Missing fields:
          </div>
          <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '12px', color: '#b91c1c' }}>
            {missingFields.map((field, idx) => (
              <li key={idx}>{field}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Warnings */}
      {warnings.length > 0 && (
        <div style={{ background: '#fffbeb', border: '1px solid #fde68a', borderRadius: '8px', padding: '10px 12px', marginBottom: '12px' }}>
          <div style={{ fontWeight: '700', color: '#92400e', fontSize: '12px', marginBottom: '4px' }}>
            Warnings:
          </div>
          <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '12px', color: '#92400e' }}>
            {warnings.map((warning, idx) => (
              <li key={idx}>{warning}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Unsupported Claims Alert */}
      {validationReport.unsupported_claims && validationReport.unsupported_claims.length > 0 && (
        <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '8px', padding: '10px 12px', marginBottom: '12px' }}>
          <div style={{ fontWeight: '700', color: '#991b1b', fontSize: '12px', marginBottom: '4px' }}>
            ⚠️ Blocked Unsupported Claims:
          </div>
          <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '12px', color: '#b91c1c' }}>
            {validationReport.unsupported_claims.map((claim, idx) => (
              <li key={idx}>{claim}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Tailored alignments */}
      {validationReport.tailored_alignments && validationReport.tailored_alignments.length > 0 && (
        <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: '8px', padding: '10px 12px', marginBottom: '12px' }}>
          <div style={{ fontWeight: '700', color: '#166534', fontSize: '12px', marginBottom: '4px' }}>
            🎯 Verified Role Alignments:
          </div>
          <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '12px', color: '#15803d' }}>
            {validationReport.tailored_alignments.map((align, idx) => (
              <li key={idx}>{align}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Passed checklist */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {(validationReport.passed_checks || []).map((p, idx) => (
          <div key={idx} style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ color: '#10b981' }}>✓</span> {p}
          </div>
        ))}
      </div>
    </div>
  )
}
