# Task S3 - CLI hardening

- Worktree: <local path>   Branch: agent/sonnet/cli-hardening   Base: d0a4c31
- Test script: bash "<local path>" "<worktree with forward slashes>" [pytest args]
- May edit: cli/assistant_cli.py, cli/pyproject.toml, tests/test_cli.py (and NEW tests/test_cli_hardening.py if you prefer a separate file).
- Must NOT edit: anything else. Do NOT look at or modify the user's own checkout; their old uncommitted CLI edits are superseded except the one hunk below.

## Context
The CLI is a Typer app (`cli/assistant_cli.py`). A static review of an OLDER version reported the issues below. `origin/main` has changed since, so FIRST read the
current file and `tests/test_cli.py`, confirm each issue is still real (reproduce with a failing test), and skip any that is already fixed (say so in the report).

## Issues to fix (if still present)
1. Exit codes: `typer.Exit` (a `click.exceptions.Exit`, subclass of RuntimeError) is swallowed by broad `except Exception:` blocks around `_post`/`_get`
   calls (admin consolidate, agent-undo, agent-activity/runs, triage, recap, and similar), so failures print an empty "Failed: " and exit 0. Re-raise
   `typer.Exit`/`click.exceptions.Exit` (and `SystemExit`/`KeyboardInterrupt`) before handling other exceptions; real HTTP 4xx/5xx and connection errors must exit non-zero
   with a useful message. A JSON reply with a non-ok status from agent-undo must exit non-zero.
2. `_stream_chat`: a mid-stream `httpx.ReadTimeout`/`RemoteProtocolError` after tokens were already printed must NOT trigger a second POST to `/chat`
   (it can run "add task X" twice). Only fall back when no output has been produced yet. A non-200 stream response (e.g. 401/403) should surface the error once, not retry.
   An SSE `type: error` event must make the command exit non-zero.
3. `_post` must handle `httpx.TimeoutException` and other `httpx.HTTPError`s like `_get` does (friendly message, non-zero exit), not a traceback.
4. Token default: today the token falls back to the literal "dev-token", which makes the "AUTH_TOKEN not set" guard unreachable and sends `dev-token` to whatever URL is
   configured. DECISION (from the user): keep `dev-token` as the fallback ONLY when the API base is localhost/127.0.0.1/::1; for any other host require an explicit token
   (env `AUTH_TOKEN`, saved config, or `compass login`) and exit non-zero with a clear message. Also: a repo-local `.env` loaded by `load_dotenv()` must not silently override a
   token saved by `compass login`/`compass config`; define and document the precedence (saved config > env > dev fallback for localhost) and test it.
5. Config file: tokens are written as `auth_token = "{token}"` without TOML escaping (a `"` or `\` corrupts the file, and `load_config` then silently falls back to defaults).
   Write properly escaped TOML, warn (do not silently ignore) when the config file cannot be parsed, create it with owner-only permissions (0600; best effort on Windows),
   and make `compass config` display not reveal the token length (print a fixed mask or last 4 chars).
6. Query params in `agent-runs` / `agent-activity` (and any other hand-built URL) must be URL-encoded (use httpx params).
7. `sys.stdout.reconfigure(...)` at import must be guarded with `hasattr` so wrappers without `reconfigure` do not crash import.
8. `recap`: a non-200 on the conversation list must not be reported as "No conversation found" (surface the HTTP error, exit non-zero). `compass add` must not print
   success when the backend response indicates failure.
9. Carry over this one hunk from the user's old local edit into `cli/pyproject.toml` (it is NOT in origin/main yet):
   ```
   [tool.setuptools]
   package-dir = {"cli" = "."}
   packages = ["cli", "cli.commands"]
   ```
   Verify against the current file that it is consistent with `compass = "cli.assistant_cli:app"` and that `cli/commands` exists; if the packages list would break an
   editable install, say so instead of applying it blindly.

## Tests
Use `typer.testing.CliRunner` and monkeypatched httpx (follow the existing style in tests/test_cli.py). One test per fixed issue; each must fail on the old code.
Keep `tests/test_cli.py::test_cli_backend_integration_tenant_isolation` as is (it needs a local dev server and is deselected in verification).

Acceptance: full suite green (with that one deselect), red-check shown, gates clean.
