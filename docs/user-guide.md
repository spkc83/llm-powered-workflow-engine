# User Guide

## Who the system serves

The application supports customer self-service and authorized staff-assisted
service. The authenticated actor and serviced customer are separate identities;
staff access requires customer-read permission, while customers can access only
their own records.

## Chat

1. Select or authenticate the customer.
2. Send a message. Clients should include a stable `message_id` when retrying.
3. Continue with the returned `session_id`.
4. For a consequential action, review the requested action and provide explicit
   confirmation through the structured action flow. Conversational wording alone
   is not treated as authorization.
5. Trust action status only when the application reports `succeeded` or
   `reconciled`. `Requested`, `authorized`, `dispatched`, and `unknown` are not
   success states.

A repeated provider message ID is suppressed. A session belongs to one
actor/customer pair and cannot be reused to access another customer.

## IVR

The IVR adapter accepts final ASR transcripts and metadata from a telephony
provider. Low-confidence or interrupted values require readback. Spoken numbers,
account identifiers, dates, and action confirmations remain customer assertions
until confirmed by readback/DTMF or an authoritative system lookup.

The engine does not persist raw audio by default. Provider integrations must apply
recording-consent, retention, and secret-redaction rules for the applicable North
American sub-jurisdiction.

## Human assistance

A transfer starts as `requested`. The customer must not be told they are connected
until an agent durably accepts it. Handoff context contains the case, verified
facts, unresolved questions, policy version, and action status; generated summaries
remain proposals.

## Corrections and failures

- Corrected customer statements supersede assertions; they do not overwrite
  verified system records without deterministic validation.
- An `unknown` action outcome is reconciled without issuing the action again.
- If identity, evidence, consent, or policy is missing, the action fails closed and
  the conversation should explain the next safe step.
