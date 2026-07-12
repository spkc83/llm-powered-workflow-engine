"""Deterministic domain decisions kept outside prompts and ADK state."""

from pydantic import BaseModel


class RefundDecision(BaseModel):
    eligible: bool
    reason: str
    amount: float
    idempotency_key: str


class OrderSnapshot(BaseModel):
    order_id: str
    customer_id: str
    status: str
    days_since_delivery: int
    amount: float
    payment_method: str
    evidence_ref: str


class RefundDecisionService:
    def __init__(self, refund_window_days: int = 30):
        self.refund_window_days = refund_window_days

    def evaluate(
        self,
        *,
        order_id: str,
        authenticated_customer_id: str,
        order_customer_id: str,
        order_status: str,
        days_since_delivery: int,
        amount: float,
    ) -> RefundDecision:
        key = f"refund:{order_id}"
        if authenticated_customer_id != order_customer_id:
            return RefundDecision(eligible=False, reason="ownership_mismatch", amount=amount, idempotency_key=key)
        if order_status not in {"delivered", "completed"}:
            return RefundDecision(eligible=False, reason="order_not_complete", amount=amount, idempotency_key=key)
        if days_since_delivery > self.refund_window_days:
            return RefundDecision(eligible=False, reason="outside_refund_window", amount=amount, idempotency_key=key)
        if amount <= 0:
            return RefundDecision(eligible=False, reason="invalid_amount", amount=amount, idempotency_key=key)
        return RefundDecision(eligible=True, reason="eligible", amount=amount, idempotency_key=key)


class RegEDecision(BaseModel):
    eligible: bool
    liability_tier: str
    max_liability: float
    reason: str


class RegEDecisionService:
    covered_methods = {"debit", "debit_card", "ach", "p2p", "atm", "electronic_transfer"}

    def evaluate(self, payment_method: str, days_since_noticed: int, amount: float) -> RegEDecision:
        if payment_method.lower() not in self.covered_methods:
            return RegEDecision(
                eligible=False, liability_tier="not_covered", max_liability=amount,
                reason="not_eft",
            )
        if days_since_noticed <= 2:
            return RegEDecision(eligible=True, liability_tier="tier_1", max_liability=50, reason="eligible")
        if days_since_noticed <= 60:
            return RegEDecision(eligible=True, liability_tier="tier_2", max_liability=500, reason="eligible")
        return RegEDecision(
            eligible=False, liability_tier="tier_3", max_liability=amount,
            reason="outside_60_day_window",
        )
