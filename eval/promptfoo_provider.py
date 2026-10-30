"""promptfoo provider: runs Compass's offline intake routing for each test message."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("NEBIUS_API_KEY", "mock-nebius-key")
os.environ.setdefault("ENVIRONMENT", "test")


def call_api(prompt, options, context):
    from eval.intake_cases import decide

    return {"output": asyncio.run(decide(prompt))}
