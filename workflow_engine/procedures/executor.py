"""Stateful procedure executor — runtime state machine for procedure execution.

Instead of relying solely on the LLM to follow instructions, this executor
tracks the current step, validates transitions, and enforces branching logic
at the engine level. The LLM still drives the conversation, but the engine
ensures procedural correctness.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

from ..agents.guardrails import validate_tool_args
from ..audit import AuditAction, get_audit_logger
from ..errors import ProcedureError, ErrorCode
from ..logging_config import get_logger

logger = get_logger("procedures.executor")


class StepStatus(str, Enum):
    """Status of a procedure step."""
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class ProcedureStatus(str, Enum):
    """Status of a procedure execution."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class StepExecution:
    """Tracks the execution state of a single procedure step."""

    def __init__(self, step_def: dict):
        self.step_id: str = step_def["id"]
        self.definition: dict = step_def
        self.status: StepStatus = StepStatus.PENDING
        self.entered_at: Optional[str] = None
        self.completed_at: Optional[str] = None
        self.tool_results: list[dict] = []
        self.transition_reason: Optional[str] = None

    def enter(self) -> None:
        self.status = StepStatus.ACTIVE
        self.entered_at = datetime.now(timezone.utc).isoformat()

    def complete(self, reason: str = "completed") -> None:
        self.status = StepStatus.COMPLETED
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.transition_reason = reason

    def fail(self, reason: str = "failed") -> None:
        self.status = StepStatus.FAILED
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.transition_reason = reason

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "status": self.status.value,
            "entered_at": self.entered_at,
            "completed_at": self.completed_at,
            "transition_reason": self.transition_reason,
        }


# Type alias for step lifecycle hooks
StepHook = Callable[[str, dict], Coroutine[Any, Any, None]]


class ProcedureExecutor:
    """Stateful executor that tracks and enforces procedure progression.

    The executor maintains a directed graph of steps and validates all
    transitions. It provides the LLM agent with context about what step
    it should be on and what tools are permitted for that step.

    Usage:
        executor = ProcedureExecutor(procedure_def)
        executor.start(session_state)

        # When the agent processes a step:
        executor.enter_step("lookup_order", session_state)

        # When a tool completes:
        executor.record_tool_result("lookup_order", "lookup_order", result, session_state)

        # Transition to next step:
        executor.transition("check_eligibility", session_state)
    """

    def __init__(self, procedure: dict):
        """Initialize the executor with a procedure definition.

        Args:
            procedure: The parsed procedure dict from YAML.
        """
        self.procedure_id: str = procedure["id"]
        self.procedure_name: str = procedure["name"]
        self.steps: dict[str, dict] = {s["id"]: s for s in procedure["steps"]}
        self.step_order: list[str] = [s["id"] for s in procedure["steps"]]

        # Build adjacency graph for valid transitions
        self._valid_transitions: dict[str, set[str]] = {}
        for step in procedure["steps"]:
            sid = step["id"]
            targets: set[str] = set()
            for field in ("next_step", "on_success", "on_failure"):
                if field in step and step[field] != "end":
                    targets.add(step[field])
            if "conditions" in step and step["conditions"]:
                for cond in step["conditions"]:
                    t = cond.get("next_step")
                    if t and t != "end":
                        targets.add(t)
            if "options" in step and step["options"]:
                for opt in step["options"]:
                    t = opt.get("next_step")
                    if t and t != "end":
                        targets.add(t)
            # "end" is always a valid target (completes the procedure)
            targets.add("end")
            self._valid_transitions[sid] = targets

        # Runtime state
        self.status: ProcedureStatus = ProcedureStatus.NOT_STARTED
        self.current_step_id: Optional[str] = None
        self.step_executions: dict[str, StepExecution] = {}
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None

        # Lifecycle hooks
        self._on_enter_hooks: list[StepHook] = []
        self._on_exit_hooks: list[StepHook] = []
        self._on_complete_hooks: list[Callable] = []

    # --- Lifecycle hooks ---

    def on_step_enter(self, hook: StepHook) -> None:
        """Register a hook called when entering any step."""
        self._on_enter_hooks.append(hook)

    def on_step_exit(self, hook: StepHook) -> None:
        """Register a hook called when exiting any step."""
        self._on_exit_hooks.append(hook)

    def validate_step_tools(self, step_id: str, tool_name: str, args: dict) -> list:
        """Validate tool arguments before execution at a given step.

        Uses the guardrails validate_tool_args function and also checks
        that the tool is permitted for the current step.

        Args:
            step_id: The step attempting to use the tool.
            tool_name: The tool being called.
            args: The arguments being passed to the tool.

        Returns:
            List of GuardrailViolation objects (empty if valid).
        """
        violations = validate_tool_args(tool_name, args)

        # Check that the tool is allowed for this step
        allowed = self.get_allowed_tools()
        if allowed and tool_name not in allowed:
            from ..agents.guardrails import GuardrailViolation
            violations.append(GuardrailViolation(
                rule="tool_not_allowed_for_step",
                description=(
                    f"Tool '{tool_name}' is not permitted at step '{step_id}'. "
                    f"Allowed tools: {allowed}"
                ),
                severity="block",
            ))
            logger.warning(
                "Tool '%s' blocked at step '%s' — not in allowed list %s",
                tool_name, step_id, allowed,
            )

        return violations

    # --- Execution control ---

    async def start(self, session_state: dict) -> str:
        """Start procedure execution at the first step.

        Args:
            session_state: The session state dict to update.

        Returns:
            The ID of the first step.
        """
        if self.status == ProcedureStatus.IN_PROGRESS:
            raise ProcedureError(
                f"Procedure '{self.procedure_id}' is already in progress",
                code=ErrorCode.PROCEDURE_ALREADY_ACTIVE,
            )

        self.status = ProcedureStatus.IN_PROGRESS
        self.started_at = datetime.now(timezone.utc).isoformat()

        first_step_id = self.step_order[0]
        self._update_session_state(session_state, first_step_id)

        # Audit
        audit = get_audit_logger()
        await audit.log(
            action=AuditAction.PROCEDURE_STARTED,
            actor=session_state.get("customer_id", "system"),
            resource_type="procedure",
            resource_id=self.procedure_id,
            session_id=session_state.get("_session_id"),
            procedure_id=self.procedure_id,
            metadata={"first_step": first_step_id},
        )

        logger.info("Procedure '%s' started at step '%s'", self.procedure_id, first_step_id)
        return await self.enter_step(first_step_id, session_state)

    async def enter_step(self, step_id: str, session_state: dict) -> str:
        """Enter a specific step.

        Args:
            step_id: The step to enter.
            session_state: The session state dict.

        Returns:
            The step ID that was entered.
        """
        if step_id not in self.steps:
            raise ProcedureError(
                f"Step '{step_id}' does not exist in procedure '{self.procedure_id}'",
                code=ErrorCode.INVALID_STEP_TRANSITION,
            )

        # Create execution record
        execution = StepExecution(self.steps[step_id])
        execution.enter()
        self.step_executions[step_id] = execution
        self.current_step_id = step_id

        self._update_session_state(session_state, step_id)

        # Fire on_enter hooks
        step_def = self.steps[step_id]
        for hook in self._on_enter_hooks:
            try:
                await hook(step_id, step_def)
            except Exception as e:
                logger.warning("Step enter hook failed for '%s': %s", step_id, e)

        logger.info("Entered step '%s' in procedure '%s'", step_id, self.procedure_id)
        return step_id

    async def transition(self, target_step_id: str, session_state: dict, reason: str = "completed") -> str:
        """Transition from the current step to a target step.

        Validates that the transition is allowed by the procedure graph.

        Args:
            target_step_id: The step to transition to, or "end".
            session_state: The session state dict.
            reason: Reason for the transition.

        Returns:
            The new current step ID, or "end" if the procedure completed.
        """
        if self.current_step_id is None:
            raise ProcedureError("No active step to transition from")

        # Validate transition
        valid_targets = self._valid_transitions.get(self.current_step_id, set())
        if target_step_id not in valid_targets:
            raise ProcedureError(
                f"Invalid transition from '{self.current_step_id}' to '{target_step_id}'. "
                f"Valid targets: {sorted(valid_targets)}",
                code=ErrorCode.INVALID_STEP_TRANSITION,
                details={
                    "from_step": self.current_step_id,
                    "to_step": target_step_id,
                    "valid_targets": sorted(valid_targets),
                },
            )

        # Complete current step
        current_exec = self.step_executions.get(self.current_step_id)
        if current_exec:
            current_exec.complete(reason)

            # Fire on_exit hooks
            for hook in self._on_exit_hooks:
                try:
                    await hook(self.current_step_id, self.steps[self.current_step_id])
                except Exception as e:
                    logger.warning("Step exit hook failed for '%s': %s", self.current_step_id, e)

        # Audit step transition
        audit = get_audit_logger()
        await audit.log(
            action=AuditAction.STEP_TRANSITION,
            actor=session_state.get("customer_id", "system"),
            resource_type="procedure_step",
            resource_id=f"{self.procedure_id}:{target_step_id}",
            session_id=session_state.get("_session_id"),
            procedure_id=self.procedure_id,
            step_id=target_step_id,
            metadata={
                "from_step": self.current_step_id,
                "reason": reason,
            },
        )

        # Handle "end" target
        if target_step_id == "end":
            return await self.complete(session_state, resolution=reason)

        # Enter the new step
        return await self.enter_step(target_step_id, session_state)

    async def complete(self, session_state: dict, resolution: str = "completed") -> str:
        """Mark the procedure as completed.

        Args:
            session_state: The session state dict.
            resolution: Description of how the procedure concluded.

        Returns:
            "end"
        """
        self.status = ProcedureStatus.COMPLETED
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.current_step_id = None

        session_state["workflow_status"] = "completed"
        session_state["workflow_resolution"] = resolution
        session_state["workflow_completed_at"] = self.completed_at
        session_state["current_step"] = None

        audit = get_audit_logger()
        await audit.log(
            action=AuditAction.PROCEDURE_COMPLETED,
            actor=session_state.get("customer_id", "system"),
            resource_type="procedure",
            resource_id=self.procedure_id,
            session_id=session_state.get("_session_id"),
            procedure_id=self.procedure_id,
            metadata={"resolution": resolution, "steps_executed": len(self.step_executions)},
        )

        logger.info("Procedure '%s' completed: %s", self.procedure_id, resolution)
        return "end"

    async def escalate(self, session_state: dict, reason: str) -> str:
        """Mark the procedure as escalated.

        Args:
            session_state: The session state dict.
            reason: Reason for escalation.

        Returns:
            "escalated"
        """
        self.status = ProcedureStatus.ESCALATED
        self.completed_at = datetime.now(timezone.utc).isoformat()

        session_state["workflow_status"] = "escalated"
        session_state["escalation_reason"] = reason
        session_state["escalated_at"] = self.completed_at

        audit = get_audit_logger()
        await audit.log(
            action=AuditAction.PROCEDURE_ESCALATED,
            actor=session_state.get("customer_id", "system"),
            resource_type="procedure",
            resource_id=self.procedure_id,
            session_id=session_state.get("_session_id"),
            procedure_id=self.procedure_id,
            metadata={"reason": reason, "step": self.current_step_id},
        )

        logger.info("Procedure '%s' escalated: %s", self.procedure_id, reason)
        return "escalated"

    # --- Query methods ---

    def get_current_step(self) -> Optional[dict]:
        """Get the current step definition, or None if no active step."""
        if self.current_step_id:
            return self.steps.get(self.current_step_id)
        return None

    def get_allowed_tools(self) -> list[str]:
        """Get tool names permitted for the current step."""
        step = self.get_current_step()
        if not step:
            return []
        tools: list[str] = []
        if "tool" in step:
            tools.append(step["tool"])
        if "tools" in step and isinstance(step["tools"], list):
            tools.extend(step["tools"])
        return tools

    def get_valid_transitions(self) -> set[str]:
        """Get valid transition targets from the current step."""
        if self.current_step_id:
            return self._valid_transitions.get(self.current_step_id, set())
        return set()

    def get_progress(self) -> dict:
        """Get a summary of procedure execution progress."""
        completed_steps = [
            sid for sid, ex in self.step_executions.items()
            if ex.status == StepStatus.COMPLETED
        ]
        return {
            "procedure_id": self.procedure_id,
            "procedure_name": self.procedure_name,
            "status": self.status.value,
            "current_step": self.current_step_id,
            "steps_completed": completed_steps,
            "total_steps": len(self.steps),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    def get_step_history(self) -> list[dict]:
        """Get execution history for all visited steps."""
        return [
            ex.to_dict() for ex in self.step_executions.values()
        ]

    # --- Internal helpers ---

    def _update_session_state(self, session_state: dict, step_id: str) -> None:
        """Sync executor state into the session state dict."""
        completed = [
            sid for sid, ex in self.step_executions.items()
            if ex.status == StepStatus.COMPLETED
        ]
        session_state["current_procedure"] = self.procedure_id
        session_state["current_procedure_name"] = self.procedure_name
        session_state["current_step"] = step_id
        session_state["steps_completed"] = completed
        session_state["workflow_status"] = self.status.value
        session_state["workflow_started_at"] = self.started_at


class ProcedureExecutorRegistry:
    """Manages active procedure executors per session.

    Each session can have at most one active procedure executor.
    """

    def __init__(self):
        self._executors: dict[str, ProcedureExecutor] = {}

    def get(self, session_id: str) -> Optional[ProcedureExecutor]:
        """Get the active executor for a session."""
        return self._executors.get(session_id)

    def create(self, session_id: str, procedure: dict) -> ProcedureExecutor:
        """Create a new executor for a session.

        Args:
            session_id: The session identifier.
            procedure: The procedure definition dict.

        Returns:
            The new ProcedureExecutor.
        """
        executor = ProcedureExecutor(procedure)
        self._executors[session_id] = executor
        return executor

    def remove(self, session_id: str) -> None:
        """Remove the executor for a session (e.g., on completion)."""
        self._executors.pop(session_id, None)

    def list_active(self) -> dict[str, dict]:
        """List all active executors with their progress."""
        return {
            sid: executor.get_progress()
            for sid, executor in self._executors.items()
            if executor.status == ProcedureStatus.IN_PROGRESS
        }
