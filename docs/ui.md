# Shiny Development and Operator Console

The Shiny application is a development/operator console. It is useful for chat,
procedure inspection, seeded scenario exploration, session state, and local table
browsing. It is not a production customer portal and does not replace a contact center.

## Run locally

Start the API, then run `shiny run app_ui.py --port 8001`. `BACKEND_URL` defaults to
`http://localhost:8000`. Docker Compose sets it to the backend service. When backend
authentication is enabled, provide a suitable short-lived `BACKEND_AUTH_TOKEN`.

## Current screens

- Chat: canonical `/api/v1/chat`, session ID and workflow state.
- Test scenarios: seeded refund, complaint, fraud, and Reg E prompts. Model wording
  is observational; deterministic action correctness belongs to backend tests.
- Data browser: allow-listed reference tables only.
- Sidebar: customer, prior sessions, procedures and backend address.

## Limitations

- The console does not capture audio or place calls.
- It does not perform real provider delivery or human-agent staffing.
- It currently exposes only a subset of operations; Swagger remains the complete
  development interface for actions, policies, handoffs, workers and adapters.
- Production deployments should use an identity-aware frontend rather than passing a
  static bearer token to this console.

## Testing

`tests/test_ui_client.py` checks environment configuration, authentication headers,
canonical route usage, app import, and ASGI HTML rendering. Release verification also
runs a local Shiny server smoke; a full browser interaction suite remains appropriate
for a future customer-facing frontend.
