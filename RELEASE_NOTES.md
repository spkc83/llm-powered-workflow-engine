# LLM-Powered Workflow Engine v2.0.0

Version 2.0 moves consequential business control out of prompts and model session
state. ADK 2.1 remains responsible for bounded interpretation and response
composition, while the new deterministic core owns cases, verified facts, policy,
action authorization, idempotency, connector outcomes, and handoff truth.

## Highlights

- Chat and IVR share identity, dedupe, policy, action, response, and handoff rules.
- Refunds are ownership-checked, deterministically evaluated, idempotent, and
  reconciled without duplicate dispatch.
- Low-confidence IVR input cannot become verified fact or authorize an action.
- SQLite works out of the box; additional databases implement the `CoreStore` port.
- Simple signed NAM policy governance requires separate author and approver.

## Upgrade warning

ADK 1.9 session tables are not compatible with ADK 2.1. Configure the new separate
session database and follow `docs/migration.md` before starting production workers.

## Validation

The release is gated by the complete automated suite, Ruff on changed/new code,
Python compilation, dependency-baseline comparison, database migration smoke tests,
and Git diff validation.
