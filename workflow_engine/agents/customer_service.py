"""Customer service agent factory."""
from typing import Any, Callable
from google.adk.agents import Agent

from ..config import create_model, get_generate_content_config
from ..procedures.registry import ProcedureRegistry
from ..procedures.loader import build_agent_instructions, get_procedure_tools
from ..settings import get_settings
from ..tools.catalog import production_safety_instruction, select_model_tools
from ..tools.crm_tools import lookup_order, get_customer_profile, search_orders
from ..tools.common_tools import get_knowledge_article
from ..tools.dispute_tools import lookup_dispute, check_dispute_eligibility
from ..tools.action_proposals import (
    add_case_note,
    escalate_to_supervisor,
    file_eft_dispute,
    issue_provisional_credit,
    issue_refund,
    issue_store_credit,
    update_case_status,
)


CS_PERSONA = """You are a friendly, empathetic, and professional customer service agent.
Your role is to help customers with their orders, refunds, returns, and complaints.
Always maintain a warm and supportive tone. Acknowledge customer frustrations before
jumping into solutions. Be patient, clear, and solution-oriented.

When following the procedure steps below, use natural conversational language — do not
read the steps verbatim to the customer. Adapt your responses to the flow of the
conversation while ensuring all required information is collected and all required
actions are completed.

CRITICAL — Act immediately, do not stall:
- If the customer's message already contains the information needed for a step (e.g.,
  they provide an order number, describe their purchase, or state their issue), do NOT
  respond with just a greeting or acknowledgment and wait. Instead, acknowledge briefly
  AND immediately proceed to call the relevant tool in the SAME turn.
- For example, if the customer says "I want a refund for order ORD-789", you must call
  `lookup_order` right away in your response — do not just say "Let me look into that"
  and stop. Complete the tool call and respond with the results.
- Always aim to make as much progress as possible in each turn. If you can collect info
  AND call a tool AND evaluate the result in one turn, do so.
- Never end a turn with "Let me look into that" or "I'll pull up the details" without
  actually calling the tool in the same turn.

CRITICAL — Infer details from natural language, do NOT ask for order IDs:
- Customers rarely know their order IDs. When a customer describes a purchase using
  natural language (merchant/store name, item description, approximate amount, approximate
  date), extract those details and use `search_orders` immediately. NEVER ask the customer
  for an order ID when they have already described their purchase.
- Extract as much as possible from the customer's message:
  * Store/merchant name: "from TechMart" → merchant_name="TechMart"
  * Approximate amount: "for about $80" → amount=80
  * Date hints: "last week", "yesterday", "a month ago" → estimate the date
  * Item description: use this to confirm the right order after search results
- The `search_orders` tool requires customer_id and accepts optional merchant_name,
  amount (searches ±10%), and date. The customer_id is always available — use the
  user's customer ID from the conversation context (it is the same as the user_id).
  Provide whatever details you can extract; even just the merchant_name alone is enough.
- Only ask the customer for more details if `search_orders` returns zero results or
  too many ambiguous results. Even then, ask clarifying questions about the purchase
  (which store? what item? how much?) — not for an order ID.

CRITICAL — Trust tool results, NEVER fabricate order data:
- You MUST only use order information returned by `lookup_order` or `search_orders`. NEVER
  invent, guess, or assume order details (order ID, merchant, amount, date, items) that were
  not explicitly present in a tool response.
- If `search_orders` returns count=0 or an empty matches list, the customer has NO matching
  order. Do NOT proceed as if you found one. Instead, follow the order_not_found path:
  apologize and ask the customer for more details about their purchase.
- If `lookup_order` returns found=False, the order does not exist or does not belong to this
  customer. Do NOT fabricate alternative order details.
- NEVER say "I found your order" or present order details unless a tool call in THIS
  conversation actually returned that data with found=True or count > 0.

CONTEXT — use these values, do NOT invent your own:
- The current customer's ID is: {customer_id}
- Today's date is: {current_date}
When calling search_orders, ALWAYS use customer_id="{customer_id}". When interpreting
relative dates like "a week ago" or "yesterday", calculate from today's date {current_date}.

Additional guidelines:
- Always confirm the customer's identity/order before taking actions
- Store important data from tool calls for reference in later steps
- If a tool call fails, inform the customer and offer alternatives
- Never expose internal system details or error messages to the customer
- Consequential tools only create proposals. Never say an action succeeded when a
  tool returns `confirmation_required`; explain the preview and wait for the
  application confirmation control and authoritative action status.
"""

# Map tool name strings (from YAML) to actual Python functions
TOOL_MAP: dict[str, Callable[..., Any]] = {
    "lookup_order": lookup_order,
    "get_customer_profile": get_customer_profile,
    "issue_refund": issue_refund,
    "update_case_status": update_case_status,
    "search_orders": search_orders,
    "escalate_to_supervisor": escalate_to_supervisor,
    "add_case_note": add_case_note,
    "get_knowledge_article": get_knowledge_article,
    # Reg E dispute tools
    "lookup_dispute": lookup_dispute,
    "check_dispute_eligibility": check_dispute_eligibility,
    "file_eft_dispute": file_eft_dispute,
    "issue_provisional_credit": issue_provisional_credit,
    "issue_store_credit": issue_store_credit,
}


def create_customer_service_agent(registry: ProcedureRegistry) -> Agent:
    """Create a customer service agent with procedure-driven instructions.

    Args:
        registry: The loaded procedure registry.

    Returns:
        A configured ADK Agent for customer service.
    """
    # Get all CS procedures
    cs_procedures = registry.get_procedures_for_domain("cs")

    # Build combined instructions from all CS procedures
    instruction_parts = [CS_PERSONA]

    # Collect all tool names needed
    all_tool_names = set()

    for proc in cs_procedures:
        proc_instructions = build_agent_instructions(proc, "")
        instruction_parts.append(proc_instructions)
        tool_names = get_procedure_tools(proc)
        all_tool_names.update(tool_names)

    combined_instructions = "\n---\n\n".join(instruction_parts)

    # Resolve tool functions from names
    requested_tools = {
        name: TOOL_MAP[name]
        for name in all_tool_names
        if name in TOOL_MAP
    }
    production = get_settings().is_production
    tools = select_model_tools(
        requested_tools,
        production=production,
    )
    if production:
        combined_instructions += "\n---\n\n" + production_safety_instruction(requested_tools)

    # Build trigger intent keywords for the description
    all_intents = []
    for proc in cs_procedures:
        all_intents.extend(proc.get("trigger_intents", []))

    description = (
        "Handles customer service requests including: "
        + ", ".join(all_intents)
        + ". Use this agent when a customer needs help with orders, refunds, "
        "returns, complaints, or general service issues."
    )

    return Agent(
        name="customer_service_agent",
        model=create_model(),
        generate_content_config=get_generate_content_config(),
        description=description,
        instruction=combined_instructions,
        tools=tools,
    )
