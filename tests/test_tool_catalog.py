"""Regression tests for the Phase 0 model-tool safety inventory."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from workflow_engine.agents.customer_service import TOOL_MAP as CUSTOMER_SERVICE_TOOLS
from workflow_engine.agents.fraud_ops import TOOL_MAP as FRAUD_TOOLS
from workflow_engine.procedures.registry import ProcedureRegistry
from workflow_engine.tools.catalog import (
    AuthorizationMode,
    IdempotencyMode,
    TOOL_CATALOG,
    select_model_tools,
)


def _exposed_tool_names() -> set[str]:
    # get_knowledge_article is also exposed directly by the general agent.
    return set(CUSTOMER_SERVICE_TOOLS) | set(FRAUD_TOOLS) | {"get_knowledge_article"}


def test_every_model_exposed_tool_is_classified() -> None:
    assert _exposed_tool_names() == set(TOOL_CATALOG)


def test_every_procedure_tool_is_resolvable_and_classified() -> None:
    registry = ProcedureRegistry(str(Path(__file__).parent.parent / "procedures"))
    procedure_tools = {
        tool
        for procedure in registry.procedures.values()
        for tool in registry.get_procedure_tool_names(procedure["id"])
    }

    assert procedure_tools <= _exposed_tool_names()


def test_consequential_tools_declare_independent_controls() -> None:
    consequential = [entry for entry in TOOL_CATALOG.values() if entry.consequential]

    assert consequential
    for entry in consequential:
        assert entry.required_permission is not None
        assert entry.authorization_mode is AuthorizationMode.ACTION_GATEWAY_REQUIRED
        assert entry.idempotency_mode is not IdempotencyMode.NOT_APPLICABLE
        assert entry.production_model_enabled is True
        assert entry.proposal_only is True


def test_production_exposes_only_proposal_wrappers_for_consequential_tools() -> None:
    selected = select_model_tools(CUSTOMER_SERVICE_TOOLS, production=True)
    selected_names = {tool.__name__ for tool in selected}

    assert "lookup_order" in selected_names
    assert "search_orders" in selected_names
    assert "issue_refund" in selected_names
    assert "issue_store_credit" in selected_names
    assert "file_eft_dispute" in selected_names
    assert "issue_provisional_credit" in selected_names
    for tool in selected:
        if TOOL_CATALOG[tool.__name__].consequential:
            assert tool.__module__ == "workflow_engine.tools.action_proposals"


def test_direct_write_function_cannot_be_registered_as_model_action() -> None:
    from workflow_engine.tools.crm_tools import issue_refund

    with pytest.raises(ValueError, match="proposal-only"):
        select_model_tools({"issue_refund": issue_refund}, production=False)


def test_development_model_exposure_preserves_current_behavior() -> None:
    selected = select_model_tools(CUSTOMER_SERVICE_TOOLS, production=False)

    assert {tool.__name__ for tool in selected} == set(CUSTOMER_SERVICE_TOOLS)


def test_unclassified_tool_fails_closed() -> None:
    with pytest.raises(KeyError):
        select_model_tools({"new_write_tool": lambda: None}, production=False)


def test_customer_service_agent_applies_production_freeze(monkeypatch) -> None:
    from workflow_engine.agents import customer_service

    registry = ProcedureRegistry(str(Path(__file__).parent.parent / "procedures"))
    monkeypatch.setattr(
        customer_service,
        "get_settings",
        lambda: SimpleNamespace(is_production=True),
    )

    agent = customer_service.create_customer_service_agent(registry)
    selected_names = {tool.__name__ for tool in agent.tools}

    assert "lookup_order" in selected_names
    assert "issue_refund" in selected_names
    assert "only create proposals" in agent.instruction.lower()


def test_fraud_agent_applies_production_freeze(monkeypatch) -> None:
    from workflow_engine.agents import fraud_ops

    registry = ProcedureRegistry(str(Path(__file__).parent.parent / "procedures"))
    monkeypatch.setattr(
        fraud_ops,
        "get_settings",
        lambda: SimpleNamespace(is_production=True),
    )

    agent = fraud_ops.create_fraud_ops_agent(registry)
    selected_names = {tool.__name__ for tool in agent.tools}

    assert "get_fraud_alert" in selected_names
    assert "flag_account" in selected_names
    assert FRAUD_TOOLS["submit_sar"].__module__ == "workflow_engine.tools.action_proposals"
    assert "only create proposals" in agent.instruction.lower()
