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
    signing_key_id: str | None = None
    activation_signature: str | None = None
    signature: str | None = None

    def canonical_payload(self) -> bytes:
        data = self.model_dump(
            exclude={"signature", "activation_signature"}, mode="json"
        )
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


class PolicySigner:
    def __init__(
        self,
        key: bytes,
        key_id: str = "primary",
        verification_keys: dict[str, bytes] | None = None,
    ):
        if len(key) < 8:
            raise ValueError("Signing key is too short")
        self.key = key
        self.key_id = key_id
        self.verification_keys = {**(verification_keys or {}), key_id: key}

    def approve(self, package: PolicyPackage, approver: str) -> PolicyPackage:
        if approver == package.author:
            raise ValueError("Policy author and approver must be separate")
        approved = package.model_copy(
            update={
                "approver": approver,
                "lifecycle": PolicyLifecycle.APPROVED,
                "signing_key_id": self.key_id,
                "signature": None,
            }
        )
        signature = hmac.new(self.key, approved.canonical_payload(), hashlib.sha256).hexdigest()
        return approved.model_copy(update={"signature": signature})

    def verify(self, package: PolicyPackage) -> bool:
        if (
            not package.signature
            or package.lifecycle
            not in {
                PolicyLifecycle.APPROVED,
                PolicyLifecycle.ACTIVE,
                PolicyLifecycle.RETIRED,
            }
        ):
            return False
        if package.signing_key_id is None:
            return False
        verification_key = self.verification_keys.get(package.signing_key_id)
        if verification_key is None:
            return False
        expected = hmac.new(
            verification_key, package.canonical_payload(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(package.signature, expected)

    def activate(self, package: PolicyPackage) -> PolicyPackage:
        if package.lifecycle is not PolicyLifecycle.APPROVED or not self.verify(package):
            raise ValueError("Only a valid approved package can be activated")
        active = package.model_copy(
            update={
                "lifecycle": PolicyLifecycle.ACTIVE,
                "signing_key_id": self.key_id,
                "signature": None,
            }
        )
        signature = hmac.new(self.key, active.canonical_payload(), hashlib.sha256).hexdigest()
        return active.model_copy(
            update={"signature": signature, "activation_signature": signature}
        )

    def retire(self, package: PolicyPackage) -> PolicyPackage:
        if package.lifecycle is not PolicyLifecycle.ACTIVE or not self.verify(package):
            raise ValueError("Only a valid active package can be retired")
        retired = package.model_copy(
            update={
                "lifecycle": PolicyLifecycle.RETIRED,
                "signing_key_id": self.key_id,
                "signature": None,
            }
        )
        signature = hmac.new(
            self.key, retired.canonical_payload(), hashlib.sha256
        ).hexdigest()
        return retired.model_copy(update={"signature": signature})


class PolicyRegistry:
    """In-process active-package registry; persistence adapters may hydrate it."""

    def __init__(self, signer: PolicySigner):
        self.signer = signer
        self._active: dict[str, PolicyPackage] = {}
        self._packages: dict[str, PolicyPackage] = {}

    def load(self, package: PolicyPackage) -> None:
        if package.lifecycle is not PolicyLifecycle.ACTIVE or not self.signer.verify(package):
            raise ValueError("Policy registry accepts only valid active packages")
        self._active[package.package_id] = package
        self._packages[package.package_id] = package

    def load_history(self, package: PolicyPackage) -> None:
        if package.lifecycle not in {PolicyLifecycle.ACTIVE, PolicyLifecycle.RETIRED}:
            raise ValueError("Policy history accepts only active or retired packages")
        if not self.signer.verify(package):
            raise ValueError("Policy history package signature is invalid")
        self._packages[package.package_id] = package
        if package.lifecycle is PolicyLifecycle.ACTIVE:
            self._active[package.package_id] = package

    def require_active(self, package_id: str) -> PolicyPackage:
        try:
            return self._active[package_id]
        except KeyError as exc:
            raise ValueError(f"Policy package is not active: {package_id}") from exc

    def require_authorization_snapshot(
        self, package_id: str, activation_signature: str
    ) -> PolicyPackage:
        try:
            package = self._packages[package_id]
        except KeyError as exc:
            raise ValueError(f"Policy package history is unavailable: {package_id}") from exc
        if package.activation_signature != activation_signature:
            raise ValueError("Action policy activation snapshot does not match policy history")
        if not self.signer.verify(package):
            raise ValueError("Action policy history signature is invalid")
        return package

    def retire(self, package_id: str) -> None:
        self._active.pop(package_id, None)

    def active_packages(self) -> list[PolicyPackage]:
        return list(self._active.values())

    def clear(self) -> None:
        self._active.clear()
        self._packages.clear()
