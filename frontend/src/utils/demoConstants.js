// Demo persona constants and task classification helpers
// Used to ensure dummy tasks never leak or persist after reload

export const DEMO_TASK_TITLES = new Set([
  // Legacy seed titles (commit c34cf7b)
  '36-hour Hackathon Sprint: Final Demo Build',
  'CS 61C Lab 4: RISC-V Pipeline Synthesis',
  'Record 3-minute Devpost demo video',
  'Nebius Buildathon Phase 2 Submission',
  'Deploy Compass backend to Nebius Serverless Endpoints',
  'CS 61C Midterm Review: Cache Hierarchies & Virtual Memory',
  'Embeddings truncation and Matryoshka dimension verification',
  // Current Judge Persona seed titles
  'Nebius Buildathon Phase 1 Submission',
  'CS 61C Homework 3: RISC-V Calling Conventions',
  'Configure Production SSL & CORS Headers',
  'Organize Hackathon Pitch Slide Deck',
  'Final Paper: Scalable Hybrid Search in Pgvector',
  'General Quarterly Study Group Retrospective',
  'Distributed Systems Term Project Checkpoint',
  'Nebius Cloud GPU Quota and Capacity Review',
  'Explore Quantized GGUF Local Inference Fallback',
  'Organize CS 61C Discussion Group Study Guide',
  'CS 61C Logisim ALU Control Hazard Resolution',
  'Enterprise SSO Integration for University Directory',
  'Initial Compass Schema Migration to Neon Postgres',
  'Set Up GitHub Actions CI Pipeline for Lint and Pytest',
])

/**
 * Returns true if the task is a demo / dummy task from the Judge Persona or legacy seeding.
 * Strict check against is_demo flags, tags, trusted_event_url, and known demo titles.
 */
export function isDemoTask(t) {
  if (!t) return false
  // If explicitly flagged as not demo by the backend/user session, preserve it
  if (t.is_demo === false) return false
  if (t.is_demo === true || t.is_fallback) return true
  const taskIdStr = String(t.id || '')
  if (taskIdStr.startsWith('demo-') || taskIdStr.startsWith('mock-') || taskIdStr.startsWith('sim-')) {
    return true
  }
  // Only the seeder's own URL scheme counts; arbitrary URLs such as https://demoday.example.com do not
  const trustedUrl = String(t.trusted_event_url || '').toLowerCase()
  if (trustedUrl.startsWith('compass://demo-persona/')) return true
  if (t.notes && String(t.notes).toLowerCase().includes('demo persona')) return true
  if (t.title && DEMO_TASK_TITLES.has(String(t.title).trim())) return true
  return false
}
