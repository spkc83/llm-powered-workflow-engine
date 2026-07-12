"""Procedure YAML loader and instruction builder."""
import yaml
from pathlib import Path


def load_procedure(file_path: str) -> dict:
    """Parse a YAML procedure file and return the procedure dict.

    Args:
        file_path: Path to the YAML procedure file.

    Returns:
        The procedure dict from the YAML file.

    Raises:
        ValueError: If required fields are missing.
        FileNotFoundError: If file doesn't exist.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Procedure file not found: {file_path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    if not data or "procedure" not in data:
        raise ValueError(f"Invalid procedure file: missing 'procedure' key in {file_path}")

    procedure = data["procedure"]

    # Validate required top-level fields
    required = ["id", "name", "description", "steps"]
    for field in required:
        if field not in procedure:
            raise ValueError(f"Procedure missing required field '{field}' in {file_path}")

    # Validate steps
    if not procedure["steps"] or len(procedure["steps"]) == 0:
        raise ValueError(f"Procedure has no steps in {file_path}")

    validate_procedure(procedure)

    return procedure


def validate_procedure(procedure: dict) -> bool:
    """Validate procedure structure and step references.

    Checks that:
    - Each step has required fields (id, instruction, action)
    - Step references (next_step, on_success, on_failure) point to valid step IDs or "end"
    - Tool_call actions have a tool field

    Args:
        procedure: The procedure dict to validate.

    Returns:
        True if valid.

    Raises:
        ValueError: If validation fails.
    """
    step_ids = {step["id"] for step in procedure["steps"]}
    valid_targets = step_ids | {"end"}

    for step in procedure["steps"]:
        # Check required step fields
        if "id" not in step:
            raise ValueError("Step missing 'id' field")
        if "instruction" not in step:
            raise ValueError(f"Step '{step['id']}' missing 'instruction' field")
        if "action" not in step:
            raise ValueError(f"Step '{step['id']}' missing 'action' field")

        # Validate tool_call has tool
        if step["action"] == "tool_call" and "tool" not in step:
            raise ValueError(f"Step '{step['id']}' has action 'tool_call' but no 'tool' field")

        # Validate step references
        for ref_field in ["next_step", "on_success", "on_failure"]:
            if ref_field in step and step[ref_field] not in valid_targets:
                raise ValueError(
                    f"Step '{step['id']}' has {ref_field}='{step[ref_field]}' "
                    f"which is not a valid step ID or 'end'"
                )

        # Validate condition targets
        if "conditions" in step and step["conditions"]:
            for cond in step["conditions"]:
                if "next_step" in cond and cond["next_step"] not in valid_targets:
                    raise ValueError(
                        f"Step '{step['id']}' has condition with next_step='{cond['next_step']}' "
                        f"which is not a valid step ID or 'end'"
                    )

        # Validate option targets
        if "options" in step and step["options"]:
            for opt in step["options"]:
                if "next_step" in opt and opt["next_step"] not in valid_targets:
                    raise ValueError(
                        f"Step '{step['id']}' has option with next_step='{opt['next_step']}' "
                        f"which is not a valid step ID or 'end'"
                    )

    return True


def build_agent_instructions(procedure: dict, persona: str) -> str:
    """Transform procedure steps into a detailed instruction string for an LLM agent.

    The output string includes:
    1. The agent's role/persona
    2. Procedure overview
    3. Step-by-step instructions with tool guidance
    4. Branching logic in natural language
    5. State tracking notes

    Args:
        procedure: The procedure dict.
        persona: The agent persona description.

    Returns:
        A formatted instruction string.
    """
    lines = []

    # Persona
    lines.append(persona)
    lines.append("")

    # Procedure overview
    lines.append(f"## Procedure: {procedure['name']}")
    lines.append(f"{procedure['description']}")
    lines.append("")

    # Step-by-step instructions
    lines.append("## Steps to Follow")
    lines.append("Follow these steps in order, using the branching logic described:")
    lines.append("")

    for i, step in enumerate(procedure["steps"], 1):
        lines.append(f"### Step {i}: {step['id']}")
        lines.append(step["instruction"].strip())

        # Tool guidance
        if step["action"] == "tool_call" and "tool" in step:
            lines.append(f"  → Use the `{step['tool']}` tool to complete this step.")
            if "on_success" in step:
                lines.append(f"  → If successful, proceed to: {step['on_success']}")
            if "on_failure" in step:
                lines.append(f"  → If it fails, go to: {step['on_failure']}")

        # Collection guidance
        if step["action"] == "collect_info" and "required_info" in step:
            info_list = ", ".join(step["required_info"])
            lines.append(f"  → You must collect: {info_list}")
            lines.append("  → IMPORTANT: If this information is already present in the user's message, "
                         "skip collection and immediately proceed to the next step.")

        # Branching conditions
        if step["action"] == "evaluate" and "conditions" in step and step["conditions"]:
            lines.append("  → Evaluate the following conditions:")
            for cond in step["conditions"]:
                condition_text = cond.get("if", cond.get("condition", ""))
                target = cond.get("next_step", "end")
                lines.append(f"    - If {condition_text} → go to {target}")

        # Options
        if "options" in step and step["options"]:
            lines.append("  → Present these options to the user:")
            for opt in step["options"]:
                label = opt.get("label", "")
                target = opt.get("next_step", "end")
                lines.append(f"    - {label} → go to {target}")

        # Linear next step
        if "next_step" in step and step["action"] not in ["tool_call", "evaluate"]:
            if step["next_step"] == "end":
                lines.append("  → This is the final step. End the conversation.")
            else:
                lines.append(f"  → Next step: {step['next_step']}")

        lines.append("")

    # State tracking
    lines.append("## State Tracking")
    lines.append("As you progress through the procedure:")
    lines.append("- Store relevant data from tool calls in the conversation state")
    lines.append("- Keep track of which steps you have completed")
    lines.append("- Reference previously gathered information when needed")
    lines.append("")

    return "\n".join(lines)


def get_procedure_tools(procedure: dict) -> list[str]:
    """Extract all unique tool names referenced in the procedure steps.

    Args:
        procedure: The procedure dict.

    Returns:
        List of unique tool name strings.
    """
    tools = set()
    for step in procedure.get("steps", []):
        if "tool" in step:
            tools.add(step["tool"])
        # Also extract from the plural "tools" key (list of additional tools)
        if "tools" in step and isinstance(step["tools"], list):
            tools.update(step["tools"])
    return sorted(tools)
