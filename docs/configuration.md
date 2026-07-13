# Configuration Reference

Version 3.1.0 configuration is defined by `workflow_engine.settings.Settings`.
Values come from environment variables and an optional `.env` file; names are
case-insensitive. Unknown variables are ignored, so use the contract tests and this
page to detect misspellings.

## Environment profiles

| Profile | Auth | Demo seed | Jurisdiction | Upstream default |
|---|---|---|---|---|
| `dev` | off by default | on | observe-only | sandbox |
| `staging` | configurable | off | enforced | disabled unless provider configured |
| `production` | required | forbidden | enforced | disabled or provider; sandbox forbidden |

## Application and API

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | `dev` | `dev`, `staging`, or `production`. |
| `DEBUG` | `false` | Debug behavior where supported. Keep false in production. |
| `API_HOST` | `0.0.0.0` | Bind host used by launch commands. |
| `API_PORT` | `8000` | Bind port used by launch commands. |
| `API_PREFIX` | `/api/v1` | Versioned API prefix. |
| `CORS_ORIGINS` | localhost UI origins | JSON array of allowed browser origins. Wildcard is rejected in production. |

## LLM and ADK

| Variable | Default | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | unset | Google AI credential when not using Vertex AI. |
| `GOOGLE_GENAI_USE_VERTEXAI` | `false` | Select Vertex AI backend/authentication. |
| `LLM_MODEL` | `gemini-2.5-flash` | Model name passed to ADK. |
| `LLM_TEMPERATURE` | provider default | Optional sampling temperature, 0–2. |
| `LLM_TOP_P` | provider default | Optional nucleus sampling, 0–1. |
| `LLM_TOP_K` | provider default | Optional top-k sampling. |
| `LLM_MAX_OUTPUT_TOKENS` | provider default | Optional output ceiling. |
| `APP_NAME` | `workflow_engine` | ADK application namespace. |
| `SESSION_TTL_HOURS` | `24` | Intended session lifetime. |

The model affects interpretation and response wording. It is never an action
authorization source.

## Storage

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/workflow.db` | CoreStore URL. SQLite is built in. |
| `REFERENCE_DATA_DATABASE_URL` | workflow SQLite | Local business/reference and audit repository; currently SQLite-only. |
| `SEED_REFERENCE_DATA` | true only in dev | Seed demonstration data. Production rejects true. |
| `ADK_SESSION_DATABASE_URL` | separate SQLite | Untrusted ADK session/event store. |
| `POLICY_DATABASE_URL` | `DATABASE_URL` | Policy repository URL. |
| `CORE_STORE_ADAPTER_FACTORY` | unset | Trusted `module:callable` for a non-SQLite CoreStore. |
| `POLICY_REPOSITORY_ADAPTER_FACTORY` | unset | Trusted `module:callable` for a non-SQLite PolicyRepository. |
| `SANDBOX_DATABASE_URL` | local SQLite | Simulated resources, effects, receipts, and handoffs. |
| `DB_POOL_SIZE` | `5` | Pool hint for adapters that use it. |
| `DB_MAX_OVERFLOW` | `10` | Pool overflow hint. |
| `DB_POOL_TIMEOUT` | `30` | Pool checkout timeout seconds. |
| `DB_ECHO` | `false` | SQL debug output. |

Only SQLite adapters ship. A PostgreSQL URL does not create PostgreSQL support; a
deployment must provide both conforming factories.

## Authentication and rate limiting

| Variable | Default | Purpose |
|---|---|---|
| `AUTH_ENABLED` | `false` | Enable application JWT auth. Required in production. |
| `AUTH_SECRET_KEY` | development secret | HMAC JWT secret. Default rejected in production. |
| `AUTH_ALGORITHM` | `HS256` | Approved HMAC algorithm. |
| `AUTH_TOKEN_EXPIRE_MINUTES` | `480` | Token lifetime. |
| `AUTH_ISSUER` | `workflow-engine` | Required token issuer. |
| `RATE_LIMIT_ENABLED` | `false` | Enable in-process rate limiter. |
| `RATE_LIMIT_REQUESTS` | `100` | Requests per window. |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Window length. |

The built-in auth is not OAuth/OIDC federation. The rate limiter is process-local;
multi-instance deployments need a shared edge or rate-limit service.

## Policy and jurisdiction

| Variable | Default | Purpose |
|---|---|---|
| `JURISDICTION_PROFILE` | `NAM` | Active operational profile ID. |
| `JURISDICTION_CONFIG_PATH` | unset | YAML/JSON override approved by the deployment. |
| `JURISDICTION_ENFORCE` | false in dev, true elsewhere | Observe or block violations. |
| `POLICY_SIGNING_KEY` | development key | Current HMAC policy key. Default rejected in production. |
| `POLICY_SIGNING_KEY_ID` | `primary` | ID stamped on newly signed packages. |
| `POLICY_VERIFICATION_KEYS` | `{}` | JSON map of retired key ID to verification secret. |
| `POLICY_AUTHOR` | `operations-author` | Bootstrap author identity. |
| `POLICY_APPROVER` | `risk-approver` | Bootstrap approver; must differ from author. |

Keys belong in a secret manager or injected secret. Never put them in source,
procedure YAML, prompts, logs, or images.

## Upstream mode and provider bundle

| Variable | Default | Purpose |
|---|---|---|
| `UPSTREAM_MODE` | sandbox in dev, disabled elsewhere | `disabled`, `sandbox`, or `provider`. |
| `PROVIDER_BUNDLE_FACTORY` | unset | Trusted `module:callable` returning a complete `ProviderBundle`; required in provider mode. |
| `ACTION_WORKER_LEASE_SECONDS` | `30` | Outbox lease duration. |
| `ACTION_RECONCILIATION_DELAY_SECONDS` | `30` | Minimum age between ambiguity queries. |

The provider factory receives validated `Settings` and returns adapters for STT,
TTS, telephony, chat, handoff, action dispatch/reconciliation, and authoritative
resources. Configuration is code execution: allow-list and control the installed
package.

Sandbox mode is rejected in production. Provider mode without a bundle factory is
also rejected.

## Logging, reasoning, and compliance

| Variable | Default | Purpose |
|---|---|---|
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |
| `LOG_FORMAT` | `json` | `json` or `text`; Compose uses text for development. |
| `LOG_FILE` | unset | Optional file; stdout when unset. |
| `REASONING_ENABLED` | `true` | Enable Z3/SymPy response verification. |
| `REASONING_MAX_ITERATIONS` | `2` | Maximum rewrite cycles, 0–5. |
| `COMPLIANCE_ENABLED` | `true` | Enable encoded domain checks. |

`/api/v1/metrics` is an authenticated JSON operational snapshot. Prometheus and
OpenTelemetry exporters are not packaged, and there are no inactive metrics/tracing
settings in 3.1.0.

## Shiny operator console

| Variable | Default | Purpose |
|---|---|---|
| `BACKEND_URL` | `http://localhost:8000` | Backend base URL; Compose sets `http://backend:8000`. |
| `BACKEND_AUTH_TOKEN` | unset | Optional bearer token attached by the UI client. |

A static token is acceptable only for controlled development/operations. Use an
identity-aware frontend for production users.

## Production startup rejection

Startup rejects production with:

- authentication disabled;
- default JWT or policy signing secrets;
- wildcard CORS;
- unapproved JWT algorithm;
- sandbox upstream mode;
- reference-data seeding;
- provider mode without a provider-bundle factory.

## Example development profile

```dotenv
ENVIRONMENT=dev
GOOGLE_API_KEY=replace-me
AUTH_ENABLED=false
DATABASE_URL=sqlite+aiosqlite:///data/workflow.db
REFERENCE_DATA_DATABASE_URL=sqlite+aiosqlite:///data/workflow.db
ADK_SESSION_DATABASE_URL=sqlite+aiosqlite:///data/adk_sessions_v2.db
POLICY_DATABASE_URL=sqlite+aiosqlite:///data/workflow.db
UPSTREAM_MODE=sandbox
SANDBOX_DATABASE_URL=sqlite+aiosqlite:///data/upstream_sandbox.db
```
