# Policy, Jurisdiction, and Data Governance

## Simple policy lifecycle

The governed lifecycle is `draft -> approved -> active -> retired`.

- Authenticated actor creates the draft and becomes author.
- A different authenticated actor approves it.
- Approval and activation sign canonical JSON using HMAC-SHA256.
- `signing_key_id` identifies the external key version; key material is never stored
  in policy JSON, source, prompts, or ADK state.
- `POLICY_VERIFICATION_KEYS` retains old key IDs for verification during rotation;
  the current key alone signs new lifecycle states.
- Activation atomically retires the previous package for the same
  procedure/jurisdiction.
- Active cases retain their procedure/package version; migration is explicit.

Use `/api/v1/policies` APIs or an equivalent administrative integration. The
in-memory registry is hydrated from `PolicyRepository` at startup.

## NAM profile

`NAM` is an operational umbrella profile, not a legal opinion. The built-in fixture
covers engineering controls for US/Canada/Mexico and defaults to recording and
transcription consent, secure DTMF, finite transcript retention, quiet hours, and
contact-frequency limits. Replace it through `JURISDICTION_CONFIG_PATH` with a
counsel-approved YAML/JSON profile before production.

`JURISDICTION_ENFORCE` defaults false in development and true elsewhere. Current
controls are visible at `/api/v1/jurisdictions/current`.

## Ownership

- Product owns customer outcomes and enabled channels.
- Operations owns procedures, queues, and reconciliation deadlines.
- Risk/compliance owns decision/evidence/disclosure rules and approval.
- Legal/privacy approves jurisdiction, recording, retention, and correction.
- Security owns identity, callback authentication, secrets, and keys.
- Engineering owns deterministic runtime, adapters, availability, and rollback.
- Release owner accepts evidence and residual risk.

## Evidence and privacy

Store references and minimum necessary evidence rather than raw media or regulated
narratives. SAR requests accept `narrative_ref`, not narrative text. Secret DTMF is
redacted before transcript or log creation. Apply RBAC, retention, legal hold,
correction/supersession, and deletion rules per evidence class.

The local audit hash chain detects modification but must be combined with immutable
backup or external anchoring for stronger tamper resistance.
