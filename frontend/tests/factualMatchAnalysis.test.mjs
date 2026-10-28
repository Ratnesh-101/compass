import test from 'node:test'
import assert from 'node:assert/strict'

/**
 * Pure match analysis logic identical to ApplicationWorkspaceModal.jsx
 */
export function computeMatchAnalysis({ opportunityRequirements, jobAnalysisRequirements, userSkills = [] }) {
  const rawRequiredSkills = opportunityRequirements || []
  const requiredSkills = rawRequiredSkills.length > 0
    ? rawRequiredSkills
    : (jobAnalysisRequirements || [])

  const matchedSkills = requiredSkills.filter(s =>
    userSkills.some(us => us.toLowerCase() === s.toLowerCase())
  )
  const missingSkills = requiredSkills.filter(s =>
    !userSkills.some(us => us.toLowerCase() === s.toLowerCase())
  )

  let displayState = 'has_gaps'
  if (requiredSkills.length === 0) {
    displayState = 'general_qualification'
  } else if (missingSkills.length === 0) {
    displayState = 'all_verified'
  }

  return {
    requiredSkills,
    matchedSkills,
    missingSkills,
    displayState,
  }
}

test('Factual Match Analysis: Zero required skills resolves to general_qualification state', () => {
  const res = computeMatchAnalysis({
    opportunityRequirements: [],
    jobAnalysisRequirements: [],
    userSkills: ['Python', 'SQL'],
  })

  assert.equal(res.displayState, 'general_qualification')
  assert.equal(res.requiredSkills.length, 0)
  assert.equal(res.matchedSkills.length, 0)
  assert.equal(res.missingSkills.length, 0)
})

test('Factual Match Analysis: Fallback to jobAnalysis.required_skills when opportunity requirements empty', () => {
  const res = computeMatchAnalysis({
    opportunityRequirements: null,
    jobAnalysisRequirements: ['Product Strategy', 'User Empathy', 'SQL'],
    userSkills: ['sql'],
  })

  assert.equal(res.requiredSkills.length, 3)
  assert.equal(res.matchedSkills.length, 1)
  assert.equal(res.missingSkills.length, 2)
  assert.equal(res.displayState, 'has_gaps')
})

test('Factual Match Analysis: 100% matched skills resolves to all_verified state with zero false warnings', () => {
  const res = computeMatchAnalysis({
    opportunityRequirements: ['Python', 'Docker'],
    jobAnalysisRequirements: [],
    userSkills: ['python', 'docker', 'kubernetes'],
  })

  assert.equal(res.displayState, 'all_verified')
  assert.equal(res.matchedSkills.length, 2)
  assert.equal(res.missingSkills.length, 0)
})

test('Factual Match Analysis: Partial matches correctly identifies gaps', () => {
  const res = computeMatchAnalysis({
    opportunityRequirements: ['TypeScript', 'GraphQL', 'React'],
    jobAnalysisRequirements: [],
    userSkills: ['react'],
  })

  assert.equal(res.displayState, 'has_gaps')
  assert.equal(res.matchedSkills.length, 1)
  assert.equal(res.missingSkills.length, 2)
  assert.deepEqual(res.missingSkills, ['TypeScript', 'GraphQL'])
})
