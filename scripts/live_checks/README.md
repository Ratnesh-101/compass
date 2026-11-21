# Live checks

Browser checks (Playwright) that run against the **deployed** Compass site, the same way a judge or first-time visitor would use it.
They are not part of CI: they hit the live app and backend, so they spend a few guest and Tavily credits and can be slow while the free
Render backend wakes up (20 to 45 s). Each script prints `PASS` / `FAIL` lines and saves screenshots to the current directory.

## Setup

- Node 18 or newer.
- `playwright-core` with a Chromium build installed (`npx playwright install chromium`). If `playwright-core` is not resolvable from where
  you run the script, point to it: `PLAYWRIGHT_CORE=/path/to/node_modules/playwright-core`.
- Scripts that upload a resume need `RESUME_FILE=/path/to/resume.docx` (a `.docx`, `.pdf` or `.txt` resume). Use your own file; do not commit it.

## Scripts

| Script | What it checks | Arguments |
|---|---|---|
| `regression_check.mjs` | 23-step pass over the first screen, tour, chat, planner basics, schedule, career, About, phone layout and JS errors. Run this after every deploy. | `node regression_check.mjs <baseUrl> <outDir> [local\|live]` (`live` adds the AI-dependent checks) |
| `judge_demo_check.mjs` | The judge demo path: Planner approval gate and reject/re-plan (task data unchanged), URL ingest paused for approval, share link opens for a stranger. | none |
| `judge_polish_check.mjs` | About page model names, the tour chat title in Recent chats, plain wording on Planner approval cards. | none |
| `resume_flow_check.mjs` | Resume upload, matches, Prepare Application, mark as submitted. Needs `RESUME_FILE`. | none |
| `career_workspace_check.mjs` | A cleared personal deadline stays cleared after reopening; "I submitted this externally" moves it to Applied with a follow-up date. Needs `RESUME_FILE`. | none |
| `stream_smoothness_check.mjs` | Samples how an answer's text grows while it streams (median and largest step per frame). | `node stream_smoothness_check.mjs <url> <label>` |

The skeleton / slow-network check is a separate Python script: `scripts/skeleton_acceptance.py --url <site>` (needs `playwright` for Python).

## Notes

- These checks depend on live data. `career_workspace_check.mjs` opens the listing titled "GSoC 2026 Open Source Contributor"; if that
  listing is gone, change `TITLE` at the top. The model can also vary its plan, so the Planner approval step does not always appear:
  re-run before treating one miss as a bug.
- Several scripts have the site URL near the top (`https://compass-farmlytics.vercel.app/`); change it to test another deployment.
