"""Replay and canary gates kept separate from probabilistic ADK evaluation."""

import hashlib
import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel


class ReplayResult(BaseModel):
    deterministic: bool
    expected_hash: str
    actual_hash: str


class ReplayHarness:
    @staticmethod
    def _hash(value: Any) -> str:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    def replay(self, decision: Callable[..., Any], inputs: dict[str, Any], expected: Any) -> ReplayResult:
        actual = decision(**inputs)
        expected_hash = self._hash(expected)
        actual_hash = self._hash(actual)
        return ReplayResult(
            deterministic=expected_hash == actual_hash,
            expected_hash=expected_hash,
            actual_hash=actual_hash,
        )


class RolloutGate(BaseModel):
    procedure_id: str
    channel: str
    risk_tier: str
    enabled_percent: int = 0
    unauthorized_actions: int = 0
    mandatory_evidence_rate: float = 1.0

    def may_advance(self) -> bool:
        return self.unauthorized_actions == 0 and self.mandatory_evidence_rate == 1.0
