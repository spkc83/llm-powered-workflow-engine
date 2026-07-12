# Security Policy

## Supported versions

Security fixes are provided for the latest v2.x release.

## Reporting

Do not open public issues for vulnerabilities or include customer data, credentials,
policy keys, transcripts, or connector payloads. Use GitHub private vulnerability
reporting for this repository. Include affected version, reproduction, impact, and
suggested mitigation when available.

## Security model

Models, prompts, channel payloads, tool arguments, and ADK state are untrusted.
Consequential actions require authenticated actor/customer binding, permission,
verified facts and evidence, approved policy, explicit consent/approval where
required, stable idempotency, and connector postconditions. See
`docs/threat-model.md`.
