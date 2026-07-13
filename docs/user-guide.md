# User and Service-Operator Guide

## What v3.2 does

The application assists customers and authorized staff through chat and IVR. The
model interprets requests and drafts responses; deterministic code controls money,
account, regulatory, fraud, and handoff state.

## Chat

1. Authenticate or select the serviced customer.
2. Send a message with a stable provider message ID; reuse it on retry.
3. Continue using the returned conversation/session ID.
4. Review structured action details and consent/approval prompts.
5. If an action card appears, review the authoritative preview and expiry.
6. Confirm or cancel using the host control; the assistant cannot confirm for you.
7. Treat proposal `confirmed` as submitted, not completed. Treat only action
   `succeeded` or `reconciled` as completed.

A repeated ID is suppressed. Out-of-order provider messages wait in quarantine.
Staff and customer identities remain separate; a conversation cannot be reused for
another customer.

## IVR

The system receives a transcript from a configured STT/telephony adapter. The
built-in development stub does not listen to audio. Low-confidence or interrupted
speech requires readback. Recording/transcription consent may be required before
processing. Use secure DTMF collection for secrets; do not speak or log full
credentials/card data.

## Actions

Refund, store credit, dispute, provisional credit, account restriction, alert
closure, SAR submission, case changes, and escalation follow the action gateway.
The application reloads upstream data and checks policy, permission, fact evidence,
consent/approval, and idempotency. An `unknown` outcome means the provider may have
committed; operations reconcile rather than repeat it.

## Human assistance

Handoff state is shown honestly: requested, queued, accepted, connected, and
resolved are distinct. If the queue times out or fails, the application offers
reassignment, callback/bot re-entry, or another approved option.

## Development sandbox

In development, Shiny demonstrates chat → proposal → confirmation → typed gateway
→ local SQLite effect and action history. Swagger can seed resources and failure
scenarios. These are local effects, not evidence of a real bank/provider refund,
credit, filing, restriction, delivery, or human connection.

## Corrections and support

Customer corrections supersede assertions but cannot overwrite verified upstream
records without validation. Report issues using sanitized correlation, message,
case, and action IDs; never include secrets, raw audio, SAR narrative, or customer
data in public issues.
