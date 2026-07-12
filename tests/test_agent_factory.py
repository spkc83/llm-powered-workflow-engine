"""Tests for agent factory functions using the canonical module layout."""
import pytest
from pathlib import Path

from workflow_engine.procedures.registry import ProcedureRegistry

PROCEDURES_DIR = str(Path(__file__).parent.parent / "procedures")


@pytest.fixture(scope="module")
def registry():
    return ProcedureRegistry(PROCEDURES_DIR)


class TestCreateCustomerServiceAgent:
    def test_agent_has_name(self, registry):
        from workflow_engine.agents.customer_service import create_customer_service_agent
        agent = create_customer_service_agent(registry)
        assert agent.name == "customer_service_agent"

    def test_agent_has_tools(self, registry):
        from workflow_engine.agents.customer_service import create_customer_service_agent
        agent = create_customer_service_agent(registry)
        assert len(agent.tools) > 0

    def test_agent_instruction_contains_procedure_steps(self, registry):
        from workflow_engine.agents.customer_service import create_customer_service_agent
        agent = create_customer_service_agent(registry)
        assert "greet_and_collect" in agent.instruction
        assert "lookup_order" in agent.instruction

    def test_agent_instruction_contains_persona(self, registry):
        from workflow_engine.agents.customer_service import create_customer_service_agent
        agent = create_customer_service_agent(registry)
        assert "customer service" in agent.instruction.lower()

    def test_agent_description_contains_trigger_intents(self, registry):
        from workflow_engine.agents.customer_service import create_customer_service_agent
        agent = create_customer_service_agent(registry)
        assert "refund" in agent.description.lower() or "return" in agent.description.lower()

    def test_agent_model_is_set(self, registry):
        from workflow_engine.agents.customer_service import create_customer_service_agent
        agent = create_customer_service_agent(registry)
        assert agent.model is not None


class TestCreateFraudOpsAgent:
    def test_agent_has_name(self, registry):
        from workflow_engine.agents.fraud_ops import create_fraud_ops_agent
        agent = create_fraud_ops_agent(registry)
        assert agent.name == "fraud_ops_agent"

    def test_agent_has_tools(self, registry):
        from workflow_engine.agents.fraud_ops import create_fraud_ops_agent
        agent = create_fraud_ops_agent(registry)
        assert len(agent.tools) > 0

    def test_agent_instruction_contains_fraud_steps(self, registry):
        from workflow_engine.agents.fraud_ops import create_fraud_ops_agent
        agent = create_fraud_ops_agent(registry)
        assert "receive_alert" in agent.instruction
        assert "get_fraud_alert" in agent.instruction

    def test_agent_instruction_contains_persona(self, registry):
        from workflow_engine.agents.fraud_ops import create_fraud_ops_agent
        agent = create_fraud_ops_agent(registry)
        assert "fraud" in agent.instruction.lower()

    def test_agent_description_contains_trigger_intents(self, registry):
        from workflow_engine.agents.fraud_ops import create_fraud_ops_agent
        agent = create_fraud_ops_agent(registry)
        assert "fraud" in agent.description.lower()

    def test_tool_map_covers_yaml_tools(self, registry):
        from workflow_engine.agents.fraud_ops import TOOL_MAP
        yaml_tools = registry.get_procedure_tool_names("fraud_alert_triage")
        for tool_name in yaml_tools:
            assert tool_name in TOOL_MAP, f"TOOL_MAP missing '{tool_name}'"


class TestCreateRouterAgent:
    def test_router_has_three_sub_agents(self, registry):
        from workflow_engine.agents.router import create_router_agent
        agent = create_router_agent(registry)
        assert len(agent.sub_agents) == 3

    def test_router_sub_agent_names(self, registry):
        from workflow_engine.agents.router import create_router_agent
        agent = create_router_agent(registry)
        names = {a.name for a in agent.sub_agents}
        assert "customer_service_agent" in names
        assert "fraud_ops_agent" in names
        assert "general_agent" in names

    def test_router_has_no_tools(self, registry):
        from workflow_engine.agents.router import create_router_agent
        agent = create_router_agent(registry)
        assert not agent.tools

    def test_router_instruction_mentions_routing(self, registry):
        from workflow_engine.agents.router import create_router_agent
        agent = create_router_agent(registry)
        instr = agent.instruction.lower()
        assert "customer service" in instr or "route" in instr or "specialist" in instr

    def test_general_agent_has_knowledge_tool(self):
        from workflow_engine.agents.router import create_general_agent
        agent = create_general_agent()
        tool_names = [t.__name__ for t in agent.tools]
        assert "get_knowledge_article" in tool_names

    def test_general_agent_description_set(self):
        from workflow_engine.agents.router import create_general_agent
        agent = create_general_agent()
        assert agent.description and len(agent.description) > 0


class TestRootAgentModule:
    def test_root_agent_exported(self):
        from workflow_engine.agent import root_agent
        assert root_agent is not None

    def test_root_agent_has_sub_agents(self):
        from workflow_engine.agent import root_agent
        assert len(root_agent.sub_agents) == 3
