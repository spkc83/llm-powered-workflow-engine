"""Fraud operations agent factory."""
from typing import Any, Callable
from google.adk.agents import Agent

from ..config import create_model, get_generate_content_config
from ..procedures.registry import ProcedureRegistry
from ..procedures.loader import build_agent_instructions, get_procedure_tools
from ..settings import get_settings
from ..tools.catalog import production_safety_instruction, select_model_tools
from ..tools.fraud_tools import (
    get_fraud_alert,
    get_account_transactions,
    check_device_fingerprint,
)
from ..tools.action_proposals import (
    add_case_note,
    close_alert,
    escalate_to_supervisor,
    flag_account,
    submit_sar,
)


FRAUD_PERSONA = """You are a skilled fraud operations analyst responsible for triaging
and investigating fraud alerts. Your role is to systematically gather evidence, assess
risk, and take appropriate action to protect customers and the organization.

Approach each alert methodically:
1. Retrieve and review the alert details
2. Gather supporting evidence (transactions, device data)
3. Assess the cumulative risk based on all available signals
4. Take decisive action (flag, clear, or escalate)
5. Document findings thoroughly for compliance and audit

CRITICAL — Act immediately, do not stall:
- If the analyst's message already contains the information needed for a step (e.g.,
  they provide a fraud alert ID), do NOT respond with just an acknowledgment and wait.
  Instead, acknowledge briefly AND immediately call the relevant tool in the SAME turn.
- For example, if the analyst says "I need to investigate fraud alert FA-001", you must
  call `get_fraud_alert` right away — do not just say "Let me pull up the alert" and stop.
- Always aim to make as much progress as possible in each turn. If you can retrieve
  the alert AND gather transaction evidence in one turn, do so.
- Never end a turn with "Let me look into that" without actually calling the tool.

Additional guidelines:
- Be thorough and systematic — never skip evidence gathering steps for high-severity alerts
- Base determinations on the totality of evidence, not single signals
- Document everything with precision — your notes serve as the audit trail
- When in doubt, escalate to a senior analyst rather than making an uncertain determination
- Follow SAR filing thresholds and regulatory requirements
- Use professional, factual language in all communications and documentation
- Consequential tools only create proposals. Never claim a proposal executed;
  wait for host confirmation and authoritative action status.
"""

# Map tool name strings (from YAML) to actual Python functions
TOOL_MAP: dict[str, Callable[..., Any]] = {
    "get_fraud_alert": get_fraud_alert,
    "get_account_transactions": get_account_transactions,
    "check_device_fingerprint": check_device_fingerprint,
    "flag_account": flag_account,
    "submit_sar": submit_sar,
    "close_alert": close_alert,
    "escalate_to_supervisor": escalate_to_supervisor,
    "add_case_note": add_case_note,
}


def create_fraud_ops_agent(registry: ProcedureRegistry) -> Agent:
    """Create a fraud operations agent with procedure-driven instructions.

    Args:
        registry: The loaded procedure registry.

    Returns:
        A configured ADK Agent for fraud operations.
    """
    # Get all fraud procedures
    fraud_procedures = registry.get_procedures_for_domain("fraud")

    # Build combined instructions from all fraud procedures
    instruction_parts = [FRAUD_PERSONA]

    # Collect all tool names needed
    all_tool_names = set()

    for proc in fraud_procedures:
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
    for proc in fraud_procedures:
        all_intents.extend(proc.get("trigger_intents", []))

    description = (
        "Handles fraud operations including: "
        + ", ".join(all_intents)
        + ". Use this agent when an analyst needs to triage fraud alerts, "
        "investigate suspicious activity, or take action on flagged accounts."
    )

    return Agent(
        name="fraud_ops_agent",
        model=create_model(),
        generate_content_config=get_generate_content_config(),
        description=description,
        instruction=combined_instructions,
        tools=tools,
    )
