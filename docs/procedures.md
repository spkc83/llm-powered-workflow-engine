# Procedure Authoring Guide

Procedures are YAML files that define structured workflows for agents to follow. They live in the `procedures/` directory and are auto-discovered by the procedure registry at startup.

## File Structure

```yaml
procedure:
  id: unique_procedure_id        # Used internally and in APIs
  name: "Human-Readable Name"    # Displayed in UI
  description: "What this procedure handles"
  version: "1.0"                 # Optional, for tracking
  trigger_intents:               # Keywords that activate this procedure
    - keyword one
    - keyword two

  steps:
    - id: step_one
      instruction: >
        Detailed natural language instructions for the agent.
        This is what guides the agent's behavior at this step.
      action: collect_info       # Step type
      required_info:
        - piece_of_info
      next_step: step_two

    - id: step_two
      instruction: >
        Instructions for the next step...
      action: tool_call
      tool: tool_function_name
      on_success: step_three
      on_failure: error_step
```

## Required Top-Level Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique procedure identifier (e.g., `cs_refund`, `fraud_alert_triage`) |
| `name` | string | Human-readable name |
| `description` | string | What the procedure handles |
| `steps` | list | Ordered list of step objects |

## Optional Top-Level Fields

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Version tracking |
| `trigger_intents` | list[string] | Keywords the router uses to activate this procedure |

## Step Types (Actions)

### `collect_info`

The agent needs to gather information from the user before proceeding.

```yaml
- id: greet_and_collect
  instruction: >
    Greet the customer and ask for their order number.
  action: collect_info
  required_info:
    - order_identifier
  next_step: lookup_order
```

| Field | Required | Description |
|-------|----------|-------------|
| `required_info` | yes | List of information items to collect |
| `next_step` | yes | Step to proceed to after collection |

### `tool_call`

The agent calls a tool function to perform an action.

```yaml
- id: lookup_order
  instruction: >
    Look up the order using the provided order number.
  action: tool_call
  tool: lookup_order
  on_success: check_eligibility
  on_failure: order_not_found
```

| Field | Required | Description |
|-------|----------|-------------|
| `tool` | yes | Name of the tool function to call |
| `on_success` | yes | Step to go to if the tool succeeds |
| `on_failure` | yes | Step to go to if the tool fails |

### `evaluate`

The agent evaluates conditions and branches accordingly.

```yaml
- id: check_eligibility
  instruction: >
    Evaluate whether the order qualifies for a refund.
  action: evaluate
  conditions:
    - if: "order_date within 30 days AND status in [delivered, shipped]"
      next_step: process_refund
    - if: "order_date outside 30 days"
      next_step: deny_refund_window
    - if: "order_status == processing"
      next_step: cancel_order
```

| Field | Required | Description |
|-------|----------|-------------|
| `conditions` | yes | List of condition objects with `if` and `next_step` |

Natural-language conditions are conversational guidance only. They may help the
model decide what clarification to propose, but they cannot authorize an action.
Production eligibility and branching for consequential work must be implemented
as typed deterministic decisions in `workflow_engine/core` and covered by replay
tests.

### `inform`

The agent communicates information to the user and optionally presents choices.

```yaml
- id: deny_refund_window
  instruction: >
    Inform the customer their order is outside the refund window.
    Offer alternatives.
  action: inform
  options:
    - label: "Customer accepts store credit"
      next_step: offer_store_credit
    - label: "Customer requests escalation"
      next_step: escalate_case
```

| Field | Required | Description |
|-------|----------|-------------|
| `options` | no | List of option objects with `label` and `next_step` |
| `next_step` | no | Used when there are no options (linear flow) |

## Step Fields Reference

Every step must have these fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique step identifier within the procedure |
| `instruction` | string | Natural language guidance for the agent |
| `action` | string | One of: `collect_info`, `tool_call`, `evaluate`, `inform` |

## Navigation

Steps connect to each other via these fields:

| Field | Used By | Description |
|-------|---------|-------------|
| `next_step` | `collect_info`, `inform` | Next step in linear flow |
| `on_success` | `tool_call` | Step after successful tool execution |
| `on_failure` | `tool_call` | Step after failed tool execution |
| `conditions[].next_step` | `evaluate` | Step for each condition branch |
| `options[].next_step` | `inform` | Step for each user choice |

Use `"end"` as a target to terminate the procedure.

## Validation

The procedure loader validates:

- All required fields are present
- All `next_step`, `on_success`, `on_failure` references point to valid step IDs or `"end"`
- `tool_call` steps have a `tool` field
- Condition and option targets are valid

Invalid procedures raise `ValueError` at load time with a descriptive message.

## Naming Conventions

- **Procedure IDs**: Use domain prefix — `cs_` for customer service, `fraud_` for fraud ops
- **Step IDs**: Use snake_case descriptive names (e.g., `greet_and_collect`, `assess_risk`)
- **Tool names**: Must match the Python function name in the tool module

## Instruction Writing Tips

1. **Be specific** — tell the agent exactly what to do, what to say, and what to look for
2. **Include examples** — provide example phrases the agent can adapt
3. **Set the tone** — describe the emotional register (empathetic, professional, factual)
4. **Explain branching** — when the step has conditions, explain what each path means
5. **Reference tools** — mention what data the tool will return and how to use it
6. **Keep it conversational** — instruct the agent not to read steps verbatim

## Example: Minimal Procedure

```yaml
procedure:
  id: cs_simple_inquiry
  name: "Customer Service - Simple Inquiry"
  description: "Answer basic customer questions"
  trigger_intents:
    - question
    - help
    - info

  steps:
    - id: greet
      instruction: >
        Greet the customer and ask how you can help them today.
      action: collect_info
      required_info:
        - question
      next_step: lookup_kb

    - id: lookup_kb
      instruction: >
        Search the knowledge base for articles relevant to the customer's question.
        Present the most relevant information in a helpful, conversational way.
      action: tool_call
      tool: get_knowledge_article
      on_success: close
      on_failure: close

    - id: close
      instruction: >
        Ask if the customer needs anything else. Thank them and close the conversation.
      action: inform
      next_step: end
```

## Existing Procedures

| File | ID | Domain | Steps |
|------|----|--------|-------|
| `customer_service_refund.yaml` | `cs_refund` | Customer Service | 8 steps — greet, lookup, eligibility check, refund/deny/cancel, escalate, close |
| `customer_service_complaint.yaml` | `cs_complaint` | Customer Service | 6 steps — greet, classify, lookup context, resolve, escalate, close |
| `cs_eft_dispute.yaml` | `cs_eft_dispute` | Customer Service | 9 steps — collect info, lookup, assess eligibility (Reg E tiers), file dispute, provisional credit, deny late/redirect non-EFT, escalate, close |
| `fraud_ops_alert_triage.yaml` | `fraud_alert_triage` | Fraud Ops | 9 steps — receive alert, review, gather evidence, check devices, assess risk, flag/clear/escalate, document, close |

## Governed policy boundary

YAML procedure prose remains conversational guidance. Consequential eligibility,
fact authority, parameter provenance, idempotency, and connector postconditions
belong in typed core services and signed policy packages—not natural-language
`evaluate` conditions.

The initial policy lifecycle is `draft -> approved -> active -> retired`. The
package author and approver must be different identities. Approved and active
packages are HMAC signed using canonical JSON. Production signing keys must be
loaded from a secret manager; never place them in YAML, prompts, ADK state, or
source control.

For compound intents, the deterministic router selects one primary procedure and
explicit subprocedures, then locks every version for the case. It never silently
switches an active case to a newer policy version.
