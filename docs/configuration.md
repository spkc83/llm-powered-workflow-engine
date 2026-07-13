# Configuration Reference

Settings are defined in `workflow_engine/settings.py`, loaded from environment and
`.env`, and are case-insensitive. Production validation fails startup for unsafe
secret, authentication, CORS, sandbox, signing, or seed combinations.

## Profiles

| Profile | Auth | Seed data | Jurisdiction | Upstream |
|---|---|---|---|---|
| `dev` | off by default | on by default | observe | sandbox by default |
| `staging` | configurable | off | enforce | disabled unless provider configured |
| `production` | required | forbidden | enforce | disabled or provider; sandbox forbidden |

## Core variables

| Variable | Default | Meaning |
|---|---|---|
| `ENVIRONMENT` | `dev` | `dev`, `staging`, or `production`. |
| `DATABASE_URL` | SQLite workflow DB | Core store URL. Non-SQLite needs `CORE_STORE_ADAPTER_FACTORY`. |
| `REFERENCE_DATA_DATABASE_URL` | SQLite workflow DB | Local business/reference and audit repository; currently SQLite. |
| `SEED_REFERENCE_DATA` | true only in dev | Load sample customers/orders/transactions. Forbidden in production. |
| `ADK_SESSION_DATABASE_URL` | separate SQLite DB | Untrusted ADK session/event storage. |
| `POLICY_DATABASE_URL` | `DATABASE_URL` | Durable policy repository. |
| `CORE_STORE_ADAPTER_FACTORY` | unset | Trusted `module:callable` for a non-SQLite store. |
| `POLICY_REPOSITORY_ADAPTER_FACTORY` | unset | Trusted `module:callable` for policy persistence. |
| `UPSTREAM_MODE` | sandbox in dev, disabled otherwise | `disabled`, `sandbox`, or `provider`. |
| `PROVIDER_BUNDLE_FACTORY` | unset | Trusted `module:callable` returning `ProviderBundle`; required in provider mode. |
| `SANDBOX_DATABASE_URL` | local SQLite | Simulated provider resources/effects/receipts. |

## Security and policy

`AUTH_ENABLED` is mandatory in production. Set a strong `AUTH_SECRET_KEY`, approved
HMAC `AUTH_ALGORITHM`, issuer, expiration, and explicit `CORS_ORIGINS`. Policy uses
`POLICY_SIGNING_KEY`, `POLICY_SIGNING_KEY_ID`, and optional
`POLICY_VERIFICATION_KEYS` for retired keys. Author and approver identities must differ.

`JURISDICTION_PROFILE=NAM` selects the built-in profile. Supply an approved YAML/JSON
file with `JURISDICTION_CONFIG_PATH`; enforcement defaults off in dev and on elsewhere.

## UI

| Variable | Meaning |
|---|---|
| `BACKEND_URL` | Backend base URL; Docker uses `http://backend:8000`. |
| `BACKEND_AUTH_TOKEN` | Optional bearer token for the operator UI. Do not bake it into images. |

## Provider factory

The callable receives the validated `Settings` object and returns
`workflow_engine.integrations.loading.ProviderBundle`. The bundle supplies STT,
TTS, telephony, chat, handoff, action, and authoritative-resource adapters. Factory
configuration is code execution: allow-list the package and protect deployment config.

## Observability

`LOG_LEVEL`, `LOG_FORMAT`, and `LOG_FILE` are active. `/health`, `/ready`,
`/api/v1/metrics`, and operations endpoints provide JSON status. The repository does
not package Prometheus or OpenTelemetry exporters; deployments may translate these
signals or add instrumentation without relying on inactive configuration flags.
