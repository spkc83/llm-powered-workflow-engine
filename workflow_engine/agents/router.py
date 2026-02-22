"""Router agent and general Q&A agent definitions."""
from google.adk.agents import Agent

from ..config import create_model, get_generate_content_config
from ..procedures.registry import ProcedureRegistry
from .customer_service import create_customer_service_agent
from .fraud_ops import create_fraud_ops_agent


ROUTER_INSTRUCTION = """You are the main router agent for a customer service and fraud operations system.
Your job is to understand what the user needs and direct them to the right specialist agent.

You have the following specialist agents available:
1. **Customer Service Agent** — Handles customer inquiries about orders, refunds, returns,
   complaints, and general service issues.
2. **Fraud Operations Agent** — Handles fraud alert triage, suspicious activity investigation,
   and account security actions.
3. **General Assistant** — Handles general questions, small talk, and anything that doesn't
   fit the other categories.

Routing guidelines:
- If the user mentions refunds, returns, orders, complaints, or service issues → Customer Service Agent
- If the user mentions fraud alerts, suspicious activity, account security, or investigation → Fraud Operations Agent
- For greetings, general questions, or unclear intent → General Assistant
- If you're unsure, ask the user a clarifying question before routing

You can handle basic greetings yourself (e.g., "Hello", "How are you?") before routing
to a specialist. Keep your responses brief when routing — the specialist agent will
handle the detailed interaction.
"""


def create_general_agent() -> Agent:
    """Create a general-purpose Q&A agent for fallback handling."""
    return Agent(
        name="general_agent",
        model=create_model(),
        generate_content_config=get_generate_content_config(),
        description=(
            "Handles general questions, greetings, and conversations that don't "
            "relate to customer service orders/refunds or fraud operations. "
            "Use this agent for small talk, general inquiries, or when the user's "
            "intent is unclear."
        ),
        instruction="""You are a helpful general assistant. You can answer general questions,
engage in small talk, and help users understand what services are available.

If a user asks about something that would be better handled by a specialist
(customer service or fraud operations), let them know and suggest they describe
their specific need so you can connect them with the right team.

Available services:
- Customer Service: Help with orders, refunds, returns, complaints
- Fraud Operations: Fraud alert triage, suspicious activity investigation

Keep responses friendly, concise, and helpful.""",
    )


def create_router_agent(registry: ProcedureRegistry) -> Agent:
    """Create the top-level router agent with all sub-agents.

    Args:
        registry: The loaded procedure registry.

    Returns:
        The root router Agent with sub-agents configured.
    """
    cs_agent = create_customer_service_agent(registry)
    fraud_agent = create_fraud_ops_agent(registry)
    general_agent = create_general_agent()

    return Agent(
        name="router_agent",
        model=create_model(),
        generate_content_config=get_generate_content_config(),
        description="Main router that directs users to the appropriate specialist agent.",
        instruction=ROUTER_INSTRUCTION,
        sub_agents=[cs_agent, fraud_agent, general_agent],
    )
