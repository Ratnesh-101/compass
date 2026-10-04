# Compass — Continuous Deployment (CD) Architecture & Runbook

This document defines the deployment architecture, deployment lifecycle, environment configuration, post-deployment verification, and rollback procedures for **Compass**.

---

## 1. System Deployment Architecture

Compass decouples continuous integration (validation) from continuous deployment (delivery) across native cloud providers:

```text
                            Developer Feature Branch
                                       │
                                  Pull Request
                                       │
                                       ▼
                         ┌───────────────────────────┐
                         │   GitHub Actions (CI)     │
                         │ ├─ Backend lint & tests   │
                         │ ├─ Frontend Vite build    │
                         │ └─ Docker Compose config  │
                         └─────────────┬─────────────┘
                                       │
                                    PASS
                                       │
                                       ▼
                                 Review & Merge
                                       │
                                       ▼
                             ┌───────────────────┐
                             │    main branch    │
                             └─────────┬─────────┘
                                       │
                     ┌─────────────────┴─────────────────┐
                     ▼                                   ▼
        ┌─────────────────────────┐         ┌─────────────────────────┐
        │     Vercel Frontend     │         │      Render Cloud       │
        │ ├─ React 18 / Vite SPA  │         │ ├─ FastAPI Web Service  │
        │ ├─ Automatic Git Deploy │         │ ├─ Dockerfile Build     │
        │ └─ Vercel rewrite/proxy │         │ └─ Automatic Git Deploy │
        └────────────┬────────────┘         └────────────┬────────────┘
                     │                                   │
                     ▼                                   ▼
        Production Frontend                 Production Backend
   https://compass-farmlytics.vercel.app   https://compass-backend-qryu.onrender.com
                     │                                   │
                     │    transparent same-origin proxy  │
                     └───────────────────────────────────┤
                                                         ▼
                                            ┌─────────────────────────┐
                                            │    Neon Serverless DB   │
                                            │ ├─ PostgreSQL 16        │
                                            │ └─ pgvector HNSW 768d   │
                                            └─────────────────────────┘
                                                         │
                                                         ▼
                                            ┌─────────────────────────┐
                                            │ Post-Deploy Verification│
                                            │ scripts/verify_deployment.py
                                            └─────────────────────────┘
```

---

## 2. CI vs. CD Contract

| Stage | Owner | Trigger | Responsibilities | Secrets Scope |
|-------|-------|---------|------------------|---------------|
| **CI (Validation)** | GitHub Actions (`.github/workflows/ci.yml`) | Pull Request or Push to `main` | Validates code correctness: Ruff linting, Pytest test suite with isolated PostgreSQL service container, Frontend production bundle build (`npm run build`), Docker Compose configuration validation (`docker compose config --quiet`). | Mock/CI secrets only (`ci-test-token`). **Zero** production secrets. |
| **CD (Delivery)** | Vercel + Render Provider-Native Git Hooks | Direct merge or push to `main` | Deploys validated code to live production surfaces. Vercel compiles and distributes static assets via Vercel CDN and handles reverse-proxy rewrites; Render builds Docker image and runs FastAPI container. | Production secrets configured securely in provider dashboards. |
| **Verification** | Automation / Operations (`scripts/verify_deployment.py`) | Post-deployment gate | Non-mutating read-only HTTP probes verifying backend `/health`, Neon DB connection, Vercel frontend reachability, and same-origin proxying. | Read-only public endpoints. No credentials required. |

> [!IMPORTANT]
> **No Fake CD Workflows**: GitHub Actions does not execute deployment scripts or push Docker images to registries. Vercel and Render maintain native Git integrations connected to `Ratnesh-101/compass` targeting branch `main`. Merging PRs to `main` targets automated deployment via native provider webhooks (auto-deploy and production branch settings require manual provider dashboard verification).

---

## 3. Platform Configuration

### A. Frontend (Vercel)

- **Production Domain**: `https://compass-farmlytics.vercel.app`
- **Connected Repository**: `Ratnesh-101/compass` (Requires manual dashboard verification)
- **Production Branch**: `main` — requires manual dashboard verification.
- **Auto-deploy**: Not independently verified from the repository. Production currently reflects main commit `30cb1c8`, which is consistent with the intended auto-deploy configuration. Manual Vercel dashboard verification required.
- **Framework Preset**: Vite
- **Root Directory**: `frontend` (or project root with `frontend/vercel.json` / `vercel.json`)
- **Build Command**: `npm run build`
- **Output Directory**: `dist`
- **Node.js Version**: 20.x
- **Reverse Proxy Routing Architecture**:
  The application utilizes a **Vercel rewrite/proxy** configuration defined in `vercel.json` (and `frontend/vercel.json`), routing client API requests transparently to the Render backend:
  ```text
  Vercel frontend
        ↓
  Vercel rewrite/proxy
        ↓
  Render backend
  ```
  Configuration (`vercel.json`):
  ```json
  {
    "rewrites": [
      { "source": "/health", "destination": "https://compass-backend-qryu.onrender.com/health" },
      { "source": "/chat", "destination": "https://compass-backend-qryu.onrender.com/chat" },
      { "source": "/api/:path*", "destination": "https://compass-backend-qryu.onrender.com/api/:path*" }
    ]
  }
  ```
  *Benefit*: Client requests use same-origin relative URLs (`/api/...`), shielding users from CORS issues, ad-blockers (such as Brave Shields), and backend host leakage.

### B. Backend (Render)

- **Production Domain**: `https://compass-backend-qryu.onrender.com`
- **Connected Repository**: `Ratnesh-101/compass` (Requires manual dashboard verification)
- **Production Branch**: `main` — requires manual dashboard verification.
- **Auto-deploy**: Not independently verified from the repository. Production currently reflects main commit `30cb1c8`, which is consistent with the intended auto-deploy configuration. Manual Render dashboard verification required.
- **Service Type**: Web Service (Docker runtime)
- **Dockerfile Path**: `backend/Dockerfile`
- **Docker Context**: Root directory (`.`)
- **Runtime Command**: `uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}`
- **Health Check Path**: `/health` (Expected: HTTP 200, `{"status": "ok", "db_connected": true}`)
- **Commit Tracking**: Automatically reports git short SHA via `RENDER_GIT_COMMIT` in `/health`.

### C. Persistent Storage (Neon PostgreSQL)

- **Host**: Hosted Neon Serverless PostgreSQL (`eu-central-1`)
- **Engine**: PostgreSQL 16 + `pgvector`
- **Features**: Serverless autoscaling, scale-to-zero compute, automatic connection pooling, instant branching.
- **Migration Strategy**: Schema initialized and validated dynamically during application startup lifespan (`backend/memory/db.py`).

---

## 4. Environment Variables Matrix

### Local / Build Configuration (`frontend/.env.production`)

> [!NOTE]
> `frontend/.env.production` is **untracked and gitignored** in `.gitignore`. It is a local/deployment reference file containing only public, non-secret client configuration (`VITE_API_BASE_URL=https://compass-backend-qryu.onrender.com`). It is NOT a repository-tracked file and contains zero secrets.

| Variable | Environment | Purpose | Verification State |
|----------|-------------|---------|-------------------|
| `VITE_API_BASE_URL` | Production / Preview | Target backend base URL if direct calls are needed | Local file: Configured. In Vercel dashboard: Requires manual dashboard verification. In production builds, SPA client defaults to same-origin relative URLs (`''`) routed via `vercel.json` rewrites. |

### Backend (Render Environment Settings)

| Variable | Scope | Description | Verification State |
|----------|-------|-------------|--------------------|
| `ENVIRONMENT` | Backend | Must be `production` to activate fail-closed security assertions. | Requires manual dashboard verification |
| `DATABASE_URL` | Backend | Neon PostgreSQL connection string with SSL required (`sslmode=require`). | Requires manual dashboard verification |
| `AUTH_TOKEN` | Backend | Secret admin/service token for privileged endpoints. In production, default `dev-token` is blocked. | Requires manual dashboard verification |
| `TOKEN_ENCRYPTION_KEY` | Backend | 32-byte cryptographic secret used for encrypting Google OAuth tokens at rest. | Requires manual dashboard verification |
| `NEBIUS_API_KEY` | Backend | Nebius Token Factory API key for Nemotron and Qwen embedding inference. | Requires manual dashboard verification |
| `NEBIUS_BASE_URL` | Backend | Base endpoint for Nebius Token Factory (`https://api.tokenfactory.nebius.com/v1/`). | Repository default configured; dashboard override possible |
| `TAVILY_API_KEY` | Backend | Tavily Web Search API key for real-time web intelligence. | Requires manual dashboard verification |
| `TAVILY_ENABLED` | Backend | Enables Tavily web search tools (`True`). | Repository default configured (`True`) |
| `TAVILY_ABSTAIN_FIRST`| Backend | Enforces memory search before escalating to web queries. | Repository default configured (`True`) |
| `GOOGLE_CLIENT_ID` | Backend | Google Cloud OAuth 2.0 Web Client ID. | Requires manual dashboard verification |
| `GOOGLE_CLIENT_SECRET`| Backend | Google Cloud OAuth 2.0 Web Client Secret. | Requires manual dashboard verification |
| `GOOGLE_REDIRECT_URI` | Backend | OAuth callback redirect URL (`https://compass-farmlytics.vercel.app/api/calendar/callback`). | Repository default configured |
| `CORS_ORIGINS` | Backend | Allowed CORS origins (JSON array or comma-separated). | Repository default configured (`https://compass-farmlytics.vercel.app`) |
| `LOG_LEVEL` | Backend | Application logging verbosity (`INFO`). | Repository default configured (`INFO`); dashboard override possible |

> [!CAUTION]
> Never commit actual production secrets to Git. Secret values are injected exclusively at runtime via provider project settings dashboards.

---

## 5. Post-Deployment Verification

After any merge to `main` or provider redeployment, run the post-deployment smoke verification suite:

```bash
python scripts/verify_deployment.py
```

### Preferred Smoke-Test Principle
The smoke verification script strictly uses the minimum necessary read-only endpoints to validate deployment health without mutating state or leaking operational data.

### Probes Executed:

1. **Backend `/health`**:
   - Status code HTTP 200
   - JSON response contains `status: "ok"`, `version: "0.1.0"`
   - `db_connected: True` (live query to Neon PostgreSQL succeeded)
   - Commit SHA matches GitHub `main` HEAD (`commit: "30cb1c8..."`)
2. **Frontend Dashboard (Vercel)**:
   - Status code HTTP 200
   - React root container `<div id="root">` present
   - Production JS and CSS bundles load successfully
3. **Vercel `/health` Proxy Rewrite**:
   - Status code HTTP 200
   - Proves Vercel rewrite/proxy reaches Render backend transparently without DNS, TLS, or CORS errors
4. **CORS Preflight Probe**:
   - OPTIONS preflight request with `Origin: https://compass-farmlytics.vercel.app`
   - Verifies `Access-Control-Allow-Origin` permits requests from the production frontend origin

> [!NOTE]
> `/api/usage/summary` is deliberately excluded from deployment smoke verification because it exposes operational metrics (total requests, token counts, cost) that are not needed for binary deployment health signaling.

---

## 6. Rollback Procedures

When mitigating a production regression or incident, distinguish between **immediate restoration** and **permanent repository correction**:

```text
Provider rollback
    ↓
Fast restoration of known-good deployment (Immediate, zero build time)

Git revert
    ↓
Permanent repository-level correction
    ↓
CI validation & future deployment
```

> [!IMPORTANT]
> **Primary vs. Secondary Mechanism**: Provider rollback in Vercel and Render dashboards is the **primary** mechanism for rapid production recovery because it instantly restores a known-good build artifact without waiting for CI builds. Git revert is the **secondary / permanent** mechanism to ensure the repository state is corrected for all future merges.
>
> **Do not execute either rollback unless responding to an actual production incident.**

### A. Primary Production Rollback: Provider Dashboards (Instant)

#### 1. Vercel Frontend Rollback (Seconds)
1. Open the [Vercel Project Dashboard](https://vercel.com/dashboard) -> Select **compass-farmlytics**.
2. Navigate to the **Deployments** tab.
3. Locate the last known good deployment (verified by date and commit SHA).
4. Click the three dots (`...`) on that deployment and click **Promote to Production** (or **Redeploy**).
5. Vercel routes immediately switch traffic to the prior build within seconds without rebuilding.

#### 2. Render Backend Rollback (Seconds)
1. Open the [Render Dashboard](https://dashboard.render.com/) -> Select **compass-backend-qryu**.
2. Navigate to the **Events** tab.
3. Locate the previous successful deploy event.
4. Click **Rollback to this deploy**.
5. Render immediately redeploys the previous container build.

---

### B. Secondary Repository-Level Rollback: Git Revert (Permanent Fix)

To permanently correct the codebase after an incident has been stabilized:

#### 1. Reverting a Normal (Non-Merge) Commit
For a standard single-parent commit:
```bash
git checkout main
git pull origin main
git revert <bad-commit-sha>
git push origin main
```

#### 2. Reverting a Merge Commit
When reverting a pull request merge commit, the parent mainline number must be specified using `-m 1` (where 1 indicates the `main` branch parent):
```bash
git checkout main
git pull origin main
git revert -m 1 <bad-merge-commit-sha>
git push origin main
```

> [!WARNING]
> Do NOT use `-m 1` on a normal commit. Git will fail with `error: option `mainline' is only valid with merge commits`. Similarly, running `git revert` on a merge commit without `-m` will fail with `error: commit is a merge but no -m option was given`.

---

### C. Verification After Rollback

Immediately after initiating or completing any rollback, re-run:

```bash
python scripts/verify_deployment.py
```

Verify that all 4 probes pass and that the reported `commit` reflects the restored version.

---

## 7. CD Security & Hardening Controls

- **Minimal CI Permissions**: GitHub Actions workflows specify `permissions: contents: read` explicitly.
- **Fail-Closed Secrets in Production**: If `ENVIRONMENT=production`, `Settings.validate_production_secrets()` asserts that `AUTH_TOKEN` and `TOKEN_ENCRYPTION_KEY` are not set to default development values.
- **Branch Protection**: Production merges require passing CI checks on GitHub. Feature branches and PRs cannot deploy directly to production.
- **SSRF & Metadata Defense**: All outbound agent requests validate destination IPs against private, link-local, loopback, and cloud metadata addresses (including IPv6 and mapped addresses).
- **Same-Origin Proxying**: Vercel rewrite/proxy handles `/api/*` and `/health` routing to Render over secure TLS, preventing CORS misconfigurations from affecting end users.

---

## 8. Known Operational Limitations

1. **Render Free-Tier Sleep Cycle**: On free or hobby plans, Render spins down web services after 15 minutes of inactivity. The first request after a period of dormancy will experience a cold-start delay of 30–50 seconds while the container initializes.
2. **In-Memory Rate Limiting**: Endpoint rate limiting is enforced per-worker in memory. If Render scales horizontally across multiple container instances, rate limits apply per container rather than globally across workers (documented trade-off).
3. **Branch Preview Databases**: Pull requests deploy frontend preview builds on Vercel, but preview backend environments require separate Render services or manual database branch creation via Neon CLI.
