"""Minimal governed policy packages with separated approval and HMAC signing."""

import hashlib
import hmac
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel


class PolicyLifecycle(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    ACTIVE = "active"
    RETIRED = "retired"


class PolicyPackage(BaseModel):
    package_id: str
    procedure_id: str
    version: str
    jurisdiction: str
    author: str
    rules: dict[str, Any]
    lifecycle: PolicyLifecycle = PolicyLifecycle.DRAFT
    approver: str | None = None
    signature: str | None = None

    def canonical_payload(self) -> bytes:
        data = self.model_dump(exclude={"signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


class PolicySigner:
    def __init__(self, key: bytes):
        if len(key) < 8:
            raise ValueError("Signing key is too short")
        self.key = key

    def approve(self, package: PolicyPackage, approver: str) -> PolicyPackage:
        if approver == package.author:
            raise ValueError("Policy author and approver must be separate")
        approved = package.model_copy(
            update={"approver": approver, "lifecycle": PolicyLifecycle.APPROVED, "signature": None}
        )
        signature = hmac.new(self.key, approved.canonical_payload(), hashlib.sha256).hexdigest()
        return approved.model_copy(update={"signature": signature})

    def verify(self, package: PolicyPackage) -> bool:
        if not package.signature or package.lifecycle not in {PolicyLifecycle.APPROVED, PolicyLifecycle.ACTIVE}:
            return False
        expected = hmac.new(self.key, package.canonical_payload(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(package.signature, expected)

    def activate(self, package: PolicyPackage) -> PolicyPackage:
        if not self.verify(package):
            raise ValueError("Only a valid approved package can be activated")
        active = package.model_copy(update={"lifecycle": PolicyLifecycle.ACTIVE, "signature": None})
        signature = hmac.new(self.key, active.canonical_payload(), hashlib.sha256).hexdigest()
        return active.model_copy(update={"signature": signature})


class PolicyRegistry:
    """In-process active-package registry; persistence adapters may hydrate it."""

    def __init__(self, signer: PolicySigner):
        self.signer = signer
        self._active: dict[str, PolicyPackage] = {}

    def load(self, package: PolicyPackage) -> None:
        if package.lifecycle is not PolicyLifecycle.ACTIVE or not self.signer.verify(package):
            raise ValueError("Policy registry accepts only valid active packages")
        self._active[package.package_id] = package

    def require_active(self, package_id: str) -> PolicyPackage:
        try:
            return self._active[package_id]
        except KeyError as exc:
            raise ValueError(f"Policy package is not active: {package_id}") from exc
