# API Reference

The FastAPI backend runs on port 8000 by default. All endpoints are async and versioned at `/api/v1`. Legacy routes at `/api/` are maintained for backward compatibility.

## Endpoints

### POST /api/v1/chat

Send a user message and receive an agent response. The response is filtered through guardrails to prevent leakage of internal data.

**Request body:**

```json
{
  "message": "I'd like a refund for order ORD-123",
  "user_id": "user-1",
  "session_id": "optional-existing-session-id"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | yes | The user's message (1–10,000 characters) |
| `user_id` | string | yes | Identifier for the user (1–100 characters) |
| `session_id` | string | no | Existing session ID to continue a conversation. If omitted, a new session is created. |

**Response (200):**

```json
{
  "response": "I'd be happy to help you with a refund! Let me look up order ORD-123...",
  "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `response` | string | The agent's response text (guardrail-filtered) |
| `session_id` | string | Session ID (save this to continue the conversation) |

**How it works:**

1. Normalizes the request via the HTTP channel adapter
2. Gets or creates a session via `DatabaseSessionService`
3. Sends the message to the ADK runner which routes it to the appropriate agent
4. The agent follows its procedure, calling tools as needed
5. The response is passed through `filter_response()` guardrails
6. The filtered response text is returned

---

### WS /api/v1/ws/chat

WebSocket endpoint for real-time streaming agent responses. Each response chunk is guardrail-filtered before sending.

**Inbound message:**

```json
{
  "message": "I'd like a refund for order ORD-123",
  "user_id": "CUST-456",
  "session_id": "optional-session-id"
}
```

**Outbound frames:**

```json
{
  "type": "agent_response",
  "text": "Let me look up that order...",
  "session_id": "a1b2c3d4-...",
  "timestamp": "2026-02-25T10:30:00+00:00",
  "quick_replies": [],
  "cards": [],
  "metadata": {}
}
```

**Completion marker:**

```json
{
  "type": "stream_end",
  "session_id": "a1b2c3d4-..."
}
```

---

### GET /api/v1/procedures

List all loaded workflow procedures.

**Response (200):**

```json
{
  "procedures": [
    {
      "id": "cs_refund",
      "name": "Customer Service - Refund Request",
      "description": "Handle customer refund requests for orders",
      "trigger_intents": ["refund", "return", "money back", "cancel order"]
    }
  ],
  "count": 3
}
```

---

### GET /api/v1/procedures/active

List all active procedure executors with their progress.

**Response (200):**

```json
{
  "active_procedures": {
    "session-id-1": {
      "procedure_id": "cs_refund",
      "procedure_name": "Customer Service - Refund Request",
      "status": "in_progress",
      "current_step": "check_eligibility",
      "steps_completed": ["greet_and_collect", "lookup_order"],
      "total_steps": 7,
      "started_at": "2026-02-25T10:30:00+00:00",
      "completed_at": null
    }
  },
  "count": 1
}
```

---

### GET /api/v1/session/{session_id}/state

Get workflow state for a session.

**Query parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_id` | string | yes | The user ID that owns the session |

**Response (200):**

```json
{
  "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "state": {
    "current_procedure": "cs_refund",
    "current_procedure_name": "Customer Service - Refund Request",
    "current_step": "process_refund",
    "steps_completed": ["greet_and_collect", "lookup_order", "check_eligibility"],
    "workflow_status": "in_progress",
    "workflow_started_at": "2026-02-21T10:30:00.000000"
  }
}
```

Only workflow-related state keys are exposed (not internal agent state).

**Response (404):**

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Session 'nonexistent-id' not found",
    "status_code": 404
  }
}
```

---

### GET /api/v1/session/{session_id}/procedure

Get the procedure execution progress and step history for a session.

**Response (200) — active procedure:**

```json
{
  "session_id": "a1b2c3d4-...",
  "procedure": {
    "procedure_id": "cs_refund",
    "procedure_name": "Customer Service - Refund Request",
    "status": "in_progress",
    "current_step": "check_eligibility",
    "steps_completed": ["greet_and_collect", "lookup_order"],
    "total_steps": 7,
    "started_at": "2026-02-25T10:30:00+00:00",
    "completed_at": null
  },
  "step_history": [
    {
      "step_id": "greet_and_collect",
      "status": "completed",
      "entered_at": "2026-02-25T10:30:00+00:00",
      "completed_at": "2026-02-25T10:30:15+00:00",
      "transition_reason": "completed"
    }
  ]
}
```

**Response (200) — no active procedure:**

```json
{
  "session_id": "a1b2c3d4-...",
  "procedure": null,
  "message": "No active procedure for this session."
}
```

---

### GET /api/v1/customers

List all customers. Supports pagination.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 100 | Maximum number of rows to return |
| `offset` | int | 0 | Number of rows to skip |

**Response (200):**

```json
{
  "customers": [
    {
      "customer_id": "CUST-456",
      "name": "Jane Smith"
    }
  ],
  "count": 4,
  "limit": 100,
  "offset": 0
}
```

---

### GET /api/v1/sessions

List all sessions for a user.

**Query parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_id` | string | yes | The user ID to list sessions for |

**Response (200):**

```json
{
  "sessions": [
    {
      "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "procedure": "Customer Service - Refund Request",
      "status": "completed"
    }
  ],
  "count": 1
}
```

---

### GET /api/v1/tables/{table_name}

Browse the contents of a database table. Supports pagination.

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `table_name` | string | Name of the table to query |

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 100 | Maximum number of rows to return |
| `offset` | int | 0 | Number of rows to skip |

**Allowed tables:**

`customers`, `orders`, `order_items`, `accounts`, `transactions`, `fraud_alerts`, `devices`, `login_history`, `risk_indicators`, `cases`, `case_notes`, `escalations`, `refunds`, `knowledge_articles`

**Response (200):**

```json
{
  "table": "customers",
  "rows": [
    {
      "customer_id": "CUST-456",
      "name": "Jane Smith",
      "email": "jane.smith@email.com"
    }
  ],
  "count": 4,
  "limit": 100,
  "offset": 0
}
```

**Response (422):**

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Table 'secret_table' is not browsable",
    "status_code": 422,
    "field": "table_name",
    "details": {"allowed": ["accounts", "cases", "..."]}
  }
}
```

---

### GET /api/v1/metrics

Operational metrics for monitoring dashboards.

**Response (200):**

```json
{
  "procedures_loaded": 3,
  "active_procedures": 1,
  "auth_enabled": false,
  "rate_limit_enabled": false,
  "environment": "dev"
}
```

---

### GET /health

Health check.

**Response (200):**

```json
{
  "status": "ok",
  "version": "2.0.0",
  "environment": "dev",
  "procedures_loaded": 3,
  "auth_enabled": false
}
```

## Error Responses

All errors follow a structured format:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Human-readable error description",
    "status_code": 404
  }
}
```

| Error Code | Status | Description |
|------------|--------|-------------|
| `NOT_FOUND` | 404 | Resource not found |
| `VALIDATION_ERROR` | 422 | Invalid input |
| `AUTHENTICATION_ERROR` | 401 | Missing or invalid token |
| `AUTHORIZATION_ERROR` | 403 | Insufficient permissions |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests |
| `TOOL_EXECUTION_ERROR` | 500 | Tool failed during execution |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

## Example Chat Flow

```bash
# Start a refund conversation (natural language — no order ID needed)
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I bought headphones from TechMart last week and I want a refund", "user_id": "CUST-456"}'

# Or use an explicit order ID
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I want a refund for order ORD-123", "user_id": "CUST-456"}'

# Continue the conversation using the returned session_id
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Yes, the item was defective", "user_id": "CUST-456", "session_id": "<session_id>"}'

# Check workflow progress
curl "http://localhost:8000/api/v1/session/<session_id>/state?user_id=CUST-456"

# Check procedure execution details
curl "http://localhost:8000/api/v1/session/<session_id>/procedure"

# Browse paginated data
curl "http://localhost:8000/api/v1/customers?limit=10&offset=0"

# View operational metrics
curl "http://localhost:8000/api/v1/metrics"
```

---

## Authoritative core-action APIs

### POST /api/v1/core/refunds

Creates or returns an idempotent refund action. This endpoint is the production
write path; conversational tools cannot bypass it. The authenticated actor must
be the customer or have `refund:write`, the order is reloaded, ownership and the
refund window are checked, parameter values are committed as verified facts, and
the database connector revalidates them before writing the refund.

```json
{
  "customer_id": "CUST-456",
  "order_id": "ORD-123",
  "reason": "Customer confirmed the item was damaged",
  "consent_evidence_ref": "chat-message:msg-42"
}
```

```json
{
  "action_id": "ACT-...",
  "status": "succeeded",
  "outcome": {
    "refund_id": "REF-...",
    "order_id": "ORD-123",
    "amount": 79.99,
    "currency": "USD",
    "status": "processed"
  }
}
```

Repeating the request for the same order returns the original action and does not
write another refund. Unknown connector outcomes remain `unknown` until the
reconciliation worker records `reconciled`, `failed`, or another `unknown` result.

### POST /api/v1/ivr/turns

Normalizes a provider ASR turn into the shared conversation inbox. Stable
`message_id` values are deduplicated across retries. ASR never creates verified
facts; low-confidence or interrupted input requires readback.

```json
{
  "message_id": "call-123:turn-4",
  "conversation_id": "call-123",
  "customer_id": "CUST-456",
  "transcript": "refund order one two three",
  "asr_confidence": 0.71,
  "interrupted": false
}
```

```json
{
  "accepted": true,
  "requires_readback": true,
  "proposed_authority": "asserted"
}
```

### Chat/WS dedupe and identity

`POST /api/v1/chat` and WebSocket messages accept an optional stable
`message_id`. Duplicate IDs are suppressed before ADK execution. `user_id` is
retained for client compatibility but means the serviced customer, not the JWT
subject. Sessions are owned by the authenticated actor/customer pair. Production
WebSockets require a Bearer token during the handshake.
