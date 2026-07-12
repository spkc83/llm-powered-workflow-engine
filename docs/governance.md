# Policy and Governance

## NAM profile

`NAM` is the initial umbrella jurisdiction. Production packages must name the
applicable sub-jurisdiction when rules differ. Legal/compliance owners approve
recording consent, disclosures, retention, Reg E/EFTA behavior, privacy, and
language/accessibility content.

## Package lifecycle

`draft -> approved -> active -> retired`

- The author and approver must be different identities.
- Approved/active packages use canonical JSON and HMAC-SHA256 signatures.
- Signing keys live in a secret manager and never in source, prompts, YAML, or ADK
  state.
- Active cases retain their package version. Migration is an explicit tested event.
- Model-generated policy is draft-only.

## Ownership

- Product: customer outcomes and channel scope.
- Domain operations: procedures and reconciliation deadlines.
- Risk/compliance: decisions, evidence, disclosures, approval.
- Security: identity, keys, permissions, threat model.
- Engineering: compiler/runtime, connectors, availability, rollback.
- Release owner: signs the evidence, CX, queue, cost, and error-budget gate.

## Evidence and privacy

Store only evidence needed to reproduce decisions. Avoid permanent raw transcripts
or audio by default. Apply access control, retention, redaction, legal hold, and
customer correction/supersession policies to every evidence class.
