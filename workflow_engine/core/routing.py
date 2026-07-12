"""Deterministic coarse routing, composition, and procedure-version locking."""

from typing import Any

from pydantic import BaseModel, Field


class ProcedureRoute(BaseModel):
    primary_procedure: str
    subprocedures: list[str] = Field(default_factory=list)
    versions: dict[str, str]


class ProcedureRouter:
    def __init__(self, catalog: dict[str, dict[str, Any]]):
        self.catalog = catalog

    def route(self, text: str, current: ProcedureRoute | None) -> ProcedureRoute:
        if current is not None:
            return current
        words = set(text.lower().replace(",", " ").split())
        matches = [
            procedure_id
            for procedure_id, definition in self.catalog.items()
            if words & set(definition["keywords"])
        ]
        if not matches:
            raise ValueError("No deterministic procedure match")
        # Regulatory dispute takes precedence over ordinary servicing when both
        # are present; other procedures remain explicit composed subprocedures.
        matches.sort(key=lambda value: ("dispute" not in value, value))
        return ProcedureRoute(
            primary_procedure=matches[0],
            subprocedures=matches[1:],
            versions={item: self.catalog[item]["version"] for item in matches},
        )
