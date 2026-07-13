# Roadmap and Remaining Work

This roadmap is based on the v3.2.0 working implementation. It separates product
gaps from deployment obligations so planned work is not mistaken for shipped code.

## Highest priority product work

1. **Production identity and confirmation UX** — replace static Shiny bearer-token
   use with an identity-aware frontend, delegated-customer selection, accessible
   confirmation review, step-up authentication where policy requires it, and a
   durable consent presentation/version contract.
2. **Provider conformance harness** — certify REST/Python action connectors for
   idempotency, timeout-after-commit, reconciliation truthfulness, schema drift,
   redaction, auth rotation, and failure injection before enabling them.
3. **Production database adapters** — implement and load-test CoreStore, policy,
   reference/audit, and ADK session adapters for an approved database. The current
   non-SQLite support is a protocol/factory boundary, not a shipped adapter.
4. **Observability** — add Prometheus metrics, distributed tracing, connector
   latency/error measures, proposal/action funnels, dashboards, alerts, and SIEM
   export. Current JSON metrics and structured logs are operational foundations only.
5. **Browser and accessibility QA** — add a real browser suite for Shiny action
   cards, confirmation replay, expiry, errors, session restore, keyboard use, and
   screen-reader behavior. Current tests cover helpers, typed client, import, and
   ASGI/render smoke rather than full browser interaction.

## Integration work

- Supply and certify real STT, TTS, telephony, outbound-chat, contact-center,
  action, and authoritative-resource adapters.
- Add a signed provider callback framework if deployments need callbacks in
  addition to reconciliation polling.
- Implement a reviewed Python WebSocket connector only for providers that cannot
  support REST; retain durable outbox and query reconciliation semantics.
- Harden the existing proposal/status-only MCP façade with production host
  interoperability tests, delegated-identity policy, rate/size limits, audit
  coverage, and deployment guidance. Never add raw dispatch or model confirmation.
- Add secret-manager clients for `secret://` references and document supported
  rotation behavior.

## Core hardening

- Add a proposal-expiry sweeper; expiry is currently lazy.
- Define retention, archival, legal hold, purge, and external immutable audit policy.
- Add migration/version tooling for registry configuration and provider contract
  rollbacks while historical actions retain their binding version.
- Exercise multi-process and multi-node stores with concurrency, failover, and load
  tests; SQLite remains a single-host reference topology.
- Separate the large FastAPI composition root into route/dependency modules once
  behavior is fully locked by regression tests.

## Regulatory and operational obligations

- Obtain counsel and risk approval for NAM, Regulation E, recording, consent,
  customer notices, approval thresholds, SAR handling, and retention.
- Integrate enterprise OAuth/OIDC, KMS/HSM, managed TLS, secrets, backups, DR,
  monitoring, WORM/SIEM, vulnerability management, and incident response.
- Perform threat modeling and penetration testing against the selected providers
  and deployment topology.

## Explicit non-goals for v3.2

- arbitrary model-created actions or endpoints;
- a visual workflow/policy designer;
- turnkey bank/contact-center deployment;
- packaged PostgreSQL or distributed database support;
- real-time token streaming for consequential responses;
- generic WebSocket provider execution;
- MCP confirmation, execution, or provider-administration tools;
- legal or regulatory certification.
