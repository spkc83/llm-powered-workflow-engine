"""Workflow state management helpers.

Provides functions to track procedure execution progress via session state.
All functions operate on a plain dict (the caller passes tool_context.state
or session.state), keeping them testable without real ADK context.
"""
from datetime import datetime
from typing import Any, Optional


def initialize_workflow(state: dict, procedure_id: str, procedure_name: str) -> None:
    """Initialize workflow tracking state for a new procedure execution.

    Args:
        state: The session state dict to write to.
        procedure_id: ID of the procedure being executed.
        procedure_name: Human-readable name of the procedure.
    """
    state["current_procedure"] = procedure_id
    state["current_procedure_name"] = procedure_name
    state["current_step"] = None
    state["steps_completed"] = []
    state["workflow_status"] = "in_progress"
    state["workflow_started_at"] = datetime.now().isoformat()
    state["workflow_resolution"] = None
    state["workflow_completed_at"] = None


def set_current_step(state: dict, step_id: str) -> None:
    """Update the current step and track the previous step as completed.

    Args:
        state: The session state dict.
        step_id: The step ID to set as current.
    """
    previous_step = state.get("current_step")
    if previous_step and previous_step not in state.get("steps_completed", []):
        steps = state.get("steps_completed", [])
        steps.append(previous_step)
        state["steps_completed"] = steps

    state["current_step"] = step_id


def get_current_step(state: dict) -> Optional[str]:
    """Get the current step ID.

    Args:
        state: The session state dict.

    Returns:
        The current step ID, or None if not set.
    """
    return state.get("current_step")


def get_workflow_progress(state: dict) -> dict:
    """Get a summary of workflow execution progress.

    Args:
        state: The session state dict.

    Returns:
        Dict with current_procedure, current_step, steps_completed,
        workflow_status, and started_at.
    """
    return {
        "current_procedure": state.get("current_procedure"),
        "current_procedure_name": state.get("current_procedure_name"),
        "current_step": state.get("current_step"),
        "steps_completed": state.get("steps_completed", []),
        "workflow_status": state.get("workflow_status"),
        "started_at": state.get("workflow_started_at"),
        "resolution": state.get("workflow_resolution"),
        "completed_at": state.get("workflow_completed_at"),
    }


def record_tool_result(state: dict, tool_name: str, result: Any) -> None:
    """Store a tool's result in state for later reference.

    Args:
        state: The session state dict.
        tool_name: Name of the tool that produced the result.
        result: The tool's return value.
    """
    state[f"tool_result:{tool_name}"] = result


def complete_workflow(state: dict, resolution: str) -> None:
    """Mark the workflow as completed.

    Args:
        state: The session state dict.
        resolution: Description of how the workflow was resolved.
    """
    # Mark current step as completed
    current = state.get("current_step")
    if current and current not in state.get("steps_completed", []):
        steps = state.get("steps_completed", [])
        steps.append(current)
        state["steps_completed"] = steps

    state["workflow_status"] = "completed"
    state["workflow_resolution"] = resolution
    state["workflow_completed_at"] = datetime.now().isoformat()
    state["current_step"] = None


def escalate_workflow(state: dict, reason: str) -> None:
    """Mark the workflow as escalated.

    Args:
        state: The session state dict.
        reason: Reason for escalation.
    """
    state["workflow_status"] = "escalated"
    state["escalation_reason"] = reason
    state["escalated_at"] = datetime.now().isoformat()
