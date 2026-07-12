"""Tests for ProcedureRegistry."""
import pytest

from workflow_engine.procedures.registry import ProcedureRegistry


CS_REFUND_YAML = """\
procedure:
  id: cs_refund
  name: "CS Refund"
  description: "Refund procedure"
  trigger_intents:
    - refund
    - return
  steps:
    - id: step_one
      instruction: "Collect order id."
      action: collect_info
      required_info:
        - order_id
      next_step: step_two
    - id: step_two
      instruction: "Look up order."
      action: tool_call
      tool: lookup_order
      on_success: end
      on_failure: end
"""

FRAUD_TRIAGE_YAML = """\
procedure:
  id: fraud_alert_triage
  name: "Fraud Triage"
  description: "Triage fraud alerts"
  trigger_intents:
    - fraud alert
    - suspicious activity
  steps:
    - id: receive_alert
      instruction: "Get the alert."
      action: tool_call
      tool: get_fraud_alert
      on_success: end
      on_failure: end
"""


@pytest.fixture
def populated_registry(tmp_path):
    (tmp_path / "cs_refund.yaml").write_text(CS_REFUND_YAML)
    (tmp_path / "fraud_triage.yaml").write_text(FRAUD_TRIAGE_YAML)
    return ProcedureRegistry(str(tmp_path))


@pytest.fixture
def empty_registry(tmp_path):
    return ProcedureRegistry(str(tmp_path))


class TestProcedureRegistry:
    def test_raises_on_missing_directory(self):
        with pytest.raises(FileNotFoundError):
            ProcedureRegistry("/nonexistent/procedures/dir")

    def test_loads_all_procedures(self, populated_registry):
        assert len(populated_registry.procedures) == 2

    def test_get_procedure_by_id(self, populated_registry):
        proc = populated_registry.get_procedure("cs_refund")
        assert proc is not None
        assert proc["name"] == "CS Refund"

    def test_get_procedure_returns_none_for_unknown(self, populated_registry):
        assert populated_registry.get_procedure("unknown_id") is None

    def test_get_procedures_for_domain_cs(self, populated_registry):
        cs_procs = populated_registry.get_procedures_for_domain("cs_")
        assert len(cs_procs) == 1
        assert cs_procs[0]["id"] == "cs_refund"

    def test_get_procedures_for_domain_fraud(self, populated_registry):
        fraud_procs = populated_registry.get_procedures_for_domain("fraud_")
        assert len(fraud_procs) == 1
        assert fraud_procs[0]["id"] == "fraud_alert_triage"

    def test_get_procedures_for_domain_empty_result(self, populated_registry):
        assert populated_registry.get_procedures_for_domain("billing_") == []

    def test_get_all_trigger_intents(self, populated_registry):
        intents = populated_registry.get_all_trigger_intents()
        assert "refund" in intents
        assert intents["refund"] == "cs_refund"
        assert "fraud alert" in intents
        assert intents["fraud alert"] == "fraud_alert_triage"

    def test_get_procedure_tool_names(self, populated_registry):
        tools = populated_registry.get_procedure_tool_names("cs_refund")
        assert tools == ["lookup_order"]

    def test_get_procedure_tool_names_unknown(self, populated_registry):
        assert populated_registry.get_procedure_tool_names("no_such") == []

    def test_empty_registry_has_no_procedures(self, empty_registry):
        assert len(empty_registry.procedures) == 0

    def test_skips_invalid_yaml_files(self, tmp_path):
        (tmp_path / "bad.yaml").write_text("not: valid: procedure: content")
        (tmp_path / "good.yaml").write_text(CS_REFUND_YAML)
        registry = ProcedureRegistry(str(tmp_path))
        assert len(registry.procedures) == 1
        assert "cs_refund" in registry.procedures
