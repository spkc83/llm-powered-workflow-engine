# Migration from v2.0 to v3.0

## Major changes

- REST, WebSocket, and canonical IVR turns use one `ConversationService` pipeline.
- Inbox identity is `(provider_id, message_id)` and optional sequences can be
  quarantined.
- All consequential action types have closed schemas and gateway specifications.
- Action authorization atomically creates a durable outbox record.
- Unknown outcomes have a reconciliation worker and operational APIs.
- Policy packages persist across restart and carry signing key IDs.
- STT, TTS, telephony, chat delivery, action, and human-agent ports have sandbox
  implementations and Swagger contracts.
- NAM operational controls are configurable and enforced outside development by
  default.
- Audit records form a SHA-256 chain.

## Configuration additions

Review `.env.example`: `POLICY_DATABASE_URL`, `POLICY_SIGNING_KEY_ID`,
`UPSTREAM_MODE`, `SANDBOX_DATABASE_URL`, worker lease/reconciliation settings,
`JURISDICTION_CONFIG_PATH`, and `JURISDICTION_ENFORCE`.

Do not set sandbox mode in production. `provider` mode requires deployment wiring
for real ports; the reference app remains fail closed otherwise.

## Upgrade procedure

1. Stop v2 action processing and back up domain/core and ADK databases.
2. Deploy v3 with `UPSTREAM_MODE=disabled`.
3. Run `python -m workflow_engine.database`; it adds audit hash columns and performs
   a one-time hash backfill for pre-v3 rows.
   Core-store startup also creates `action_events` and marks reconstructed
   pre-v3 lifecycle evidence with `{"migrated": true}`.
4. Start once and verify policy packages persist and signatures validate.
5. Verify health, audit integrity, inbox dedupe, sequence quarantine, outbox lease,
   post-commit timeout reconciliation, and handoff transitions.
6. Implement and test real adapters against `docs/integration-guide.md`.
7. Canary one procedure/channel before enabling each provider or action.

The old inbox tables remain for migration history; v3 uses
`conversation_inbox_v3`. Do not delete old evidence until retention approval.

## Rollback

Stop v3 workers, disable provider callbacks, restore the database backup, and start
v2 with its original policy/session configuration. Effects already committed by an
upstream provider remain real; reconcile them before replaying work after rollback.
