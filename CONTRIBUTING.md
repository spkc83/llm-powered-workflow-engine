# Contributing

1. Create a focused branch and preserve existing behavior with tests.
2. Keep model proposals separate from authoritative facts and actions.
3. Add every model-visible tool to the control catalog.
4. Add no consequential action without permission, evidence provenance,
   idempotency, outcome, reconciliation, and adversarial tests.
5. Update user, API, database, operations, migration, and release documentation when
   behavior changes.
6. Run `pytest -q`, Ruff on changed files, `compileall`, and `git diff --check`.

Never commit `.env`, credentials, policy keys, customer data, raw audio, or sensitive
transcripts.
