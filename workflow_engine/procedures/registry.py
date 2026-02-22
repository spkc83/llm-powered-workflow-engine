"""Procedure registry - loads and indexes all procedures."""
from pathlib import Path
from typing import Optional
from .loader import load_procedure, get_procedure_tools


class ProcedureRegistry:
    """Registry that loads all procedure YAML files and provides lookup methods."""

    def __init__(self, procedures_dir: str):
        """Initialize the registry and load all procedures.

        Args:
            procedures_dir: Path to the directory containing YAML procedure files.
        """
        self.procedures_dir = Path(procedures_dir)
        self.procedures: dict[str, dict] = {}
        self._intent_map: dict[str, str] = {}
        self.load_all()

    def load_all(self) -> None:
        """Scan procedures directory and load all valid YAML files."""
        if not self.procedures_dir.exists():
            raise FileNotFoundError(f"Procedures directory not found: {self.procedures_dir}")

        for yaml_file in sorted(self.procedures_dir.glob("*.yaml")):
            try:
                procedure = load_procedure(str(yaml_file))
                proc_id = procedure["id"]
                self.procedures[proc_id] = procedure

                # Build intent map
                for intent in procedure.get("trigger_intents", []):
                    self._intent_map[intent.lower()] = proc_id
            except (ValueError, FileNotFoundError, Exception) as e:
                print(f"Warning: Skipping invalid procedure file {yaml_file}: {e}")

    def get_procedure(self, procedure_id: str) -> Optional[dict]:
        """Get a procedure by its ID.

        Args:
            procedure_id: The procedure ID.

        Returns:
            The procedure dict, or None if not found.
        """
        return self.procedures.get(procedure_id)

    def get_procedures_for_domain(self, domain: str) -> list[dict]:
        """Get all procedures matching a domain prefix.

        Args:
            domain: Domain prefix to match (e.g., "cs" for customer service,
                    "fraud" for fraud operations).

        Returns:
            List of matching procedure dicts.
        """
        return [
            proc for proc_id, proc in self.procedures.items()
            if proc_id.startswith(domain)
        ]

    def get_all_trigger_intents(self) -> dict[str, str]:
        """Get mapping of all trigger intent keywords to procedure IDs.

        Returns:
            Dict mapping intent keyword -> procedure_id.
        """
        return dict(self._intent_map)

    def get_procedure_tool_names(self, procedure_id: str) -> list[str]:
        """Get tool names for a specific procedure.

        Args:
            procedure_id: The procedure ID.

        Returns:
            List of tool name strings, or empty list if procedure not found.
        """
        proc = self.get_procedure(procedure_id)
        if proc is None:
            return []
        return get_procedure_tools(proc)
