"""Tests for procedure YAML loader and instruction builder."""
import pytest

from workflow_engine.procedures.loader import (
    load_procedure,
    build_agent_instructions,
    get_procedure_tools,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_YAML = """\
procedure:
  id: test_proc
  name: "Test Procedure"
  description: "A test procedure"
  steps:
    - id: step_one
      instruction: "Do step one."
      action: collect_info
      required_info:
        - some_field
      next_step: step_two
    - id: step_two
      instruction: "Call a tool."
      action: tool_call
      tool: lookup_order
      on_success: step_three
      on_failure: end
    - id: step_three
      instruction: "Evaluate something."
      action: evaluate
      conditions:
        - if: "value == true"
          next_step: end
      next_step: end
"""

MISSING_PROCEDURE_KEY_YAML = """\
id: test_proc
name: "Test"
description: "No outer procedure key"
steps:
  - id: s1
    instruction: "x"
    action: collect_info
    next_step: end
"""

MISSING_STEPS_YAML = """\
procedure:
  id: test_proc
  name: "Test"
  description: "No steps"
  steps: []
"""

TOOL_CALL_WITHOUT_TOOL_YAML = """\
procedure:
  id: test_proc
  name: "Test"
  description: "tool_call step missing tool field"
  steps:
    - id: s1
      instruction: "missing tool"
      action: tool_call
      on_success: end
      on_failure: end
"""

BAD_NEXT_STEP_YAML = """\
procedure:
  id: test_proc
  name: "Test"
  description: "bad next_step reference"
  steps:
    - id: s1
      instruction: "bad ref"
      action: collect_info
      next_step: nonexistent_step
"""


@pytest.fixture
def valid_yaml_file(tmp_path):
    f = tmp_path / "test_proc.yaml"
    f.write_text(VALID_YAML)
    return str(f)


@pytest.fixture
def valid_procedure(valid_yaml_file):
    return load_procedure(valid_yaml_file)


def write_temp_yaml(tmp_path, content, name="proc.yaml"):
    f = tmp_path / name
    f.write_text(content)
    return str(f)


# ---------------------------------------------------------------------------
# load_procedure tests
# ---------------------------------------------------------------------------

class TestLoadProcedure:
    def test_loads_valid_procedure(self, valid_procedure):
        assert valid_procedure["id"] == "test_proc"
        assert valid_procedure["name"] == "Test Procedure"
        assert len(valid_procedure["steps"]) == 3

    def test_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_procedure("/nonexistent/path/proc.yaml")

    def test_raises_on_missing_procedure_key(self, tmp_path):
        f = write_temp_yaml(tmp_path, MISSING_PROCEDURE_KEY_YAML)
        with pytest.raises(ValueError, match="missing 'procedure' key"):
            load_procedure(f)

    def test_raises_on_empty_steps(self, tmp_path):
        f = write_temp_yaml(tmp_path, MISSING_STEPS_YAML)
        with pytest.raises(ValueError, match="no steps"):
            load_procedure(f)

    def test_raises_on_tool_call_without_tool(self, tmp_path):
        f = write_temp_yaml(tmp_path, TOOL_CALL_WITHOUT_TOOL_YAML)
        with pytest.raises(ValueError, match="no 'tool' field"):
            load_procedure(f)

    def test_raises_on_bad_next_step_reference(self, tmp_path):
        f = write_temp_yaml(tmp_path, BAD_NEXT_STEP_YAML)
        with pytest.raises(ValueError, match="not a valid step ID"):
            load_procedure(f)


# ---------------------------------------------------------------------------
# get_procedure_tools tests
# ---------------------------------------------------------------------------

class TestGetProcedureTools:
    def test_extracts_tool_names(self, valid_procedure):
        tools = get_procedure_tools(valid_procedure)
        assert tools == ["lookup_order"]

    def test_empty_when_no_tool_steps(self):
        proc = {
            "steps": [
                {"id": "s1", "instruction": "x", "action": "collect_info"}
            ]
        }
        assert get_procedure_tools(proc) == []

    def test_deduplicates_tools(self):
        proc = {
            "steps": [
                {"id": "s1", "instruction": "x", "action": "tool_call", "tool": "my_tool"},
                {"id": "s2", "instruction": "y", "action": "tool_call", "tool": "my_tool"},
            ]
        }
        assert get_procedure_tools(proc) == ["my_tool"]


# ---------------------------------------------------------------------------
# build_agent_instructions tests
# ---------------------------------------------------------------------------

class TestBuildAgentInstructions:
    def test_includes_persona(self, valid_procedure):
        persona = "You are a test agent."
        result = build_agent_instructions(valid_procedure, persona)
        assert persona in result

    def test_includes_procedure_name(self, valid_procedure):
        result = build_agent_instructions(valid_procedure, "")
        assert "Test Procedure" in result

    def test_includes_all_step_ids(self, valid_procedure):
        result = build_agent_instructions(valid_procedure, "")
        assert "step_one" in result
        assert "step_two" in result
        assert "step_three" in result

    def test_includes_tool_guidance(self, valid_procedure):
        result = build_agent_instructions(valid_procedure, "")
        assert "lookup_order" in result

    def test_includes_required_info(self, valid_procedure):
        result = build_agent_instructions(valid_procedure, "")
        assert "some_field" in result

    def test_includes_condition_branches(self, valid_procedure):
        result = build_agent_instructions(valid_procedure, "")
        assert "value == true" in result

    def test_returns_string(self, valid_procedure):
        result = build_agent_instructions(valid_procedure, "persona")
        assert isinstance(result, str)
        assert len(result) > 0
