"""Closed inventory of consequential commands accepted by the action kernel."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionSpecification:
    name: str
    required_parameters: frozenset[str]
    authoritative_parameters: frozenset[str]
    requires_consent: bool = False
    requires_approval: bool = False


def _spec(
    name: str,
    required: set[str],
    authoritative: set[str],
    *,
    consent: bool = False,
    approval: bool = False,
) -> ActionSpecification:
    return ActionSpecification(
        name=name,
        required_parameters=frozenset(required),
        authoritative_parameters=frozenset(authoritative),
        requires_consent=consent,
        requires_approval=approval,
    )


ACTION_SPECIFICATIONS = {
    spec.name: spec
    for spec in (
        _spec("issue_refund", {"order_id"}, {"order_id"}, consent=True),
        _spec(
            "issue_store_credit",
            {"order_id", "customer_id", "amount", "currency", "reason"},
            {"order_id", "customer_id", "amount"},
            consent=True,
        ),
        _spec("update_case_status", {"target_status", "reason"}, set()),
        _spec(
            "file_eft_dispute",
            {"customer_id", "transaction_id", "amount", "dispute_type"},
            {"customer_id", "transaction_id", "amount"},
            consent=True,
        ),
        _spec(
            "issue_provisional_credit",
            {"customer_id", "dispute_id", "amount"},
            {"customer_id", "dispute_id", "amount"},
            approval=True,
        ),
        _spec("escalate_to_supervisor", {"reason", "priority"}, set()),
        _spec("add_case_note", {"note"}, set()),
        _spec(
            "flag_account", {"account_id", "reason", "restriction"}, {"account_id"}, approval=True
        ),
        _spec(
            "submit_sar", {"account_id", "alert_id", "narrative_ref"}, {"account_id", "alert_id"},
            approval=True,
        ),
        _spec("close_alert", {"alert_id", "resolution"}, {"alert_id"}, approval=True),
    )
}
