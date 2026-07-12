"""Bounded ADK 2.x graph: interpretation and composition, never authorization."""

from typing import Any

from google.adk import Workflow
from pydantic import BaseModel, Field

from workflow_engine.core.kernel import FactAuthority


class CandidateProposal(BaseModel):
    intent: str
    extracted_facts: dict[str, Any] = Field(default_factory=dict)
    evidence_spans: dict[str, str] = Field(default_factory=dict)


class ValidatedProposal(CandidateProposal):
    fact_authority: FactAuthority = FactAuthority.ASSERTED


class ComposedResponse(BaseModel):
    text: str
    authoritative_status: str | None = None


def validate_proposal(proposal: CandidateProposal) -> ValidatedProposal:
    missing_evidence = set(proposal.extracted_facts) - set(proposal.evidence_spans)
    if missing_evidence:
        raise ValueError(f"Extracted facts lack evidence spans: {sorted(missing_evidence)}")
    return ValidatedProposal(**proposal.model_dump(), fact_authority=FactAuthority.ASSERTED)


def compose_grounded_response(proposal: ValidatedProposal) -> ComposedResponse:
    return ComposedResponse(
        text=f"I understood this as {proposal.intent}. I will verify the relevant details before any action."
    )


def build_bounded_interaction_graph() -> Workflow:
    return Workflow(
        name="bounded_interaction_graph",
        description="Proposal validation and grounded response composition only",
        input_schema=CandidateProposal,
        output_schema=ComposedResponse,
        edges=[("START", validate_proposal, compose_grounded_response)],
    )
