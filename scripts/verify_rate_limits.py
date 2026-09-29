import asyncio
import sys
import logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.disable(logging.CRITICAL)

from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from backend.main import app, _rate_store, _agent_rate_store

async def main():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        routes_to_test = [
            {
                "name": "/api/agent/run",
                "limit": 10,
                "total_to_send": 20,  # 2x stated limit
                "ip": "198.51.100.10",
                "payload": {"goal": "test rate limiting on agent run"},
                "patch_target": "backend.agent.run_agent_workflow",
                "mock_return": None,  # handled via async generator
            },
            {
                "name": "/api/chat",
                "limit": 30,
                "total_to_send": 60,  # 2x stated limit
                "ip": "198.51.100.20",
                "payload": {"message": "test rate limiting on chat"},
                "patch_target": "backend.orchestrator.handle_message",
                "mock_return": {"response": "pong", "conversation_id": "test-c", "skill_used": "chat", "routing_latency_ms": 12},
            },
            {
                "name": "/api/log",
                "limit": 30,
                "total_to_send": 60,  # 2x stated limit
                "ip": "198.51.100.30",
                "payload": {"content": "test memory entry", "domain": "code"},
                "patch_target": "backend.services.embeddings.get_embedding",
                "mock_return": [0.0] * 768,
            },
            {
                "name": "/api/chat/stream",
                "limit": 30,
                "total_to_send": 60,  # 2x stated limit
                "ip": "198.51.100.40",
                "payload": {"message": "test streaming rate limit"},
                "patch_target": "openai.AsyncOpenAI",
                "mock_return": None,
            },
        ]

        print("=" * 80)
        print("COMPASS RATE LIMIT VERIFICATION: 4 PUBLIC ROUTES HIT AT 2x STATED LIMIT")
        print("=" * 80)

        for route in routes_to_test:
            path = route["name"]
            limit = route["limit"]
            total = route["total_to_send"]
            ip = route["ip"]
            headers = {"X-Forwarded-For": ip}

            # Clear any past state for this test IP
            if ip in _rate_store:
                del _rate_store[ip]
            if ip in _agent_rate_store:
                del _agent_rate_store[ip]

            statuses = []
            first_429_resp = None

            # Patch underlying LLM/network call to keep test pure and fast
            if path == "/api/agent/run":
                async def mock_agent_gen(*args, **kwargs):
                    from backend.agent import AgentStep
                    yield AgentStep(type="think", content="mock step", step_number=1)
                with patch("backend.agent.run_agent", side_effect=mock_agent_gen), \
                     patch("backend.agent.count_active_agent_runs", new_callable=AsyncMock) as m_active:
                    m_active.return_value = 0
                    for i in range(total):
                        r = await client.post(path, json=route["payload"], headers=headers)
                        statuses.append(r.status_code)
                        if r.status_code == 429 and first_429_resp is None:
                            first_429_resp = r
            elif path == "/api/chat":
                with patch("backend.orchestrator.handle_message", new_callable=AsyncMock) as m:
                    m.return_value = route["mock_return"]
                    for i in range(total):
                        r = await client.post(path, json=route["payload"], headers=headers)
                        statuses.append(r.status_code)
                        if r.status_code == 429 and first_429_resp is None:
                            first_429_resp = r
            elif path == "/api/log":
                with patch("backend.services.embeddings.get_embedding", new_callable=AsyncMock) as m_emb, \
                     patch("backend.main.get_pool", new_callable=AsyncMock) as m_pool:
                    m_emb.return_value = route["mock_return"]
                    mock_conn = AsyncMock()
                    mock_conn.fetchrow.return_value = {"id": 1, "domain": "code", "project_id": None, "content": "t", "source": "api_log", "tags": [], "created_at": "2026-09-17T00:00:00"}
                    mock_cm = AsyncMock()
                    mock_cm.__aenter__.return_value = mock_conn
                    mock_cm.__aexit__.return_value = None
                    m_pool.return_value.acquire.return_value = mock_cm
                    for i in range(total):
                        r = await client.post(path, json=route["payload"], headers=headers)
                        statuses.append(r.status_code)
                        if r.status_code == 429 and first_429_resp is None:
                            first_429_resp = r
            elif path == "/api/chat/stream":
                from backend.config import get_settings
                with patch("backend.orchestrator.handle_message", new_callable=AsyncMock) as m_hm, \
                     patch.object(get_settings(), "NEBIUS_API_KEY", ""):
                    m_hm.return_value = {"response": "streamed fallback", "conversation_id": "c1", "skill_used": "chat"}
                    for i in range(total):
                        r = await client.post(path, json=route["payload"], headers=headers)
                        statuses.append(r.status_code)
                        if r.status_code == 429 and first_429_resp is None:
                            first_429_resp = r

            print(f"\n[ROUTE] {path}")
            print(f"  Stated Limit: {limit} req/min | Total Requests Sent: {total} (2x limit)")
            print(f"  Client IP (X-Forwarded-For): {ip}")
            print(f"  Success (non-429) count: {len([s for s in statuses if s != 429])}")
            print(f"  Blocked (HTTP 429) count: {statuses.count(429)}")
            if first_429_resp:
                print(f"  First 429 triggered at request #: {statuses.index(429) + 1}")
                print(f"  Status Code: {first_429_resp.status_code}")
                print(f"  Retry-After Header: {first_429_resp.headers.get('retry-after')}s")
                print(f"  Response Body: {first_429_resp.text}")
            else:
                print(f"  ERROR: No 429 received!")

if __name__ == "__main__":
    asyncio.run(main())
