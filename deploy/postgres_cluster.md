# Nebius Managed PostgreSQL Cluster — Production Runbook

> [!IMPORTANT]
> **Production Architecture Decision**: Compass uses **Neon Serverless PostgreSQL** for production database storage. This provides cloud-native scale-to-zero, instant database branching, built-in connection pooling, and operational simplicity (tested end-to-end across our test suite and live application). 
> This runbook is retained as an alternative reference for private VPC-isolated database deployments entirely inside Nebius AI Cloud.

This document details the provisioning, extension configuration, schema migration, and VPC routing for the alternative **Managed PostgreSQL** database instance on Nebius AI Cloud.

---

## 1. Architecture & VPC Topology

```
┌──────────────────────────────────────────────────────────────┐
│                    Nebius VPC (eu-north1)                    │
│                                                              │
│  ┌─────────────────────────┐     ┌─────────────────────────┐ │
│  │   Serverless Endpoint   │────>│   Managed PostgreSQL    │ │
│  │   (FastAPI Backend)     │     │   (pgvector:pg16)       │ │
│  └─────────────────────────┘     └─────────────────────────┘ │
│                │                              │              │
│                ▼                              ▼              │
│  ┌─────────────────────────┐     ┌─────────────────────────┐ │
│  │  Nightly Consolidation  │     │      Internal DNS:      │ │
│  │    Cron (0 2 * * *)     │     │ c-compass-prod.rw.nebius│ │
│  └─────────────────────────┘     └─────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

- **Region**: `eu-north1` (or your target Nebius region)
- **VPC**: `vpc-compass-prod`
- **Subnets**: Private subnets with internal DNS resolution (`subnet-compass-prod-a`)
- **Network Access**: Deny public internet access. Only services within `vpc-compass-prod` holding security group `sg-compass-backend` can access port `5432`.

---

## 2. Cluster Provisioning

### Via Nebius Console or CLI:
```bash
nebius mdb postgresql cluster create \
  --name compass-postgres-prod \
  --environment production \
  --network-name vpc-compass-prod \
  --resource-preset s3-c2-m8 \
  --disk-size 50 \
  --disk-type network-ssd \
  --version 16 \
  --user name=compass_app,password="<STRONG_SECURE_PASSWORD>" \
  --database name=compass
```

---

## 3. Database Initialization & `pgvector` Verification

Connect to the provisioned cluster via the VPC bastion host or Nebius Cloud Shell:

```bash
psql "host=c-compass-prod.rw.nebius.internal port=5432 dbname=compass user=compass_app sslmode=verify-full sslrootcert=/etc/ssl/certs/nebius-root-ca.pem"
```

### Step 3.1: Enable Extensions
Verify that `pgvector` and `uuid-ossp` extensions are installed:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Verify pgvector installation
SELECT * FROM pg_extension WHERE extname = 'vector';
```

### Step 3.2: Run Schema Migration
Apply the production schema defined in `backend/memory/schema.sql`:
```bash
psql "host=c-compass-prod.rw.nebius.internal port=5432 dbname=compass user=compass_app sslmode=verify-full" -f backend/memory/schema.sql
```

### Step 3.3: Verify Tables & HNSW Index
Ensure all 5 tables and the HNSW vector index are active:
```sql
\dt
-- Should list: projects, tasks, memory_chunks, conversations, messages

\di idx_memory_chunks_embedding
-- Index "public.idx_memory_chunks_embedding"
-- Method: hnsw
-- Expression: embedding vector_cosine_ops
```

> [!NOTE]
> `memory_chunks.embedding` is configured as `VECTOR(768)`. When generating embeddings via `Qwen/Qwen3-Embedding-8B`, pass the Matryoshka dimension parameter `dimensions=768` so vectors fit within PostgreSQL's 2,000-dimension HNSW limit.

---

## 4. Connection Strings & Secret Management

### Production Connection String Format:
```text
postgresql://compass_app:<PASSWORD>@c-compass-prod.rw.nebius.internal:5432/compass?sslmode=verify-full&sslrootcert=/etc/ssl/certs/nebius-root-ca.pem
```

### Security & Secret Storage:
1. **Never commit `.env.production` to Git.**
   - `.env.production` is strictly excluded in `.gitignore`.
2. **Store in Nebius Secret Manager**:
   ```bash
   nebius lockbox secret create \
     --name compass-db-credentials \
     --payload '[{"key": "DATABASE_URL", "text_value": "postgresql://compass_app:SECRET@c-compass-prod.rw.nebius.internal:5432/compass"}]'
   ```
3. **Reference in Deployments**:
   - `deploy/serverless_endpoint.yaml` and `deploy/serverless_job.yaml` mount this secret directly into the `DATABASE_URL` environment variable.

---

## 5. Maintenance & Troubleshooting

| Issue | Root Cause | Solution |
| :--- | :--- | :--- |
| `connection refused` | Service outside VPC / Security group | Check that `ServerlessEndpoint` specifies `vpc-compass-prod` subnet. |
| `hnsw index dimensions exceed 2000` | Full 4096-dim vector stored | Ensure embedding call specifies `dimensions=768` (Matryoshka). |
| `SSL certificate verify failed` | Missing root CA certificate | Ensure `/etc/ssl/certs/nebius-root-ca.pem` is bundled or use `sslmode=require`. |
