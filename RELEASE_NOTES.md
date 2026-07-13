# LLM-Powered Workflow Engine v3.1.0

v3.1 closes the largest usability and honesty gaps found in the end-to-end v3 audit.

## Application changes

- The Shiny development/operator console now uses canonical `/api/v1` routes,
  honors Docker `BACKEND_URL`, supports an optional bearer token, and includes a
  system status view.
- `UPSTREAM_MODE=provider` now loads a trusted complete `ProviderBundle` for STT,
  TTS, telephony, chat delivery, handoff, authoritative resources, and actions.
- Action delivery and reconciliation can run continuously as
  `python -m workflow_engine.worker` and have a dedicated Compose service.
- `/ready` verifies storage, active policy, and provider-bundle state separately
  from process liveness.
- Production reference Compose no longer advertises four API workers on SQLite.

## Documentation

The README was rewritten and the documentation now includes explicit current-state,
configuration, UI, testing, architecture, provider, storage, API, and operations
boundaries. Features are classified as implemented, sandbox, deployment-supplied,
partial, or out of scope.

## Verification

- 426 automated tests pass.
- Ruff, scoped mypy, compileall, Docker Compose validation, documentation parity,
  and diff checks pass.
- The Shiny app imports and a live local server smoke renders its HTML.

## Remaining deployment obligations

No vendor adapters or credentials ship in the repository. Real provider bundles,
TLS, secret management, monitoring/export, approved database adapters, retention,
and legal/regulatory approval remain deployment responsibilities.
