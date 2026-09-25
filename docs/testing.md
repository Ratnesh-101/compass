# Compass — Testing Guide

## Running Tests

Tests require a PostgreSQL database with `pgvector`. Set `TEST_DATABASE_URL` (or `DATABASE_URL`) to a test database instance before running — the test suite **will not run against an unspecified database** (this is a safety guard to prevent accidental production mutations).

```bash
# Run full suite
python -m pytest tests -v

# Run a specific test file
python -m pytest tests/test_agent.py -v

# Run with a test database override
TEST_DATABASE_URL="postgresql://..." python -m pytest tests -v
```

**Verified result** (pytest --collect-only, Python 3.12, against Neon test branch):

```
195 tests collected
```

The CI pipeline (`ci.yml`) also runs `--collect-only` before the full run to surface this count in every CI log.

## Test Coverage by Area

| File | Tests | Coverage |
|------|------:|---------|
| `test_agent.py` | 26 | ReAct loop, SSE events, confirm/reject/undo, audit log |
| `test_security_hardening.py` | 28 | Fail-closed secrets, SSRF defenses, IPv6 filtering, IDOR isolation, proposal integrity, replay protection |
| `test_tavily.py` | 20 | Web search, ingest, injection defense, deadline drift |
| `test_api_endpoints.py` | 15 | Health, auth, CORS preflight, error handling, rate limiting |
| `test_gap_closures.py` | 15 | Rate limits, auth enforcement, cost tracking, domain filtering |
| `test_scheduling.py` | 13 | Slot allocation, prerequisites, ICS, conflict detection |
| `test_reactive_scheduling.py` | 11 | Slipped task re-planning, reactive rescheduling |
| `test_feasibility.py` | 10 | Capacity arithmetic, triage, negotiation caps |
| `test_cli.py` | 9 | CLI commands, REPL, config, triage |
| `test_specialist_agent.py` | 8 | Domain specialists, delegation, read-only enforcement |
| `test_direct_tasks.py` | 9 | Task CRUD, status transitions, duplicate prevention, same-name shift/confirm |
| `test_google_calendar_auth.py` | 6 | OAuth flow, token encryption, account isolation |
| `test_chat_gate.py` | 5 | Chat confirmation gate behavior and state checks |
| `test_specialist_confirm_gate.py` | 4 | Mutation gate via specialist path |
| `test_user_isolation.py` | 4 | Per-user workspace isolation |
| `test_demo_flow.py` | 4 | End-to-end multi-domain demo flow |
| `test_conversations_memory.py` | 3 | Pin, archive, rename, multi-turn |
| `test_structured_memory.py` | 3 | pgvector migration, HNSW indexing |
| `test_multi_turn.py` | 1 | Multi-turn conversational memory |
| `test_streaming.py` | 1 | SSE token streaming |
| **Total** | **195** | **20 test suites** |

## Test Infrastructure

Tests use `pytest-asyncio` and connect to a real PostgreSQL instance. The test suite does not mock the database layer — it runs real SQL queries against a test database and validates actual behavior.

**Key test fixtures** (see `tests/conftest.py`):
- `pool` — live database connection pool
- `client` — httpx AsyncClient wired to the FastAPI app
- Database is seeded and torn down per-test where necessary

## Notable Test Behaviors

- **Agent tests** (`test_agent.py`) mock Nebius Token Factory responses to avoid live API costs while testing the full ReAct loop execution, SSE event format, and confirmation gate behavior.
- **Tavily tests** (`test_tavily.py`) include both mocked unit tests (for injection defense, credit tracking) and integration-style tests for the confirm-gate and undo flow.
- **Calendar tests** (`test_google_calendar_auth.py`) mock Google OAuth but test the actual token encryption, storage, and account isolation logic.
- **Feasibility tests** (`test_feasibility.py`) are fully deterministic — the feasibility engine performs arithmetic, not LLM inference, so these tests run without any mocking.
