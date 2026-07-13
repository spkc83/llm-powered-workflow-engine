# Storage and Database Adapters

## Defaults

SQLite is the development, fallback, and reference implementation:

- `DATABASE_URL=sqlite+aiosqlite:///data/workflow.db` — domain and core authority;
- `POLICY_DATABASE_URL` — defaults to `DATABASE_URL`;
- `ADK_SESSION_DATABASE_URL=sqlite+aiosqlite:///data/adk_sessions_v2.db` — non-authoritative ADK state;
- `SANDBOX_DATABASE_URL=sqlite+aiosqlite:///data/upstream_sandbox.db` — development-only upstream emulator.

Initialize/seed with `python -m workflow_engine.database`. Runtime migrations are
idempotent; back up before upgrades.

## Business tables

The reference database contains customers, orders/items, accounts, transactions,
fraud alerts, devices/logins/risk indicators, cases/notes, escalations, refunds,
EFT disputes, knowledge articles, and `audit_trail`. Refund order ID is unique.
Audit rows carry `previous_hash` and `entry_hash`.

## CoreStore tables

| Table | Purpose |
|---|---|
| `workflow_cases` | Customer/procedure/version binding and optimistic version. |
| `case_facts` | Value, authority, source, evidence, expiry, supersession. |
| `action_attempts` | Command, unique idempotency key, lifecycle, outcome. |
| `action_events` | Append-oriented requested, authorized, dispatched, and outcome evidence. |
| `action_proposals` | Immutable intent/context/preview plus pending/confirmed/cancelled/expired CAS state. |
| `core_outbox` | Durable dispatch topic, lease, attempts, retry/quarantine. |
| `conversation_inbox_v3` | Provider-scoped messages and ordering status. |
| `conversation_sequences` | Last accepted provider/conversation sequence. |
| `handoffs` | Durable customer-visible transfer state. |

Older `inbox_messages`/`conversation_inbox` tables remain migration history and are
not the v3 processing authority.

## PolicyRepository table

`policy_packages` stores immutable JSON packages and lifecycle. A partial unique
index enforces one active package for each procedure/jurisdiction in SQLite.

## Sandbox tables

`upstream_sandbox.db` contains authoritative development resources, injected
action scenarios, simulated provider effects, handoff tickets, and delivery
receipts. It is ignored by Git, explicitly marked simulated, and forbidden in
production.

## Database portability

`create_core_store()` and `create_policy_repository()` resolve the URL scheme.
SQLite is built in. Deployments register a factory for another scheme; domain code
does not change. The reference app loads trusted `package.module:callable`
factories from `CORE_STORE_ADAPTER_FACTORY` and
`POLICY_REPOSITORY_ADAPTER_FACTORY`. Treat these settings as code-execution
configuration and control them like deployment artifacts. A production adapter
must pass the same conformance behavior:

- atomic optimistic compare-and-swap;
- action plus outbox commit in one transaction;
- atomic proposal creation and compare-and-set lifecycle transitions;
- compare-and-set action lifecycle transitions so dispatch/reconciliation races
  cannot overwrite terminal evidence;
- unique business idempotency;
- safe multi-worker leases and lease expiry;
- provider/message and policy activation uniqueness;
- ordering quarantine and durable handoff transitions;
- consistent JSON/time encoding and transaction rollback.

Do not point `DatabaseSessionService` at the domain/core database. ADK schemas and
retention differ and ADK state is untrusted for authorization.

The packaged SQLite topology is intentionally small: one API worker and one action
worker on the same host/volume. Multi-node or high-write deployments must provide a
conforming external adapter; this repository does not include PostgreSQL support.

Registry files and pinned OpenAPI documents are deployment configuration, not
database authority. Proposal/action rows store connector binding and contract
versions; retain matching configuration and connector code through retention.
