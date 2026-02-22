# API Reference

The FastAPI backend runs on port 8000 by default. All endpoints are async.

## Endpoints

### POST /api/chat

Send a user message and receive an agent response.

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
| `message` | string | yes | The user's message |
| `user_id` | string | yes | Identifier for the user |
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
| `response` | string | The agent's response text |
| `session_id` | string | Session ID (save this to continue the conversation) |

**How it works:**

1. Gets or creates a session via `DatabaseSessionService`
2. Sends the message to the ADK runner which routes it to the appropriate agent
3. The agent follows its procedure, calling tools as needed
4. The final response text is collected and returned

---

### GET /api/procedures

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
    },
    {
      "id": "cs_complaint",
      "name": "Customer Service - Complaint Handling",
      "description": "Handle customer complaints about products, services, or orders",
      "trigger_intents": ["complaint", "unhappy", "dissatisfied", "problem with", "issue with", "bad experience"]
    },
    {
      "id": "fraud_alert_triage",
      "name": "Fraud Operations - Alert Triage",
      "description": "Triage and investigate fraud alerts, gather evidence, and take appropriate action",
      "trigger_intents": ["fraud alert", "suspicious activity", "fraud investigation", "alert triage", "suspicious transaction"]
    }
  ]
}
```

---

### GET /api/session/{session_id}/state

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
  "detail": "Session 'nonexistent-id' not found"
}
```

---

### GET /api/customers

List all customers. Used by the Shiny UI customer selector.

**Response (200):**

```json
{
  "customers": [
    {
      "customer_id": "CUST-456",
      "name": "Jane Smith"
    },
    {
      "customer_id": "CUST-789",
      "name": "Bob Johnson"
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `customers` | array | List of objects with `customer_id` and `name` |

---

### GET /api/tables/{table_name}

Browse the contents of a database table. Used by the Shiny data browser.

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `table_name` | string | Name of the table to query |

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
      "email": "jane.smith@email.com",
      "phone": "+1-555-0123",
      "account_status": "active",
      "loyalty_tier": "gold",
      "total_orders": 15,
      "member_since": "2022-03-15"
    }
  ],
  "count": 4
}
```

**Response (400):**

```json
{
  "detail": "Table 'secret_table' is not allowed"
}
```

---

### GET /health

Health check.

**Response (200):**

```json
{
  "status": "ok",
  "procedures_loaded": 3
}
```

## Example Chat Flow

```bash
# Start a refund conversation (natural language — no order ID needed)
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I bought headphones from TechMart last week and I want a refund", "user_id": "CUST-456"}'

# Or use an explicit order ID
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I want a refund for order ORD-123", "user_id": "CUST-456"}'

# Continue the conversation using the returned session_id
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Yes, the item was defective", "user_id": "CUST-456", "session_id": "<session_id>"}'

# Check workflow progress
curl "http://localhost:8000/api/session/<session_id>/state?user_id=CUST-456"
```
