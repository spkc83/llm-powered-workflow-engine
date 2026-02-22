"""Customer service agent factory."""
from google.adk.agents import Agent

from ..config import create_model, get_generate_content_config
from ..procedures.registry import ProcedureRegistry
from ..procedures.loader import build_agent_instructions, get_procedure_tools
from ..tools.crm_tools import lookup_order, get_customer_profile, issue_refund, update_case_status, search_orders
from ..tools.common_tools import escalate_to_supervisor, add_case_note, get_knowledge_article


CS_PERSONA = """You are a friendly, empathetic, and professional customer service agent.
Your role is to help customers with their orders, refunds, returns, and complaints.
Always maintain a warm and supportive tone. Acknowledge customer frustrations before
jumping into solutions. Be patient, clear, and solution-oriented.

When following the procedure steps below, use natural conversational language — do not
read the steps verbatim to the customer. Adapt your responses to the flow of the
conversation while ensuring all required information is collected and all required
actions are completed.

Important guidelines:
- Always confirm the customer's identity/order before taking actions
- Store important data from tool calls for reference in later steps
- If a tool call fails, inform the customer and offer alternatives
- Never expose internal system details or error messages to the customer
"""

# Map tool name strings (from YAML) to actual Python functions
TOOL_MAP = {
    "lookup_order": lookup_order,
    "get_customer_profile": get_customer_profile,
    "issue_refund": issue_refund,
    "update_case_status": update_case_status,
    "search_orders": search_orders,
    "escalate_to_supervisor": escalate_to_supervisor,
    "add_case_note": add_case_note,
    "get_knowledge_article": get_knowledge_article,
    # issue_store_credit is referenced in YAML but not implemented;
    # the agent will use issue_refund or escalate as alternatives
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
    tools = []
    seen = set()
    for name in sorted(all_tool_names):
        if name in TOOL_MAP and name not in seen:
            tools.append(TOOL_MAP[name])
            seen.add(name)

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
