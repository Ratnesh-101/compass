# Compass API Contract

This document is the source of truth for both the backend developer (Rhythm) and the frontend developer (Nandani). It specifies every endpoint, request/response shape, and error format.

## Context
Compass is a personal AI assistant with persistent memory. The backend is FastAPI. Auth is a single bearer token.

## Base URL
`http://localhost:8000` (local dev)

## Authentication
All endpoints except `GET /health` require:
```http
Authorization: Bearer <AUTH_TOKEN>
```
Unauthorized requests return `401 {"detail": "Unauthorized"}`

## Endpoints

### 1. `POST /chat`
Main conversational endpoint. All user messages go through here.

**Request:**
```json
{
  "message": "string (required) — the user's message",
  "conversation_id": "string (optional, UUID) — existing conversation to continue. If omitted, a new conversation is created."
}
```

**Response (200):**
```json
{
  "conversation_id": "uuid",
  "response": "string — the assistant's reply",
  "skill_used": "string | null — which skill was invoked (e.g. 'add_task', 'query_code_context', 'chat')",
  "data": "object | null — structured data from the skill, if any (e.g. list of tasks, list of memory chunks)"
}
```

### 2. `GET /conversations/{conversation_id}/messages`
Get message history for a conversation.

**Response (200):**
```json
{
  "conversation_id": "uuid",
  "messages": [
    {
      "id": "integer",
      "role": "user | assistant | system",
      "content": "string",
      "skill_called": "string | null",
      "created_at": "ISO 8601 datetime"
    }
  ]
}
```

### 3. `GET /projects`
List all tracked projects.

**Query params:** `domain` (optional, filter by domain)

**Response (200):**
```json
{
  "projects": [
    {
      "id": "integer",
      "name": "string",
      "domain": "hackathon | coursework | code | general",
      "description": "string | null",
      "created_at": "ISO 8601 datetime"
    }
  ]
}
```

### 4. `GET /tasks`
Query tasks with optional filters.

**Query params:**
- `domain` (optional)
- `project` (optional, project name)
- `status` (optional, default: all statuses)
- `due_before` (optional, ISO date)

**Response (200):**
```json
{
  "tasks": [
    {
      "id": "integer",
      "domain": "string",
      "project": {"id": "integer", "name": "string"} | null,
      "title": "string",
      "due_date": "ISO date | null",
      "status": "open | in_progress | done | overdue",
      "priority": "low | medium | high | urgent",
      "notes": "string | null",
      "created_at": "ISO 8601 datetime",
      "updated_at": "ISO 8601 datetime"
    }
  ]
}
```

### 5. `GET /dashboard`
Aggregated stats for the sidebar. Returns per-domain summary.

**Response (200):**
```json
{
  "domains": {
    "hackathon": {
      "project_count": "integer",
      "open_task_count": "integer",
      "nearest_deadline": {"task_id": "int", "title": "string", "due_date": "ISO date"} | null,
      "last_activity": "ISO 8601 datetime | null"
    },
    "coursework": {
      "project_count": "integer",
      "open_task_count": "integer",
      "nearest_deadline": {"task_id": "int", "title": "string", "due_date": "ISO date"} | null,
      "last_activity": "ISO 8601 datetime | null"
    },
    "code": {
      "project_count": "integer",
      "open_task_count": "integer",
      "nearest_deadline": {"task_id": "int", "title": "string", "due_date": "ISO date"} | null,
      "last_activity": "ISO 8601 datetime | null"
    },
    "general": {
      "project_count": "integer",
      "open_task_count": "integer",
      "nearest_deadline": {"task_id": "int", "title": "string", "due_date": "ISO date"} | null,
      "last_activity": "ISO 8601 datetime | null"
    }
  },
  "total_open_tasks": "integer",
  "total_projects": "integer"
}
```

### 6. `GET /memory/timeline`
Chronological memory entries for the timeline view.

**Query params:**
- `domain` (optional)
- `limit` (optional, default 50)
- `offset` (optional, default 0)

**Response (200):**
```json
{
  "entries": [
    {
      "type": "task_created | task_updated | code_context | coursework_note | conversation",
      "domain": "string",
      "project": "string | null",
      "summary": "string — human-readable summary of what happened",
      "created_at": "ISO 8601 datetime"
    }
  ],
  "total": "integer",
  "has_more": "boolean"
}
```

### 7. `GET /admin/usage`
Token usage statistics.

**Response (200):**
```json
{
  "total_input_tokens": "integer",
  "total_output_tokens": "integer",
  "total_estimated_cost_usd": "number",
  "by_model": {
    "model_id": {
      "calls": "integer",
      "input_tokens": "integer",
      "output_tokens": "integer",
      "estimated_cost_usd": "number"
    }
  }
}
```

### 8. `GET /health`
Health check (no auth required).

**Response (200):**
```json
{
  "status": "ok",
  "version": "0.1.0",
  "database": "connected | disconnected"
}
```

## Error Format
All errors follow this shape:
```json
{
  "detail": "string — human-readable error message"
}
```

Common status codes:
- 400: Bad request (invalid params)
- 401: Unauthorized (missing/invalid bearer token)
- 404: Resource not found
- 500: Internal server error

## Domain Enum
Used across all endpoints: `hackathon`, `coursework`, `code`, `general`

## Notes for Frontend (Nandani)
- Use `POST /chat` for ALL user interactions in the chat panel
- Use `GET /dashboard` to populate the sidebar on page load (poll every 30s or after each chat message)
- Use `GET /tasks` for the task list view with filters
- Use `GET /memory/timeline` for the memory timeline panel
- Use `GET /conversations/{id}/messages` to restore chat history when resuming a conversation
- WebSocket streaming is a stretch goal — for now, `POST /chat` is synchronous (may take 2-5s for Ultra calls)

## Notes for Backend (Rhythm)
- All datetime fields should be ISO 8601 with timezone (UTC)
- Pagination: use `limit` + `offset` pattern
- The `/chat` endpoint is the only one that triggers model inference. All other endpoints are direct DB queries.
- The `/dashboard` endpoint should be a single efficient SQL query, not N+1 calls
