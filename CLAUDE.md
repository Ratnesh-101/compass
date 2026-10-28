# Compass — Claude Code notes

The shared contract for all agents is in [`AGENTS.md`](AGENTS.md); follow it. Coordination protocol,
ledger and task template are in `docs/agent-coordination/`.

Quick facts:
- Backend: FastAPI + asyncpg (`backend/`), tests in `tests/` (run only against local Postgres; see AGENTS.md).
- Frontend: React + Vite (`frontend/`), tests are Node's built-in runner: `node --test tests/*.test.mjs`.
- `main` auto-deploys to Vercel and Render. Never push to it; merges are the user's call.
- The user's checkout may hold uncommitted work. Do agent work in separate git worktrees.
