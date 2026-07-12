# Migration to v2.0.0

## Breaking changes

- Google ADK is pinned to 2.1.0.
- ADK `DatabaseSessionService` now uses an async SQLAlchemy URL.
- ADK sessions move from the domain database to
  `ADK_SESSION_DATABASE_URL` (`data/adk_sessions_v2.db` by default).
- Request `user_id` means serviced customer; JWT subject remains the actor.
- Production consequential model tools are frozen unless routed through the
  action gateway.
- Refunds are unique by order and execute through `/api/v1/core/refunds` or the
  gateway-backed tool.

## Upgrade procedure

1. Back up `data/workflow.db` and the previous ADK session tables.
2. Install from `requirements.txt`; verify `google-adk==2.1.0`.
3. Configure `ADK_SESSION_DATABASE_URL` to a new empty database.
4. Run `python -m workflow_engine.database`. Historical duplicate prototype
   refunds are reduced to the earliest record per order before the unique index.
5. Start the API and execute health, identity, chat dedupe, IVR, refund idempotency,
   and reconciliation smoke tests.
6. Preserve the old ADK database read-only for the approved retention period; do
   not import incompatible 1.9 events into the 2.x tables.

## Rollback

Stop v2 workers, restore the database backup, restore the previous dependency set,
and point the previous application at its original ADK session store. Do not allow
both versions to dispatch consequential actions concurrently.
