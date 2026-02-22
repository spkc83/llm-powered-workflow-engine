"""Integration tests for agent definitions and registry loading."""
import textwrap
from pathlib import Path

import pytest

from workflow_engine.procedures.registry import ProcedureRegistry
from workflow_engine.agents.customer_service import create_customer_service_agent
from workflow_engine.agents.fraud_ops import create_fraud_ops_agent
from workflow_engine.agents.router import create_router_agent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CS_YAML = textwrap.dedent("""\
    procedure:
      id: cs_refund
      name: "CS Refund"
      description: "Handle refund requests."
      trigger_intents:
        - refund
        - return
      steps:
        - id: collect
          instruction: Ask for order number.
          action: collect_info
          required_info:
            - order_id
          next_step: lookup
        - id: lookup
          instruction: Look up the order.
          action: tool_call
          tool: lookup_order
          on_success: close
          on_failure: close
        - id: close
          instruction: Close the case.
          action: tool_call
          tool: update_case_status
          on_success: end
          on_failure: end
""")

CS_COMPLAINT_YAML = textwrap.dedent("""\
    procedure:
      id: cs_complaint
      name: "CS Complaint"
      description: "Handle complaints."
      trigger_intents:
        - complaint
      steps:
        - id: greet
          instruction: Greet the customer.
          action: inform
          next_step: end
""")

FRAUD_YAML = textwrap.dedent("""\
    procedure:
      id: fraud_triage
      name: "Fraud Triage"
      description: "Triage fraud alerts."
      trigger_intents:
        - fraud alert
        - suspicious activity
      steps:
        - id: get_alert
          instruction: Retrieve the fraud alert.
          action: tool_call
          tool: get_fraud_alert
          on_success: close
          on_failure: close
        - id: close
          instruction: Close the alert.
          action: tool_call
          tool: close_alert
          on_success: end
          on_failure: end
""")


@pytest.fixture()
def procedures_dir(tmp_path: Path) -> Path:
    (tmp_path / "cs_refund.yaml").write_text(CS_YAML)
    (tmp_path / "cs_complaint.yaml").write_text(CS_COMPLAINT_YAML)
    (tmp_path / "fraud_triage.yaml").write_text(FRAUD_YAML)
    return tmp_path


@pytest.fixture()
def registry(procedures_dir: Path) -> ProcedureRegistry:
    return ProcedureRegistry(str(procedures_dir))


# ---------------------------------------------------------------------------
# ProcedureRegistry integration tests
# ---------------------------------------------------------------------------


class TestRegistryLoadsAllProcedures:
    def test_loads_three_procedures(self, registry: ProcedureRegistry):
        assert len(registry.procedures) == 3

    def test_all_procedure_ids_present(self, registry: ProcedureRegistry):
        assert "cs_refund" in registry.procedures
        assert "cs_complaint" in registry.procedures
        assert "fraud_triage" in registry.procedures

    def test_trigger_intents_indexed(self, registry: ProcedureRegistry):
        intents = registry.get_all_trigger_intents()
        assert "refund" in intents
        assert "complaint" in intents
        assert "fraud alert" in intents

    def test_cs_domain_returns_two_procedures(self, registry: ProcedureRegistry):
        cs_procs = registry.get_procedures_for_domain("cs_")
        assert len(cs_procs) == 2

    def test_fraud_domain_returns_one_procedure(self, registry: ProcedureRegistry):
        fraud_procs = registry.get_procedures_for_domain("fraud_")
        assert len(fraud_procs) == 1


# ---------------------------------------------------------------------------
# Agent factory tests
# ---------------------------------------------------------------------------


class TestCreateCustomerServiceAgent:
    def test_returns_agent_with_name(self, registry: ProcedureRegistry):
        agent = create_customer_service_agent(registry)
        assert agent.name == "customer_service_agent"

    def test_agent_has_tools(self, registry: ProcedureRegistry):
        agent = create_customer_service_agent(registry)
        assert len(agent.tools) > 0

    def test_agent_includes_lookup_order_tool(self, registry: ProcedureRegistry):
        agent = create_customer_service_agent(registry)
        tool_names = {t.__name__ for t in agent.tools}
        assert "lookup_order" in tool_names

    def test_agent_includes_update_case_status_tool(self, registry: ProcedureRegistry):
        agent = create_customer_service_agent(registry)
        tool_names = {t.__name__ for t in agent.tools}
        assert "update_case_status" in tool_names

    def test_agent_instruction_contains_procedure_name(self, registry: ProcedureRegistry):
        agent = create_customer_service_agent(registry)
        assert "CS Refund" in agent.instruction

    def test_agent_description_contains_trigger_intents(self, registry: ProcedureRegistry):
        agent = create_customer_service_agent(registry)
        assert "refund" in agent.description.lower() or "complaint" in agent.description.lower()


class TestCreateFraudOpsAgent:
    def test_returns_agent_with_name(self, registry: ProcedureRegistry):
        agent = create_fraud_ops_agent(registry)
        assert agent.name == "fraud_ops_agent"

    def test_agent_has_tools(self, registry: ProcedureRegistry):
        agent = create_fraud_ops_agent(registry)
        assert len(agent.tools) > 0

    def test_agent_includes_get_fraud_alert_tool(self, registry: ProcedureRegistry):
        agent = create_fraud_ops_agent(registry)
        tool_names = {t.__name__ for t in agent.tools}
        assert "get_fraud_alert" in tool_names

    def test_agent_includes_close_alert_tool(self, registry: ProcedureRegistry):
        agent = create_fraud_ops_agent(registry)
        tool_names = {t.__name__ for t in agent.tools}
        assert "close_alert" in tool_names

    def test_agent_instruction_contains_procedure_name(self, registry: ProcedureRegistry):
        agent = create_fraud_ops_agent(registry)
        assert "Fraud Triage" in agent.instruction


class TestCreateRouterAgent:
    def test_returns_agent_with_name(self, registry: ProcedureRegistry):
        agent = create_router_agent(registry)
        assert agent.name == "router_agent"

    def test_router_has_three_sub_agents(self, registry: ProcedureRegistry):
        agent = create_router_agent(registry)
        assert len(agent.sub_agents) == 3

    def test_sub_agent_names(self, registry: ProcedureRegistry):
        agent = create_router_agent(registry)
        names = {a.name for a in agent.sub_agents}
        assert "customer_service_agent" in names
        assert "fraud_ops_agent" in names
        assert "general_agent" in names

    def test_router_uses_gemini_model(self, registry: ProcedureRegistry):
        agent = create_router_agent(registry)
        assert "gemini" in agent.model.lower()
