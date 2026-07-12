# Phase 0 Trust and Threat Model

This document defines the initial trust boundary for the modernization plan. It
describes current constraints; it does not claim that the prototype is ready for
consequential production actions.

## Target safety claim

Model, prompt, ADK session, and callback output may propose facts or actions, but
cannot independently authorize a consequential business action. Consequential
tools remain unavailable to production model agents until an action gateway
enforces typed authorization, verified parameter provenance, consent or approval,
idempotency, and outcome reconciliation.

## Trusted components and identities

- The authenticated actor is the JWT subject and role produced by the auth layer.
- The serviced customer is a separate identity selected by the current operator
  UI and carried in the request as `user_id`.
- Database records are authoritative only when reloaded inside a deterministic
  command or decision boundary; mutable ADK session state is not authoritative.
- Connector credentials, policy signing keys, and approval identities must remain
  outside model-visible state and prompts.
- The model, prompt text, tool arguments, attachments, channel payloads, and ADK
  resume events are treated as attacker-influenced inputs.

## Primary threats

| Threat | Current exposure | Phase 0 control |
| --- | --- | --- |
| Prompt injection invokes a write tool | Domain agents expose broad tool unions | `workflow_engine.tools.catalog` classifies all exposed tools and removes consequential tools from production agents. |
| Unclassified tool is added silently | Tool maps and YAML can evolve independently | Catalog coverage tests fail when model-exposed tool names and inventory diverge. |
| Duplicate or resumed action repeats a side effect | Current write tools lack stable business idempotency keys | Inventory records idempotency as not implemented; those tools remain production-disabled. |
| Mutable session data supplies action parameters | Refund and credit tools read amounts/payment details from session state | Production model access is frozen pending transactional reload and an action gateway. |
| Actor impersonates a customer | REST/WS payload `user_id` is currently trusted as customer/session identity | Not resolved in this slice; authenticated actor/customer delegation and tenant binding are required before production chat is enabled. |
| REST and WS apply different auth/safety semantics | HTTP middleware does not establish equivalent WS identity and WS uses a reduced guardrail path | Consequential WS tools are frozen; a shared conversation service remains required. |
| External action succeeds with an ambiguous response | No requested/authorized/dispatched/unknown/reconciled lifecycle exists | Consequential actions remain production-disabled until Phase 1 implements lifecycle and reconciliation. |

## Current production safety freeze

The catalog permits model exposure only for classified non-consequential reads in
the production environment. This is containment, not authorization: the read
functions still need endpoint/actor permission enforcement and tenant/customer
binding before a production release.

## Required follow-ups

1. Define a canonical `ActorContext` and `CustomerContext`, tenant binding, staff
   delegation rules, customer self-service claims, and step-up assurance.
2. Authenticate WebSocket handshakes and make REST/WS use the same turn pipeline.
3. Implement the refund vertical slice with transactional ownership/eligibility
   reload, procedure/evidence references, stable idempotency, and reconciliation.
4. Replace direct model write tools with narrow action-gateway command DTOs.
5. Produce a fully resolved, hash-locked dependency set for each supported runtime
   platform before release.
