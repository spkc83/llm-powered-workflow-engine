"""Deterministic development adapters that emulate upstream contracts truthfully."""

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import aiosqlite

from workflow_engine.core.gateway import ConnectorOutcome
from workflow_engine.core.kernel import ActionCommand
from workflow_engine.integrations.contracts import (
    DeliveryStatus,
    HandoffReceipt,
    HandoffRequest,
    ProviderReceipt,
    SttRequest,
    SttResult,
    TelephonyEvent,
    TtsRequest,
    TtsResult,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_SENSITIVE_KEY_FRAGMENTS = {
    "password", "secret", "token", "pin", "cvv", "card_number", "ssn",
    "social_security", "private_key",
}


def _sensitive_paths(value: Any, prefix: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if any(fragment in str(key).lower() for fragment in _SENSITIVE_KEY_FRAGMENTS):
                found.add(path)
            found.update(_sensitive_paths(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.update(_sensitive_paths(nested, f"{prefix}[{index}]"))
    return found


class SandboxScenario(str, Enum):
    SUCCESS = "success"
    REJECTED = "rejected"
    TIMEOUT_BEFORE_COMMIT = "timeout_before_commit"
    TIMEOUT_AFTER_COMMIT = "timeout_after_commit"


class StubSpeechToTextAdapter:
    provider_id = "sandbox-stt"

    def __init__(self, confidence: float = 0.95):
        self.confidence = confidence

    async def transcribe(self, request: SttRequest) -> SttResult:
        redacted = request.contains_secret_dtmf
        transcript = "[REDACTED DTMF]" if redacted else (request.transcript_hint or "")
        return SttResult(
            provider_id=self.provider_id,
            event_id=request.event_id,
            call_id=request.call_id,
            transcript=transcript,
            confidence=0.0 if redacted else self.confidence,
            is_final=request.is_final,
            simulated=True,
            redacted=redacted,
        )


class StubTextToSpeechAdapter:
    provider_id = "sandbox-tts"

    async def synthesize(self, request: TtsRequest) -> TtsResult:
        digest = hashlib.sha256(
            f"{request.locale}:{request.voice}:{request.ssml}:{request.text}".encode()
        ).hexdigest()[:24]
        return TtsResult(
            provider_id=self.provider_id,
            request_id=request.request_id,
            call_id=request.call_id,
            playback_id=f"PB-{digest}",
            media_ref=f"sandbox://tts/{digest}",
            simulated=True,
        )


class LocalTelephonyAdapter:
    provider_id = "sandbox-telephony"

    async def accept_event(self, event: TelephonyEvent) -> ProviderReceipt:
        return ProviderReceipt(
            provider_id=self.provider_id,
            provider_message_id=event.event_id,
            status=DeliveryStatus.ACCEPTED,
            occurred_at=_now(),
            details={"call_id": event.call_id, "event_type": event.event_type.value, "simulated": True},
        )


class SQLiteDeliveryReceiptStore:
    """Durable development receipt ledger shared by local channel adapters."""

    def __init__(self, path: str | Path):
        self.path = str(path)

    async def initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS sandbox_delivery_receipts (
                provider_id TEXT NOT NULL, provider_message_id TEXT NOT NULL,
                status TEXT NOT NULL, occurred_at TEXT NOT NULL, receipt_json TEXT NOT NULL,
                PRIMARY KEY(provider_id,provider_message_id,status))"""
            )
            await db.commit()

    async def record(self, receipt: ProviderReceipt) -> ProviderReceipt:
        sensitive = _sensitive_paths(receipt.details)
        if sensitive:
            raise ValueError(
                "Delivery receipt rejects sensitive fields: "
                + ", ".join(sorted(sensitive))
            )
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO sandbox_delivery_receipts VALUES (?,?,?,?,?)",
                (
                    receipt.provider_id,
                    receipt.provider_message_id,
                    receipt.status.value,
                    receipt.occurred_at,
                    receipt.model_dump_json(),
                ),
            )
            await db.commit()
        return receipt

    async def list(self, limit: int = 100) -> list[ProviderReceipt]:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            rows = await (await db.execute(
                """SELECT receipt_json FROM sandbox_delivery_receipts
                ORDER BY occurred_at DESC LIMIT ?""",
                (limit,),
            )).fetchall()
        return [ProviderReceipt.model_validate_json(row[0]) for row in rows]


class LocalChatAdapter:
    provider_id = "local-chat"

    def __init__(self, receipts: SQLiteDeliveryReceiptStore):
        self.receipts = receipts

    async def send(self, message: dict[str, Any]) -> ProviderReceipt:
        message_id = message.get("message_id") or "MSG-" + hashlib.sha256(
            json.dumps(message, sort_keys=True).encode()
        ).hexdigest()[:20].upper()
        return await self.receipts.record(
            ProviderReceipt(
                provider_id=self.provider_id,
                provider_message_id=message_id,
                status=DeliveryStatus.DELIVERED,
                occurred_at=_now(),
                details={"simulated": True, "conversation_id": message.get("conversation_id")},
            )
        )


class SQLiteSandboxActionConnector:
    """Contract-faithful action-system emulator with fault injection and reconciliation."""

    provider_id = "sqlite-action-sandbox"

    def __init__(self, path: str | Path):
        self.path = str(path)

    async def initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sandbox_authoritative_resources (
                    resource_type TEXT NOT NULL, resource_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL, version INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(resource_type, resource_id)
                );
                CREATE TABLE IF NOT EXISTS sandbox_action_scenarios (
                    idempotency_key TEXT PRIMARY KEY,
                    scenario TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sandbox_action_effects (
                    idempotency_key TEXT PRIMARY KEY,
                    provider_action_id TEXT UNIQUE NOT NULL,
                    action TEXT NOT NULL,
                    command_json TEXT NOT NULL,
                    committed_at TEXT NOT NULL
                );
                """
            )
            await db.commit()

    async def put_resource(
        self, resource_type: str, resource_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Seed authoritative sandbox state; exposed only by development APIs."""
        rejected = _sensitive_paths(payload)
        if rejected:
            raise ValueError(
                "Sandbox resources reject sensitive fields: " + ", ".join(sorted(rejected))
            )
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO sandbox_authoritative_resources
                (resource_type,resource_id,payload_json,version,updated_at)
                VALUES (?,?,?,1,?) ON CONFLICT(resource_type,resource_id) DO UPDATE SET
                payload_json=excluded.payload_json, version=version+1,
                updated_at=excluded.updated_at""",
                (resource_type, resource_id, json.dumps(payload), _now()),
            )
            await db.commit()
        resource = await self.get_resource(resource_type, resource_id)
        assert resource is not None
        return resource

    async def get_resource(
        self, resource_type: str, resource_id: str
    ) -> dict[str, Any] | None:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                """SELECT * FROM sandbox_authoritative_resources
                WHERE resource_type=? AND resource_id=?""",
                (resource_type, resource_id),
            )).fetchone()
        if not row:
            return None
        data = dict(row)
        data["payload"] = json.loads(data.pop("payload_json"))
        return data

    async def set_scenario(self, idempotency_key: str, scenario: SandboxScenario) -> None:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO sandbox_action_scenarios VALUES (?, ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET scenario=excluded.scenario""",
                (idempotency_key, scenario.value),
            )
            await db.commit()

    async def _scenario(self, key: str) -> SandboxScenario:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute(
                "SELECT scenario FROM sandbox_action_scenarios WHERE idempotency_key=?", (key,)
            )).fetchone()
        return SandboxScenario(row[0]) if row else SandboxScenario.SUCCESS

    async def _effect(self, key: str) -> dict[str, Any] | None:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM sandbox_action_effects WHERE idempotency_key=?", (key,)
            )).fetchone()
        return dict(row) if row else None

    async def _commit(self, command: ActionCommand) -> dict[str, Any]:
        provider_action_id = "SBX-" + hashlib.sha256(
            command.idempotency_key.encode()
        ).hexdigest()[:20].upper()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT OR IGNORE INTO sandbox_action_effects
                (idempotency_key,provider_action_id,action,command_json,committed_at)
                VALUES (?,?,?,?,?)""",
                (
                    command.idempotency_key,
                    provider_action_id,
                    command.action,
                    command.model_dump_json(),
                    _now(),
                ),
            )
            await db.commit()
        effect = await self._effect(command.idempotency_key)
        assert effect is not None
        return effect

    async def dispatch(self, command: ActionCommand) -> ConnectorOutcome:
        existing = await self._effect(command.idempotency_key)
        if existing:
            return ConnectorOutcome.succeeded(self._details(existing, idempotent_replay=True))
        scenario = await self._scenario(command.idempotency_key)
        if scenario is SandboxScenario.REJECTED:
            return ConnectorOutcome.failed(
                {"provider_id": self.provider_id, "reason": "sandbox_rejected", "simulated": True}
            )
        if scenario is SandboxScenario.TIMEOUT_BEFORE_COMMIT:
            return ConnectorOutcome.unknown(
                {"provider_id": self.provider_id, "reason": scenario.value, "simulated": True}
            )
        effect = await self._commit(command)
        if scenario is SandboxScenario.TIMEOUT_AFTER_COMMIT:
            return ConnectorOutcome.unknown(
                {
                    "provider_id": self.provider_id,
                    "provider_action_id": effect["provider_action_id"],
                    "reason": scenario.value,
                    "simulated": True,
                }
            )
        return ConnectorOutcome.succeeded(self._details(effect))

    async def reconcile(
        self, command: ActionCommand, prior: dict[str, Any] | None
    ) -> ConnectorOutcome:
        effect = await self._effect(command.idempotency_key)
        if effect:
            return ConnectorOutcome.succeeded(self._details(effect, reconciled=True))
        return ConnectorOutcome.unknown(
            {
                "provider_id": self.provider_id,
                "reason": "no_authoritative_provider_record",
                "prior": prior or {},
                "simulated": True,
            }
        )

    def _details(self, effect: dict[str, Any], **extra: Any) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_action_id": effect["provider_action_id"],
            "action": effect["action"],
            "committed_at": effect["committed_at"],
            "simulated": True,
            **extra,
        }


class SQLiteHandoffQueueAdapter:
    provider_id = "sqlite-handoff-sandbox"

    def __init__(self, path: str | Path):
        self.path = str(path)

    async def initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS sandbox_handoff_tickets (
                provider_ticket_id TEXT PRIMARY KEY, handoff_id TEXT UNIQUE NOT NULL,
                request_json TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL)"""
            )
            await db.commit()

    async def enqueue(self, request: HandoffRequest) -> HandoffReceipt:
        await self.initialize()
        ticket_id = "TKT-" + hashlib.sha256(request.handoff_id.encode()).hexdigest()[:16].upper()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO sandbox_handoff_tickets VALUES (?,?,?,?,?)",
                (ticket_id, request.handoff_id, request.model_dump_json(), "queued", _now()),
            )
            await db.commit()
        return await self.status(ticket_id)

    async def set_status(self, provider_ticket_id: str, status: str) -> HandoffReceipt:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "UPDATE sandbox_handoff_tickets SET status=?, updated_at=? WHERE provider_ticket_id=?",
                (status, _now(), provider_ticket_id),
            )
            await db.commit()
            if cursor.rowcount != 1:
                raise KeyError(provider_ticket_id)
        return await self.status(provider_ticket_id)

    async def status(self, provider_ticket_id: str) -> HandoffReceipt:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute(
                "SELECT handoff_id,status FROM sandbox_handoff_tickets WHERE provider_ticket_id=?",
                (provider_ticket_id,),
            )).fetchone()
        if not row:
            raise KeyError(provider_ticket_id)
        return HandoffReceipt(
            provider_id=self.provider_id,
            handoff_id=row[0],
            provider_ticket_id=provider_ticket_id,
            status=row[1],
            details={"simulated": True},
        )


class DisabledActionConnector:
    provider_id = "disabled"

    async def dispatch(self, command: ActionCommand) -> ConnectorOutcome:
        return ConnectorOutcome.failed(
            {"provider_id": self.provider_id, "reason": "upstream_adapter_disabled"}
        )

    async def reconcile(
        self, command: ActionCommand, prior: dict[str, Any] | None
    ) -> ConnectorOutcome:
        return ConnectorOutcome.unknown(
            {"provider_id": self.provider_id, "reason": "upstream_adapter_disabled", "prior": prior or {}}
        )
