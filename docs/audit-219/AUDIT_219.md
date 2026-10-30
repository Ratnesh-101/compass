# Audit Report: PR #219 (`feat/chat-intelligence`)

**Auditor:** Antigravity / Gemini 3.8 Flash  
**Target Branch:** `feat/chat-intelligence` (PR #219)  
**Date:** October 30, 2026  
**Scope:** `backend/services/task_intent.py`, `task_intake.py`, `task_intake_parse.py`, `task_intake_llm.py`, `task_time.py`, `chat_idempotency.py`, `intent_gate.py`, `eval/intake_cases.py`, `promptfooconfig.yaml`, hooks in `orchestrator.py`, `chat_stream.py`, `router_helpers.py`, and frontend middleware/intake components.

---

## 1. Executive Summary & Defect Table

A comprehensive security, reliability, and correctness audit of PR #219 was conducted. The PR introduces valuable natural-language task intake improvements (pasted tables/lists preview, idempotency tracking via client request IDs, and user timezone resolution). However, the audit revealed **10 confirmed defects** across intent classification, ReDoS vulnerability, transaction atomicity, timezone handling, and security fallback configurations.

| ID | Severity | File : Line | One-Line Summary | Failing Test Name |
|---|---|---|---|---|
| **BUG-01** | **CRITICAL** | [`backend/services/task_intent.py:43-47`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/task_intent.py#L43-L47) | Catastrophic polynomial backtracking in `_CREATION_PHRASE` regex (`12,698 ms` on 50k chars) | `test_creation_phrase_regex_redos_under_100ms` |
| **BUG-02** | **CRITICAL** | [`backend/orchestrator.py:760-800`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/orchestrator.py#L760-L800), [`backend/services/chat_idempotency.py:177-185`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/chat_idempotency.py#L177-L185) | Non-atomic transaction: `tasks` committed before `chat_request_log`; retry fails with duplicate error | `test_non_atomic_transaction_between_task_and_request_log_creates_duplicate_on_retry` |
| **BUG-03** | **HIGH** | [`backend/services/task_intent.py:75-81`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/task_intent.py#L75-L81), [`backend/router_helpers.py:130-156`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/router_helpers.py#L130-L156) | Past-tense inquiries ("Did you remind me...") classified as command; mutates DB and creates task | `test_did_you_remind_me_question_creates_no_task` |
| **BUG-04** | **HIGH** | [`backend/services/task_intent.py:100-110`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/task_intent.py#L100-L110), [`backend/router_helpers.py:1220-1224`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/router_helpers.py#L1220-L1224) | Opinion/advice queries ("Should I add a task for the demo?") extract title and create tasks | `test_should_i_add_task_opinion_question_creates_no_task` |
| **BUG-05** | **HIGH** | [`backend/services/chat_idempotency.py:33-38`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/chat_idempotency.py#L33-L38), [`backend/services/chat_idempotency.py:152-158`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/chat_idempotency.py#L152-L158) | Oversized `request_id` (>64 chars / 1 MB) silently bypasses idempotency without error | `test_oversized_request_id_silently_bypasses_idempotency` |
| **BUG-06** | **HIGH** | [`backend/services/task_time.py:66-72`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/task_time.py#L66-L72) | DST Spring-Forward gap (America/New_York 02:30) silently shifts scheduled instant by +1 hr to 03:30 EDT | `test_dst_spring_forward_gap_preserves_local_clock_time` |
| **BUG-07** | **HIGH** | [`backend/config.py:61`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/config.py#L61) | Hardcoded 36-character HMAC fallback secret in `backend/config.py` allows forging proxy edge signatures | `test_backend_config_has_no_hardcoded_fallback_edge_hmac_secret` |
| **BUG-08** | **MEDIUM** | [`backend/services/task_intent.py:75-82`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/task_intent.py#L75-L82), [`backend/router_helpers.py:790-820`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/router_helpers.py#L790-L820) | Hinglish capability questions ("kya tum add task kar sakte ho?") extract Hindi words as task titles | `test_hinglish_capability_question_creates_no_task` |
| **BUG-09** | **MEDIUM** | [`backend/services/task_time.py:104-113`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/task_time.py#L104-L113) | `format_due_label` leaks unvalidated raw timezone string (e.g. `(Mars/Phobos)` or 10 KB string) into UI label | `test_format_due_label_with_invalid_timezone_uses_utc_in_label` |
| **BUG-10** | **MEDIUM** | [`frontend/src/api/chatApi.js:27-35`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/frontend/src/api/chatApi.js#L27-L35) | `sendQueryToAssistant` omits `requestId`, disabling idempotency for all non-streaming chat callers | `sendQueryToAssistant omits request_id` |

---

## 2. Detailed Findings by Area

### Question 1: Question vs Command Adversarial Evaluation

A battery of **69 adversarial chat messages** was evaluated across 11 distinct categories (mixed English/Hinglish, typos, emoji, very long texts, dates only, markdown tables, CSV, numbered lists with 21+ items, nested bullets, quoted speech, and subtle questions/commands).

#### Tabulation of False Positives & False Negatives

| Message | Category | Expected | Actual Outcome | Status | Root Cause |
|---|---|---|---|---|---|
| `"Did you remind me to take medicine yesterday?"` | Merely mention "remind me" inside question | `no_task` | `task:Take medicine` | **FALSE POSITIVE** | `_PRONOUN_LEAD` matches "Did you", but `_POLITE_PREFIX` does not strip it. `strict_command_title` extracts "Take medicine", `title_problem` passes, classified as `COMMAND`. |
| `"Do you think I should add a task to study?"` | Subtle opinion question | `no_task` | `task:Study` | **FALSE POSITIVE** | Interrogative opinion query treated as concrete command; "Study" extracted as title. |
| `"Should I add a task for the demo?"` | Advice question | `no_task` | `task:The demo` | **FALSE POSITIVE** | "Should I" interrogative classified as `COMMAND`; "The demo" extracted as title. |
| `"kya tum add task kar sakte ho?"` | Hinglish capability ask | `no_task` | `task:Kar sakte ho` | **FALSE POSITIVE** | Non-English interrogative lead bypasses `_PRONOUN_LEAD`; Hindi words "Kar sakte ho" extracted as task title. |
| `"kya tum add task kar sakte ho"` | Hinglish capability ask without `?` | `no_task` | `task:Kar sakte ho` | **FALSE POSITIVE** | Not recognized as question; extracts "Kar sakte ho" as title. |
| `'He told me "remind me to call mom tomorrow" during lunch'` | Quoted conversation | `no_task` | `task:Remind me to call mom` | **FALSE POSITIVE** | Regexes inspect unescaped quoted substrings in conversational chatter. |
| `'Can you explain why the command "add task buy milk tomorrow" created a task?'` | Meta inquiry | `no_task` | `task:Add task buy milk` | **FALSE POSITIVE** | Discussion of command inside quotes classified as `COMMAND`. |
| `'I was reading a tutorial that said "create a task for your team" every morning.'` | Quoted imperative | `no_task` | `task:Create a task for your team` | **FALSE POSITIVE** | Tutorial quote triggers task creation. |
| `"ad task buy milk tomorow"` | Typo (`ad`) | `task` | `no_task` | **FALSE NEGATIVE** | Strict word matching fails on common typo. |
| `"craete task submit report by friday"` | Typo (`craete`) | `task` | `no_task` | **FALSE NEGATIVE** | Strict word matching fails on transposed characters. |
| `"shedule task demo for monday"` | Typo (`shedule`) | `task` | `no_task` | **FALSE NEGATIVE** | Strict word matching fails on missing 'c'. |
| `"remind mee to call mom at 5pm"` | Typo (`mee`) | `task` | `no_task` | **FALSE NEGATIVE** | `remind me to` phrase requires exact single 'e'. |
| `"can u add a taks to review PR?"` | Typo (`u`, `taks`) | `task` | `no_task` | **FALSE NEGATIVE** | `taks` not recognized as creation noun. |
| `"add taks finish slides"` | Typo (`taks`) | `task` | `no_task` | **FALSE NEGATIVE** | Unrecognized typo noun. |
| `"create a tsak: write tests"` | Typo (`tsak`) | `task` | `no_task` | **FALSE NEGATIVE** | Unrecognized typo noun. |
| `"mujhe remind kar dena to call mom tomorrow"` | Hinglish command | `task` | `no_task` | **FALSE NEGATIVE** | Hinglish imperative verbs (`kar dena`) not in router keywords. |
| `"ek task add kar do: buy groceries"` | Hinglish command | `task` | `no_task` | **FALSE NEGATIVE** | Hinglish imperative prefix. |
| `"yeh task list me daal do please: finish thesis"` | Hinglish command | `task` | `no_task` | **FALSE NEGATIVE** | Hinglish imperative phrase. |
| `"please remind me ki assign submit karna hai kal"` | Hinglish command | `task` | `no_task` | **FALSE NEGATIVE** | Conjunction `ki` causes parser to fail title extraction. |
| `"Would you mind creating a deadline for project demo on Friday?"` | Polite question command | `task` | `no_task` | **FALSE NEGATIVE** | `_POLITE_PREFIX` does not cover "would you mind creating", so extraction returns empty title and blocks. |

---

### Question 2: Timezone Handling & DST Edge Cases

1. **DST Spring-Forward Gap (`America/New_York` 2026-03-08 02:30)**:
   - **Result: Wrong Instant Stored (BUG-06)**.
   - On March 8, 2026, clocks jump from 02:00:00 EST directly to 03:00:00 EDT in New York. 02:30 does not exist.
   - `combine_local(date(2026, 3, 8), time(2, 30), "America/New_York")` converts using standard time offset UTC-5 to `2026-03-08 07:30:00+00:00`.
   - When converted back to `America/New_York` time via `.astimezone(ZoneInfo("America/New_York"))`, it resolves to **`03:30:00 EDT`**.
   - The task is silently stored for 1 hour later than requested without warning the user.

2. **DST Fall-Back Overlap (`America/New_York` 2026-11-01 01:30)**:
   - **Result: Ambiguous instant resolved to fold 0**.
   - 01:30 AM occurs twice (first in EDT UTC-4 = 05:30 UTC, then in EST UTC-5 = 06:30 UTC).
   - Python `datetime.combine` defaults to `fold=0` (`2026-11-01 05:30:00+00:00`). This is deterministic, though no clarification or timezone indicator is shown.

3. **`Asia/Kolkata` (UTC+5:30)**:
   - Correctly resolves to half-hour offset (`17:00 IST -> 11:30 UTC`).

4. **`Pacific/Kiritimati` (UTC+14:00)**:
   - Correctly handles extreme date rollover (`11:00 UTC -> 01:00 UTC+14 on next calendar day`).

5. **Invalid IANA Name, Empty TZ, Unicode TZ, 10 KB String**:
   - `resolve_timezone_name` and `pick_timezone` fall back to `UTC` completely **silently without any log line**.
   - **Vulnerability in `format_due_label` (BUG-09)**:
     ```python
     def format_due_label(day: Optional[date], due_at: Optional[datetime], tz_name: str) -> str:
         ...
         local = due_at.astimezone(ZoneInfo(pick_timezone(tz_name, None)))
         return f"{label}, {format_clock(local.timetz())} ({tz_name})"
     ```
     While `pick_timezone` correctly evaluates to `"UTC"`, the function interpolates the **raw unvalidated `tz_name`** into the return string!
     - Input `"Mars/Phobos"` outputs: `"Fri Oct 30, 12:00 PM (Mars/Phobos)"` (UTC time mislabeled as Martian time).
     - Input `""` outputs: `"Fri Oct 30, 12:00 PM ()"`.
     - Input `"A" * 10000` dumps all 10,000 characters into the user-facing response.

---

### Question 3: Idempotency, Concurrency & Transaction Boundaries

1. **Concurrent Requests with Same `request_id`**:
   - Tested: Two asyncio coroutines attempting `_claim(conn, owner, rid)`.
   - Result: Database `INSERT ... ON CONFLICT DO NOTHING` ensures only the first task obtains `state='claimed'`. The second task retrieves `state='pending'` and receives `IN_FLIGHT_REPLY`. Concurrency isolation holds.

2. **Tenant Isolation**:
   - Tested: `(owner_identity, request_id)` composite primary key in `chat_request_log`.
   - Result: Different `user_id` / `guest_id` values do not collide.
   - **Caveat**: Unauthenticated users with missing IDs fall back to `"default_user"` at [`chat_idempotency.py:151`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/chat_idempotency.py#L151). Concurrent unauthenticated guests will collide if using overlapping IDs.

3. **Oversized `request_id` (>64 chars / 1 MB) (BUG-05)**:
   - `normalize_request_id` checks `REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")`.
   - For an oversized ID, it returns `None`.
   - At [`chat_idempotency.py:158`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/chat_idempotency.py#L158), `if rid and pool:` evaluates to `False`.
   - The request proceeds **without idempotency protection**, silently creating duplicate tasks on retries. It should return a 400 validation error instead.

4. **Transaction Boundary & Post-Creation Crash (BUG-02)**:
   - **Are `chat_request_log` and `tasks` written in the same transaction? NO.**
   - `structured.create_task` runs in its own connection/transaction in [`backend/orchestrator.py:760-800`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/orchestrator.py#L760-L800).
   - `_finish` runs in a separate connection/transaction in [`backend/services/chat_idempotency.py:113-128`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/chat_idempotency.py#L113-L128).
   - If a failure happens after `create_task` (e.g. audit logging, formatting, socket break):
     - `tasks` row remains committed in the database.
     - `run_and_finish` catches the error with `result=None`.
     - In `finally: await _finish(..., result=None)`: `_finish` **deletes the pending claim from `chat_request_log`**!
     - When the client retries with the same `request_id`, the orchestrator re-executes `handle_message` and fails with `duplicate_exact_deadline` error! The client is informed that their request failed, even though the task was already added.

5. **Lost `committed` SSE Event**:
   - In [`backend/services/chat_stream.py:408`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/chat_stream.py#L408), `yield committed_evt` occurs *after* `handle_message` completes.
   - If the stream disconnects before that yield, the client receives `err.committed = undefined`. The frontend displays an error with `canRetry: true`, completely unaware that the mutation succeeded.

---

### Question 4: Pending Action State Machine Evaluation

1. **Confirm Twice**:
   - First Confirm claims action via `UPDATE chat_pending_actions SET status = 'executed' WHERE id = $1 AND status = 'pending'`.
   - Second Confirm finds no active pending action (`get_active_chat_pending_action` filters by `status = 'pending'`). Fails closed; exactly one batch created.
2. **Confirm After Edit in Chat**:
   - Chat messages between preview and confirm (e.g. "change item 2 to Friday") do not alter `chat_pending_actions`. Sending "Confirm" executes the **original unedited list**.
3. **Confirm from Another Conversation**:
   - `get_active_chat_pending_action` requires `conversation_id = $2`. Rejects cross-conversation confirmation.
4. **Confirm After 24 Hours**:
   - `expires_at > now()` fails (5-minute expiry). Action is expired and ignored.
5. **Cancel Then Confirm**:
   - "Cancel" sets `status = 'cancelled'`. Subsequent "Confirm" returns no pending action.
6. **20 vs 21 Items**:
   - 20 items: all 20 accepted and previewed.
   - 21 items: truncated to `MAX_ITEMS = 20`. User is warned: *"You pasted 21 items; I can add at most 20 at once..."*.
7. **SQL Metacharacters & 5 KB Titles**:
   - SQL metacharacters (`'; DROP TABLE tasks; --`): Safely handled by parameterized `$1, $2` queries in `asyncpg`.
   - 5 KB titles: Blocked by `MAX_TITLE_LEN = 200` in [`backend/services/task_intent.py:89`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/task_intent.py#L89) and recorded in `skipped`.
8. **Atomicity**:
   - [`backend/services/task_intake.py:198`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/task_intake.py#L198) uses `async with conn.transaction():`. If any item fails during `_create_all`, all previous insertions and the action resolution roll back completely. Partial insert is prevented.

---

### Question 5: Regex Safety & Polynomial ReDoS Benchmarks

Every regular expression across the PR and `backend/services/*.py` was tested against 50,000-character adversarial inputs (`" " * 50000`, `"-" * 50000`, `"a," * 25000`, `"add " * 12500`, `"create " * 7500`, and `"- a\n" * 12500`).

#### ReDoS Benchmark Results (>100 ms)

| File : Line | Regex Pattern | Adversarial Input | Elapsed Time | CodeQL Status |
|---|---|---|---|---|
| [`backend/services/task_intent.py:43-47`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/task_intent.py#L43-L47) | `\b(?:add(?:ing)?\|creat(?:e\|ing)\|...)\b.*\b(?:tasks?\|todos?\|...)\b` | `"add " * 12500` (50,000 chars) | **12,698.87 ms (12.7s)** | **VULNERABLE (O(N²))** |
| [`backend/services/task_intent.py:43-47`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/task_intent.py#L43-L47) | `\b(?:add(?:ing)?\|creat(?:e\|ing)\|...)\b.*\b(?:tasks?\|todos?\|...)\b` | `"create " * 7500` (52,500 chars) | **5,844.42 ms (5.8s)** | **VULNERABLE (O(N²))** |

All other regexes in `backend/services/*.py` (including the revised `_BULLET_DUE_SPLIT` in `task_intake_parse.py`) completed within `< 5 ms`.

---

### Question 6: Security Audit of `frontend/middleware.js`

1. **Confirmation / Refutation**:
   - **REFUTED for `frontend/middleware.js` in current HEAD**:
     [`frontend/middleware.js:38`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/frontend/middleware.js#L38) reads:
     ```javascript
     const secret = (process.env.EDGE_HMAC_SECRET || process.env.VERCEL_EDGE_SECRET || '').trim()
     ```
     The hardcoded fallback secret in `frontend/middleware.js` was removed in commit `ed3eb4fbf9089cebe1798b2e7031a556d8bb2554` (Oct 29, 2026). Prior to that commit, line 26 contained a literal default fallback secret of length **36 characters**.
2. **Current Security Defect in `frontend/middleware.js`**:
   - When `secret` is unset, [`frontend/middleware.js:47-51`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/frontend/middleware.js#L47-L51) **fails open**: it forwards the request unsigned rather than failing closed with an error.
3. **Hardcoded Fallback Still Present in Backend (BUG-07)**:
   - [`backend/config.py:61`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/config.py#L61) still contains:
     ```python
     EDGE_HMAC_SECRET: str = "..."  # Literal string of length 36
     ```
     If the backend runs without `EDGE_HMAC_SECRET` set in its environment, it defaults to this known 36-character secret, allowing attackers to forge `x-compass-edge-sig` headers.

---

### Question 7: Frontend Race Conditions & Idempotency Gaps

1. **Missing Request ID in `sendQueryToAssistant` (BUG-10)**:
   - In [`frontend/src/api/chatApi.js:32`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/frontend/src/api/chatApi.js#L32):
     ```javascript
     const body = { message: prompt, ...chatRequestFields() }
     ```
     `chatRequestFields()` is called without arguments, returning `{ tz: "..." }` without `request_id`.
   - Callers such as `App.jsx:573` (used by `CompassPanel` and `NorthstarPanel`) therefore execute without idempotency.
2. **Double-Click Race on Intake Confirmation**:
   - [`frontend/src/components/chat/IntakePreviewCard.jsx:38`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/frontend/src/components/chat/IntakePreviewCard.jsx#L38) renders `<button id="btn-intake-confirm">` with **no `disabled` attribute**.
   - Rapid double-clicks dispatch multiple events before the state renders the user message.
3. **Tab Hidden and Resumed (`visibilitychange`)**:
   - When backgrounded, mobile browsers suspend SSE fetch readers. When resumed, `App.jsx:482` immediately triggers `loadTasks()`. If the stream disconnected after backend mutation, the task appears in the task list while the chat UI displays a connection error with a Retry button.

---

## 3. Reproducing Test Suites & Execution Evidence

All confirmed defects are reproduced via clean, standalone test files in `tests/` and `frontend/tests/`.

### Pytest Execution Output (All 12 Tests Failed as Expected)

```
============================= test session starts =============================
platform win32 -- Python 3.13.9, pytest-8.4.2, pluggy-1.5.0
rootdir: C:\Users\Ratnesh Singh\OneDrive\Desktop\compass-chat-task-intake
configfile: pytest.ini
collected 12 items

tests/test_audit_intent.py::test_did_you_remind_me_question_creates_no_task FAILED
tests/test_audit_intent.py::test_should_i_add_task_opinion_question_creates_no_task FAILED
tests/test_audit_intent.py::test_hinglish_capability_question_creates_no_task FAILED
tests/test_audit_intent.py::test_quoted_command_in_conversation_creates_no_task FAILED
tests/test_audit_redos.py::test_creation_phrase_regex_redos_under_100ms FAILED
tests/test_audit_redos.py::test_creation_phrase_regex_create_redos_under_100ms FAILED
tests/test_audit_timezone.py::test_format_due_label_with_invalid_timezone_uses_utc_in_label FAILED
tests/test_audit_timezone.py::test_oversized_timezone_string_is_not_dumped_into_label FAILED
tests/test_audit_timezone.py::test_dst_spring_forward_gap_preserves_local_clock_time FAILED
tests/test_audit_idempotency.py::test_oversized_request_id_silently_bypasses_idempotency FAILED
tests/test_audit_idempotency.py::test_non_atomic_transaction_between_task_and_request_log_creates_duplicate_on_retry FAILED
tests/test_audit_security.py::test_backend_config_has_no_hardcoded_fallback_edge_hmac_secret FAILED

================================== FAILURES ===================================
FAILED tests/test_audit_intent.py::test_did_you_remind_me_question_creates_no_task
  AssertionError: blocks_task_creation failed for 'Did you remind me to take medicine yesterday?'
  assert False is True

FAILED tests/test_audit_intent.py::test_should_i_add_task_opinion_question_creates_no_task
  AssertionError: blocks_task_creation failed for 'Should I add a task for the demo?'
  assert False is True

FAILED tests/test_audit_intent.py::test_hinglish_capability_question_creates_no_task
  AssertionError: route_message created task {'title': 'Kar sakte ho', 'domain': 'general'} for Hinglish question 'kya tum add task kar sakte ho?'
  assert 'add_task' != 'add_task'

FAILED tests/test_audit_intent.py::test_quoted_command_in_conversation_creates_no_task
  AssertionError: route_message created task {'title': 'Remind me to call mom', 'domain': 'general', 'due_date': '2026-10-31'} for quoted speech 'He told me "remind me to call mom tomorrow" during lunch'
  assert 'add_task' != 'add_task'

FAILED tests/test_audit_redos.py::test_creation_phrase_regex_redos_under_100ms
  AssertionError: _CREATION_PHRASE took 12698.9ms on 50k chars (must be <100ms)
  assert 12698.871700005839 < 100

FAILED tests/test_audit_redos.py::test_creation_phrase_regex_create_redos_under_100ms
  AssertionError: _CREATION_PHRASE took 5844.4ms on 'create ' (must be <100ms)
  assert 5844.424700000673 < 100

FAILED tests/test_audit_timezone.py::test_format_due_label_with_invalid_timezone_uses_utc_in_label
  AssertionError: Expected '(UTC)' in label for fallback, got: 'Fri Oct 30, 12:00 PM (Mars/Phobos)'
  assert '(UTC)' in 'Fri Oct 30, 12:00 PM (Mars/Phobos)'

FAILED tests/test_audit_timezone.py::test_oversized_timezone_string_is_not_dumped_into_label
  AssertionError: Label contains unbounded raw timezone string: len=10023
  assert 10023 < 100

FAILED tests/test_audit_timezone.py::test_dst_spring_forward_gap_preserves_local_clock_time
  AssertionError: DST gap shifted local time from 02:30:00 to 03:30:00
  assert datetime.time(3, 30) == datetime.time(2, 30)

FAILED tests/test_audit_idempotency.py::test_oversized_request_id_silently_bypasses_idempotency
  AssertionError: Oversized request_id was silently dropped to None
  assert None is not None

FAILED tests/test_audit_idempotency.py::test_non_atomic_transaction_between_task_and_request_log_creates_duplicate_on_retry
  AssertionError: Retry failed due to lost idempotency: {'conversation_id': '...', 'data': {'error': 'duplicate_exact_deadline', 'existing_task_id': 10045}, 'success': False}
  assert False is True

FAILED tests/test_audit_security.py::test_backend_config_has_no_hardcoded_fallback_edge_hmac_secret
  AssertionError: backend/config.py has hardcoded EDGE_HMAC_SECRET fallback of length 36
  assert 36 == 0

============================= 12 failed in 18.65s =============================
```

### Frontend Node Test Runner Output (2 Tests Failed as Expected)

```
✖ Bug: sendQueryToAssistant omits request_id, disabling idempotency for non-streaming chat (83.0ms)
  AssertionError [ERR_ASSERTION]: sendQueryToAssistant must send a request_id for mutating chat commands
  actual: undefined, expected: true

✖ Bug: IntakePreviewCard Confirm button lacks disabled state, permitting double-click races (1.5ms)
  AssertionError [ERR_ASSERTION]: IntakePreviewCard buttons must support disabled state to prevent rapid double-click dispatch
  expected: /disabled=\{/

ℹ tests 2, pass 0, fail 2
```

### Ruff Linter Check Output

```
$ python -m ruff check tests/test_audit_*.py
All checks passed!
```

---

## 4. Proposed Fixes (Not Applied to Production Files)

The following changes are proposed to resolve the identified bugs. Per audit protocol, none of these edits have been applied to production files.

### Proposal 1: Fix Catastrophic ReDoS in `_CREATION_PHRASE`
**Target:** [`backend/services/task_intent.py:43-47`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/task_intent.py#L43-L47)
Replace greedy `.*` across unbounded characters with a bounded search window or separate verb/noun checks:
```python
# Replace unbounded re.DOTALL .* with bounded non-greedy scan (<= 60 chars)
_CREATION_VERB = re.compile(
    r"\b(?:add(?:ing)?|creat(?:e|ing)|mak(?:e|ing)|sett?(?:ing)?|schedul(?:e|ing)|put(?:ting)?|track(?:ing)?|remind(?:ing)?)\b",
    re.IGNORECASE,
)
_CREATION_NOUN = re.compile(
    r"\b(?:tasks?|todos?|to-dos?|deadlines?|reminders?)\b",
    re.IGNORECASE,
)

def mentions_task_creation(message: str) -> bool:
    """True when the message talks about adding/creating/scheduling tasks or deadlines."""
    if not message:
        return False
    # Two fast linear passes replace the polynomial backtracking regex
    v_match = _CREATION_VERB.search(message)
    if not v_match:
        return False
    # Check if noun occurs within 80 characters of the verb
    window = message[v_match.start():v_match.start() + 100]
    return bool(_CREATION_NOUN.search(window))
```

### Proposal 2: Fix Non-Atomic Transaction Boundary
**Target:** [`backend/orchestrator.py`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/orchestrator.py) & [`backend/services/chat_idempotency.py`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/chat_idempotency.py)
Record the task mutation and the `chat_request_log` transition to `'done'` in the **same database transaction**:
```python
# Inside orchestrator's task creation transaction:
async with pool.acquire() as conn:
    async with conn.transaction():
        task_record = await structured.create_task(...)
        if rid:
            await conn.execute(
                "UPDATE chat_request_log SET state = 'done', response = $3::jsonb "
                "WHERE owner_identity = $1 AND request_id = $2",
                owner, rid, json.dumps(result, default=str),
            )
```

### Proposal 3: Fix Question vs Command Past-Tense & Opinion False Positives
**Target:** [`backend/services/task_intent.py:32-38`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/task_intent.py#L32-L38)
Expand interrogative question recognition to past-tense and auxiliary verbs:
```python
_QUESTION_LEAD = re.compile(
    r"^(?:did|do|does|have|has|had|was|were|is|are|can|could|would|will|should|kya)\s+",
    re.IGNORECASE,
)
```
And reject questions asking for advice or past actions from `strict_command_title`.

### Proposal 4: Fix Timezone Label Leaking in `format_due_label`
**Target:** [`backend/services/task_time.py:104-113`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/services/task_time.py#L104-L113)
```python
def format_due_label(day: Optional[date], due_at: Optional[datetime], tz_name: str) -> str:
    """Human label in the user's zone, e.g. 'Thu Oct 29, 9:00 PM (Asia/Calcutta)'."""
    if day is None:
        return "no due date"
    label = f"{day.strftime('%a %b')} {day.day}"
    if due_at is None:
        return label
    validated_tz = pick_timezone(tz_name, None)
    local = due_at.astimezone(ZoneInfo(validated_tz))
    return f"{label}, {format_clock(local.timetz())} ({validated_tz})"
```

### Proposal 5: Fail-Closed Edge Middleware & Remove Backend Hardcoded Secret
**Target:** [`frontend/middleware.js:38-45`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/frontend/middleware.js#L38-L45) & [`backend/config.py:61`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/backend/config.py#L61)
```javascript
// frontend/middleware.js
const secret = (process.env.EDGE_HMAC_SECRET || process.env.VERCEL_EDGE_SECRET || '').trim()
if (!secret) {
  if (process.env.NODE_ENV === 'production') {
    return new Response(JSON.stringify({ error: 'EDGE_HMAC_SECRET configuration missing' }), {
      status: 500,
      headers: { 'content-type': 'application/json' },
    })
  }
}
```
And in `backend/config.py:61`:
```python
EDGE_HMAC_SECRET: str = ""  # Fail closed: must be provided via environment variable
```

### Proposal 6: Pass `requestId` in `sendQueryToAssistant` & Add UI Button Lock
**Target:** [`frontend/src/api/chatApi.js:27-32`](file:///C:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass-chat-task-intake/frontend/src/api/chatApi.js#L27-L32)
```javascript
export async function sendQueryToAssistant(prompt, conversationId, tone = null, mode = null, specialistId = null, requestId = null) {
  ...
  const body = { message: prompt, ...chatRequestFields(requestId || makeRequestId()) }
```
And add `disabled={isSubmitting}` to `IntakePreviewCard.jsx`.

---

## 5. Audit Verification State

- **Existing Tests**: 355 frontend tests passing; 50 unit intent tests passing.
- **New Audit Tests**: 12 backend pytest tests in 5 files (`tests/test_audit_*.py`) and 2 node tests in `frontend/tests/audit-frontend.test.mjs` consistently fail, verifying all 10 reported issues.
- **Code Linter**: `ruff check tests/test_audit_*.py` verified 0 errors.
- **Git Working Tree**: Clean, unmodified production files; all audit tests left uncommitted for reviewer inspection.
