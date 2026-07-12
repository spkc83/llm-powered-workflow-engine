# Operations Runbook

## Startup

1. Load secrets and environment configuration.
2. Initialize/migrate the domain/core database.
3. Initialize the separate ADK 2.x session database.
4. Validate tool classification and active policy signatures.
5. Start the API and verify `/health` reports version `2.0.0`.

SQLite is the development/default store. Production database adapters must preserve
transactions, optimistic compare-and-swap, and unique constraints.

## Required production configuration

- `ENVIRONMENT=production`
- `AUTH_ENABLED=true`
- strong JWT secret or external issuer integration
- production domain/core database URL
- separate ADK session database URL
- policy signing key from a secret manager
- distinct `POLICY_AUTHOR` and `POLICY_APPROVER` identities
- explicit CORS origins and rate limits
- chat/IVR provider credentials in provider-specific adapters

## Action reconciliation

Monitor `action_attempts` for `unknown`. A reconciler queries the connector by
stable business key and records `reconciled`, `failed`, or a renewed `unknown`.
Never dispatch again to discover the result. Alert when an unknown result exceeds
the procedure-owned deadline.

## Handoff operations

Monitor requested, accepted, timed-out, and failed transfers. Customer-visible
connected status requires durable acceptance with an agent ID. Queue adapters must
preserve the core lifecycle.

## Rollout and rollback

Canary by procedure, channel, and risk tier. Advancement requires zero unauthorized
actions and complete mandatory evidence. Roll back conversational models/prompts
independently; never roll an active case to another policy version silently.

## Backup and recovery

Back up domain/core and ADK databases independently. Domain/core data is the
authority. Recovery testing must prove inbox dedupe, action idempotency, unknown
outcome reconciliation, procedure version locks, and handoff state reconstruction.

## Observability

Trace provider message → conversation → ADK invocation → case/facts → policy →
action → connector → delivery/handoff. Track latency percentiles, duplicate
suppression, blocked actions, unknown outcomes, reconciliation age, clarification,
transfer, abandonment, and recontact.
