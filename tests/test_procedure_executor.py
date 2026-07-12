"""Tests for the stateful procedure executor."""

import pytest

from workflow_engine.procedures.executor import (
    ProcedureExecutor,
    ProcedureExecutorRegistry,
    ProcedureStatus,
    StepStatus,
)
from workflow_engine.errors import ProcedureError


# --- Fixtures ---

@pytest.fixture
def simple_procedure():
    """A minimal 3-step procedure for testing."""
    return {
        "id": "test_proc",
        "name": "Test Procedure",
        "steps": [
            {
                "id": "step_1",
                "instruction": "Collect info",
                "action": "collect_info",
                "next_step": "step_2",
            },
            {
                "id": "step_2",
                "instruction": "Call tool",
                "action": "tool_call",
                "tool": "lookup_order",
                "on_success": "step_3",
                "on_failure": "end",
            },
            {
                "id": "step_3",
                "instruction": "Close",
                "action": "inform",
                "next_step": "end",
            },
        ],
    }


@pytest.fixture
def branching_procedure():
    """A procedure with evaluate branching."""
    return {
        "id": "branch_proc",
        "name": "Branching Procedure",
        "steps": [
            {
                "id": "start",
                "instruction": "Evaluate",
                "action": "evaluate",
                "conditions": [
                    {"if": "eligible", "next_step": "approve"},
                    {"if": "not eligible", "next_step": "deny"},
                ],
            },
            {
                "id": "approve",
                "instruction": "Approve",
                "action": "inform",
                "next_step": "end",
            },
            {
                "id": "deny",
                "instruction": "Deny",
                "action": "inform",
                "next_step": "end",
            },
        ],
    }


# --- Tests ---


class TestProcedureExecutorInit:
    def test_builds_step_map(self, simple_procedure):
        executor = ProcedureExecutor(simple_procedure)
        assert "step_1" in executor.steps
        assert "step_2" in executor.steps
        assert "step_3" in executor.steps

    def test_builds_transition_graph(self, simple_procedure):
        executor = ProcedureExecutor(simple_procedure)
        assert "step_2" in executor._valid_transitions["step_1"]
        assert "step_3" in executor._valid_transitions["step_2"]
        assert "end" in executor._valid_transitions["step_2"]

    def test_initial_status(self, simple_procedure):
        executor = ProcedureExecutor(simple_procedure)
        assert executor.status == ProcedureStatus.NOT_STARTED


class TestProcedureExecutorStart:
    @pytest.mark.asyncio
    async def test_starts_at_first_step(self, simple_procedure):
        executor = ProcedureExecutor(simple_procedure)
        state = {}
        result = await executor.start(state)
        assert result == "step_1"
        assert executor.current_step_id == "step_1"
        assert executor.status == ProcedureStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_updates_session_state(self, simple_procedure):
        executor = ProcedureExecutor(simple_procedure)
        state = {}
        await executor.start(state)
        assert state["current_procedure"] == "test_proc"
        assert state["current_step"] == "step_1"
        assert state["workflow_status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_cannot_start_twice(self, simple_procedure):
        executor = ProcedureExecutor(simple_procedure)
        await executor.start({})
        with pytest.raises(ProcedureError):
            await executor.start({})


class TestProcedureExecutorTransition:
    @pytest.mark.asyncio
    async def test_valid_transition(self, simple_procedure):
        executor = ProcedureExecutor(simple_procedure)
        state = {}
        await executor.start(state)
        result = await executor.transition("step_2", state)
        assert result == "step_2"
        assert executor.current_step_id == "step_2"

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self, simple_procedure):
        executor = ProcedureExecutor(simple_procedure)
        state = {}
        await executor.start(state)
        # step_1 can only go to step_2 or end, not step_3
        with pytest.raises(ProcedureError) as exc_info:
            await executor.transition("step_3", state)
        assert "Invalid transition" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_transition_to_end_completes(self, simple_procedure):
        executor = ProcedureExecutor(simple_procedure)
        state = {}
        await executor.start(state)
        await executor.transition("step_2", state)
        result = await executor.transition("end", state, reason="tool_failed")
        assert result == "end"
        assert executor.status == ProcedureStatus.COMPLETED
        assert state["workflow_status"] == "completed"

    @pytest.mark.asyncio
    async def test_completes_previous_step(self, simple_procedure):
        executor = ProcedureExecutor(simple_procedure)
        state = {}
        await executor.start(state)
        await executor.transition("step_2", state)
        assert executor.step_executions["step_1"].status == StepStatus.COMPLETED


class TestProcedureExecutorBranching:
    @pytest.mark.asyncio
    async def test_branch_to_approve(self, branching_procedure):
        executor = ProcedureExecutor(branching_procedure)
        state = {}
        await executor.start(state)
        result = await executor.transition("approve", state)
        assert result == "approve"

    @pytest.mark.asyncio
    async def test_branch_to_deny(self, branching_procedure):
        executor = ProcedureExecutor(branching_procedure)
        state = {}
        await executor.start(state)
        result = await executor.transition("deny", state)
        assert result == "deny"


class TestProcedureExecutorEscalation:
    @pytest.mark.asyncio
    async def test_escalate(self, simple_procedure):
        executor = ProcedureExecutor(simple_procedure)
        state = {}
        await executor.start(state)
        result = await executor.escalate(state, "customer requested supervisor")
        assert result == "escalated"
        assert executor.status == ProcedureStatus.ESCALATED
        assert state["workflow_status"] == "escalated"
        assert state["escalation_reason"] == "customer requested supervisor"


class TestProcedureExecutorQuery:
    @pytest.mark.asyncio
    async def test_get_current_step(self, simple_procedure):
        executor = ProcedureExecutor(simple_procedure)
        state = {}
        await executor.start(state)
        step = executor.get_current_step()
        assert step is not None
        assert step["id"] == "step_1"

    @pytest.mark.asyncio
    async def test_get_allowed_tools(self, simple_procedure):
        executor = ProcedureExecutor(simple_procedure)
        state = {}
        await executor.start(state)
        # step_1 has no tools
        assert executor.get_allowed_tools() == []
        await executor.transition("step_2", state)
        # step_2 has lookup_order
        assert "lookup_order" in executor.get_allowed_tools()

    @pytest.mark.asyncio
    async def test_get_progress(self, simple_procedure):
        executor = ProcedureExecutor(simple_procedure)
        state = {}
        await executor.start(state)
        await executor.transition("step_2", state)
        progress = executor.get_progress()
        assert progress["procedure_id"] == "test_proc"
        assert progress["current_step"] == "step_2"
        assert "step_1" in progress["steps_completed"]
        assert progress["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_get_step_history(self, simple_procedure):
        executor = ProcedureExecutor(simple_procedure)
        state = {}
        await executor.start(state)
        await executor.transition("step_2", state)
        history = executor.get_step_history()
        assert len(history) == 2
        assert history[0]["step_id"] == "step_1"
        assert history[0]["status"] == "completed"
        assert history[1]["step_id"] == "step_2"
        assert history[1]["status"] == "active"


class TestProcedureExecutorRegistry:
    def test_create_and_get(self, simple_procedure):
        reg = ProcedureExecutorRegistry()
        executor = reg.create("session-1", simple_procedure)
        assert executor is not None
        assert reg.get("session-1") is executor

    def test_get_missing_returns_none(self):
        reg = ProcedureExecutorRegistry()
        assert reg.get("nonexistent") is None

    def test_remove(self, simple_procedure):
        reg = ProcedureExecutorRegistry()
        reg.create("session-1", simple_procedure)
        reg.remove("session-1")
        assert reg.get("session-1") is None

    @pytest.mark.asyncio
    async def test_list_active(self, simple_procedure):
        reg = ProcedureExecutorRegistry()
        executor = reg.create("session-1", simple_procedure)
        await executor.start({})
        active = reg.list_active()
        assert "session-1" in active
        assert active["session-1"]["status"] == "in_progress"
