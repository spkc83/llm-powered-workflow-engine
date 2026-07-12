# Contributing

1. Work on a focused branch; add regression tests before behavior changes.
2. Keep ADK/model proposals separate from authoritative facts and effects.
3. Classify every model-visible tool; consequential tools stay production-frozen.
4. Add a consequential action only with typed payload/specification, RBAC, active
   policy allow-list, authoritative resource reload, consent/approval, atomic
   outbox, idempotency, post-commit timeout reconciliation, and hostile tests.
5. Keep provider code behind contracts in `workflow_engine/integrations`; sandbox
   outputs must say simulated and production must fail closed without a provider.
6. Preserve SQLite as the default and run store/repository conformance behavior for
   additional databases.
7. Update user, API, integration, channel, storage, governance, operations, threat,
   migration, security, support, changelog, and release documentation.
8. Run full `pytest -q`, Ruff, compilation, static/security checks available in the
   environment, OpenAPI/link checks, migration smoke, and `git diff --check`.

Never commit `.env`, runtime databases, credentials, signing keys, customer data,
raw audio, sensitive transcripts, DTMF, or SAR narratives.
