"""Tests for workflow state management helpers."""
import pytest
from datetime import datetime

from workflow_engine.state.workflow_state import (
    initialize_workflow,
    set_current_step,
    get_current_step,
    get_workflow_progress,
    record_tool_result,
    complete_workflow,
    escalate_workflow,
)


@pytest.fixture
def state():
    return {}


@pytest.fixture
def initialized_state(state):
    initialize_workflow(state, "cs_refund", "Customer Service - Refund Request")
    return state


class TestInitializeWorkflow:
    def test_sets_procedure_id(self, state):
        initialize_workflow(state, "cs_refund", "CS Refund")
        assert state["current_procedure"] == "cs_refund"

    def test_sets_procedure_name(self, state):
        initialize_workflow(state, "cs_refund", "CS Refund")
        assert state["current_procedure_name"] == "CS Refund"

    def test_sets_status_in_progress(self, state):
        initialize_workflow(state, "cs_refund", "CS Refund")
        assert state["workflow_status"] == "in_progress"

    def test_current_step_is_none(self, state):
        initialize_workflow(state, "cs_refund", "CS Refund")
        assert state["current_step"] is None

    def test_steps_completed_is_empty(self, state):
        initialize_workflow(state, "cs_refund", "CS Refund")
        assert state["steps_completed"] == []

    def test_sets_started_at(self, state):
        initialize_workflow(state, "cs_refund", "CS Refund")
        assert state["workflow_started_at"] is not None

    def test_resolution_is_none(self, state):
        initialize_workflow(state, "cs_refund", "CS Refund")
        assert state["workflow_resolution"] is None


class TestSetCurrentStep:
    def test_sets_current_step(self, initialized_state):
        set_current_step(initialized_state, "greet_and_collect")
        assert initialized_state["current_step"] == "greet_and_collect"

    def test_marks_previous_step_completed(self, initialized_state):
        set_current_step(initialized_state, "greet_and_collect")
        set_current_step(initialized_state, "lookup_order")
        assert "greet_and_collect" in initialized_state["steps_completed"]

    def test_no_duplicate_in_completed(self, initialized_state):
        set_current_step(initialized_state, "greet_and_collect")
        set_current_step(initialized_state, "lookup_order")
        set_current_step(initialized_state, "greet_and_collect")  # revisit
        assert initialized_state["steps_completed"].count("greet_and_collect") == 1

    def test_none_previous_step_not_added(self, initialized_state):
        # current_step starts as None; transitioning to first step should not add None
        set_current_step(initialized_state, "greet_and_collect")
        assert None not in initialized_state["steps_completed"]


class TestGetCurrentStep:
    def test_returns_none_before_set(self, initialized_state):
        assert get_current_step(initialized_state) is None

    def test_returns_current_step(self, initialized_state):
        set_current_step(initialized_state, "lookup_order")
        assert get_current_step(initialized_state) == "lookup_order"


class TestGetWorkflowProgress:
    def test_returns_all_fields(self, initialized_state):
        progress = get_workflow_progress(initialized_state)
        assert "current_procedure" in progress
        assert "current_step" in progress
        assert "steps_completed" in progress
        assert "workflow_status" in progress
        assert "started_at" in progress
        assert "resolution" in progress
        assert "completed_at" in progress

    def test_reflects_current_state(self, initialized_state):
        set_current_step(initialized_state, "lookup_order")
        progress = get_workflow_progress(initialized_state)
        assert progress["current_procedure"] == "cs_refund"
        assert progress["current_step"] == "lookup_order"
        assert progress["workflow_status"] == "in_progress"


class TestRecordToolResult:
    def test_stores_result_in_state(self, initialized_state):
        record_tool_result(initialized_state, "lookup_order", {"order_id": "ORD-123"})
        assert initialized_state["tool_result:lookup_order"] == {"order_id": "ORD-123"}

    def test_overwrites_previous_result(self, initialized_state):
        record_tool_result(initialized_state, "lookup_order", {"order_id": "ORD-123"})
        record_tool_result(initialized_state, "lookup_order", {"order_id": "ORD-456"})
        assert initialized_state["tool_result:lookup_order"]["order_id"] == "ORD-456"


class TestCompleteWorkflow:
    def test_sets_status_completed(self, initialized_state):
        complete_workflow(initialized_state, "refund_issued")
        assert initialized_state["workflow_status"] == "completed"

    def test_sets_resolution(self, initialized_state):
        complete_workflow(initialized_state, "refund_issued")
        assert initialized_state["workflow_resolution"] == "refund_issued"

    def test_sets_completed_at(self, initialized_state):
        complete_workflow(initialized_state, "refund_issued")
        assert initialized_state["workflow_completed_at"] is not None

    def test_clears_current_step(self, initialized_state):
        set_current_step(initialized_state, "close_case")
        complete_workflow(initialized_state, "resolved")
        assert initialized_state["current_step"] is None

    def test_adds_current_step_to_completed(self, initialized_state):
        set_current_step(initialized_state, "close_case")
        complete_workflow(initialized_state, "resolved")
        assert "close_case" in initialized_state["steps_completed"]


class TestEscalateWorkflow:
    def test_sets_status_escalated(self, initialized_state):
        escalate_workflow(initialized_state, "customer requested supervisor")
        assert initialized_state["workflow_status"] == "escalated"

    def test_sets_escalation_reason(self, initialized_state):
        escalate_workflow(initialized_state, "customer requested supervisor")
        assert initialized_state["escalation_reason"] == "customer requested supervisor"

    def test_sets_escalated_at(self, initialized_state):
        escalate_workflow(initialized_state, "reason")
        assert initialized_state["escalated_at"] is not None
