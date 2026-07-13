"""Authoritative resource adapters used by the typed action bridge.

The reference-data adapter exists for the bundled Shiny demonstration.  It is
read-only and converts the seeded local business database into the same
versioned resource contract expected from production provider bundles.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from workflow_engine.database import query_one


class ResourceProvider(Protocol):
    async def get_resource(
        self, resource_type: str, resource_id: str
    ) -> dict[str, Any] | None: ...


_REFERENCE_QUERIES: dict[str, tuple[str, str]] = {
    "order": ("orders", "order_id"),
    "transaction": ("transactions", "transaction_id"),
    "dispute": ("disputes", "dispute_id"),
    "account": ("accounts", "account_id"),
    "fraud_alert": ("fraud_alerts", "alert_id"),
}


class ReferenceDataResourceProvider:
    """Read-only authoritative adapter for the bundled SQLite demo dataset."""

    async def get_resource(
        self, resource_type: str, resource_id: str
    ) -> dict[str, Any] | None:
        binding = _REFERENCE_QUERIES.get(resource_type)
        if binding is None:
            return None
        table, key = binding
        row = await query_one(
            f"SELECT * FROM {table} WHERE {key} = ?",  # allow-listed identifiers above
            (resource_id,),
        )
        if row is None:
            return None
        payload = dict(row)
        if resource_type == "order":
            payload.update(
                {
                    "amount": payload.get("total"),
                    "refund_amount": payload.get("total"),
                    "currency": payload.get("currency") or "USD",
                    "payment_method": payload.get("payment_method")
                    or "original_payment_method",
                }
            )
        elif resource_type == "transaction":
            payload["transaction_id"] = payload.get("txn_id", resource_id)
            ownership = await query_one(
                "SELECT customer_id FROM disputes WHERE transaction_id = ? "
                "ORDER BY reported_date DESC LIMIT 1",
                (resource_id,),
            )
            if ownership is not None:
                payload["customer_id"] = ownership["customer_id"]
        canonical = json.dumps(payload, sort_keys=True, default=str).encode()
        version = int(hashlib.sha256(canonical).hexdigest()[:12], 16)
        return {"payload": payload, "version": version, "source": "reference-data"}


class ChainedResourceProvider:
    """Resolve through ordered providers without mixing resource versions."""

    def __init__(self, *providers: ResourceProvider):
        self.providers = providers

    async def get_resource(
        self, resource_type: str, resource_id: str
    ) -> dict[str, Any] | None:
        for provider in self.providers:
            resource = await provider.get_resource(resource_type, resource_id)
            if resource is not None:
                return resource
        return None
