# Security Policy

## Supported versions

Security fixes are provided for the latest v3.x release.

## Reporting

Use GitHub private vulnerability reporting. Do not open public issues containing
customer data, credentials, policy keys, transcripts, raw audio, DTMF, SAR
narratives, provider payloads, or exploit details. Include affected version,
minimal sanitized reproduction, impact, correlation/action IDs, and mitigation when
available.

## Security model

Models, prompts, channel payloads, tool arguments, and ADK state are untrusted.
Consequential actions require authenticated actor/customer binding, RBAC, active
signed policy, authoritative resource reload, verified fact provenance,
consent/approval where required, idempotency, and connector postconditions.

Consequential model tools create proposal intent only. Confirmation is a separate
authenticated host operation that rechecks actor/customer ownership, expiry,
authoritative resource and connector versions, policy, consent, and approval. The
model cannot choose an endpoint, credential, binding, identity, or evidence.

Declarative REST bindings require closed action names, allowed hosts, HTTPS in
production, secret references, pinned OpenAPI operations, bounded timeout,
idempotency, and reconciliation. Generic WebSocket provider execution is not
implemented; custom Python connectors are trusted code and require independent
review. The authenticated MCP façade can prepare/read proposals only and rejects
trusted context in tool arguments; it exposes no confirmation or execution tool.

Sandbox adapters are development-only and rejected in production. Provider
callbacks require deployment-specific authentication and replay protection. IVR
adapters must redact secrets before transcripts/logs. Operational APIs require
administrative network and identity controls.

Audit hash chaining detects local content/link tampering but is not immutable
storage; production requires protected retention, backup, and preferably external
anchoring. See [threat model](docs/threat-model.md) and
[integration guide](docs/integration-guide.md).
