# Core Engine Architecture

## Decisions

- **Workflow ownership:** a narrow transactional state machine inside the modular
  monolith. Temporal remains a future adapter when durable timers and operational
  scale justify another control plane; Camunda is not selected because the core
  engine does not require BPMN authoring or a licensed production platform.
- **Channels:** chat and IVR share one message envelope, inbox dedupe, identity,
  policy, action, response-contract, and handoff model. IVR media/ASR stays outside
  ADK graphs because ADK 2.1 graph workflows do not support Live streaming.
- **Jurisdiction:** `NAM` is the initial policy profile. Regulated content remains
  versioned policy data; jurisdiction-specific recording and disclosure fixtures
  must be added before connecting a production IVR provider.
- **Persistence:** the kernel depends on `CoreStore`. SQLite is built in and is the
  default. Other databases register an adapter by URL scheme. ADK 2.x sessions use
  a separate async database URL so ADK schema changes cannot migrate domain data.
- **Policy governance:** one author and a different approver; approved/active
  packages are HMAC signed. Production signing keys must come from a secret store.
- **Human handoff:** an internal queue port and durable lifecycle are authoritative;
  a vendor adapter can be added without changing customer-visible status semantics.

## Authority boundaries

`workflow_engine.core.kernel` owns case versions, facts, action authorization,
idempotency, and outcomes. `workflow_engine.core.gateway` owns dispatch and
reconciliation. `workflow_engine.core.adk2` emits proposals and composed text only.
No ADK node, prompt, callback, or session value can directly create an authorized
action record.

## Implemented invariants

1. Asserted facts cannot satisfy verified preconditions.
2. Procedure versions are locked for a case route; compound intents are explicit.
3. Stable idempotency keys return the original action and never redispatch it.
4. Action status is `authorized -> dispatched -> succeeded|failed|unknown`, with
   unknown outcomes reconciled without another dispatch.
5. Duplicate provider message IDs are suppressed across chat and IVR.
6. A transfer is not accepted until an agent identity durably accepts it.
7. Low-confidence or interrupted IVR transcripts remain asserted and require
   readback; they cannot directly authorize an action.
8. Consequential success claims require an authoritative succeeded/reconciled state.

## External conformance gates

The core is provider-neutral. Production completion still requires fixtures and
credentials for the selected telephony/chat providers, ASR behavior, recording
consent by NAM sub-jurisdiction, delivery receipts, and the chosen human-agent
system. These are adapter conformance tasks, not core-engine authority changes.
