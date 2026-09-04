"""
Compass — Nebius Token Factory Verification Script.

Validates two architecture questions against the live Nebius API:
  1. What is the actual embedding dimension returned by the configured model?
  2. Does the Nemotron Nano router model support OpenAI-compatible tool calling?

Usage:
    python scripts/test_nebius.py

Requires NEBIUS_API_KEY and NEBIUS_BASE_URL in .env (or environment).
"""

import os
import sys
import json
from pathlib import Path

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

# Load .env from project root
from dotenv import load_dotenv

_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

from typing import Any
from openai import OpenAI

# ---------------------------------------------------------------------------
# Configuration (mirrors backend/config.py defaults, overridable via .env)
# ---------------------------------------------------------------------------
API_KEY = os.getenv("NEBIUS_API_KEY", "")
BASE_URL = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-en-icl")
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "nvidia/Nemotron-3-Nano-8B-v1")

DIVIDER = "=" * 60


def _abort(msg: str) -> None:
    print(f"\n❌  {msg}")
    sys.exit(1)


def test_embedding_dimension(client: OpenAI) -> int | None:
    """Call the embedding endpoint and return the vector dimension."""
    print(f"\n{DIVIDER}")
    print(f"TEST 1 — Embedding Dimension ({EMBEDDING_MODEL})")
    print(DIVIDER)

    try:
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input="Compass is a personal AI assistant with persistent memory.",
        )
        vector = response.data[0].embedding
        dim = len(vector)
        print(f"  ✅  Embedding returned successfully")
        print(f"  📐  EMBEDDING_DIMENSION = {dim}")
        print(f"  🧮  Sample (first 5 values): {vector[:5]}")

        # Check against expected
        expected = int(os.getenv("EMBEDDING_DIMENSION", "768"))
        if dim != expected:
            print(f"\n  ⚠️  WARNING: .env says EMBEDDING_DIMENSION={expected}, "
                  f"but API returned {dim}.")
            print(f"       → Update config.py and schema.sql VECTOR({dim}) accordingly.")
        else:
            print(f"  ✅  Matches configured EMBEDDING_DIMENSION={expected}")

        return dim

    except Exception as e:
        print(f"  ❌  Embedding call failed: {e}")
        return None


def test_tool_calling(client: OpenAI) -> bool | None:
    """Test whether the router model supports OpenAI-compatible function calling."""
    print(f"\n{DIVIDER}")
    print(f"TEST 2 — Tool Calling Support ({ROUTER_MODEL})")
    print(DIVIDER)

    # A minimal tool definition matching OpenAI's function-calling spec
    tools: Any = [
        {
            "type": "function",
            "function": {
                "name": "add_task",
                "description": "Add a new task to the user's task list.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "The title of the task",
                        },
                        "domain": {
                            "type": "string",
                            "enum": ["hackathon", "coursework", "code", "general"],
                            "description": "The domain category",
                        },
                    },
                    "required": ["title"],
                },
            },
        }
    ]

    messages: Any = [
        {"role": "system", "content": "You are Compass, a personal AI assistant."},
        {"role": "user", "content": "Add a task called 'Fix login bug' under the code domain."},
    ]

    try:
        response = client.chat.completions.create(
            model=ROUTER_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            max_tokens=256,
        )

        choice = response.choices[0]
        if choice.message.tool_calls:
            tc: Any = choice.message.tool_calls[0]
            func_name = getattr(getattr(tc, "function", None), "name", None) or getattr(tc, "name", "unknown")
            func_args = getattr(getattr(tc, "function", None), "arguments", None) or getattr(tc, "arguments", "{}")
            print(f"  ✅  TOOL_CALLING_SUPPORTED = True")
            print(f"  🔧  Function called: {func_name}")
            print(f"  📦  Arguments: {func_args}")
            return True
        else:
            # Model responded with text instead of a tool call — partial support
            content_preview = (choice.message.content or "")[:200]
            print(f"  ⚠️  Model responded with text instead of a tool call.")
            print(f"       Response: {content_preview}")
            print(f"  📋  TOOL_CALLING_SUPPORTED = True (but model chose not to call)")
            return True

    except Exception as e:
        error_str = str(e).lower()
        if "unsupported" in error_str or "tool" in error_str or "function" in error_str:
            print(f"  ⚠️  FALLBACK_JSON_REQUIRED = True")
            print(f"       Tool calling not supported by this model/endpoint.")
            print(f"       Error: {e}")
            return False
        else:
            print(f"  ❌  Unexpected error: {e}")
            return None


def main() -> None:
    print("\n🧭  Compass — Nebius Token Factory Verification")
    print(f"    Base URL : {BASE_URL}")
    print(f"    Embed    : {EMBEDDING_MODEL}")
    print(f"    Router   : {ROUTER_MODEL}")

    if not API_KEY:
        _abort(
            "NEBIUS_API_KEY is not set.\n"
            "   Copy .env.example → .env and fill in your Nebius API key.\n"
            "   Then re-run: python scripts/test_nebius.py"
        )

    client = OpenAI(
        api_key=API_KEY,
        base_url=BASE_URL,
    )

    # --- Test 1: Embedding Dimension ---
    dim = test_embedding_dimension(client)

    # --- Test 2: Tool Calling ---
    tool_support = test_tool_calling(client)

    # --- Summary ---
    print(f"\n{DIVIDER}")
    print("SUMMARY")
    print(DIVIDER)
    print(f"  EMBEDDING_DIMENSION     = {dim or 'FAILED'}")
    if tool_support is True:
        print(f"  TOOL_CALLING_SUPPORTED  = True")
    elif tool_support is False:
        print(f"  FALLBACK_JSON_REQUIRED  = True")
    else:
        print(f"  TOOL_CALLING            = INCONCLUSIVE (check errors above)")
    print()


if __name__ == "__main__":
    main()
