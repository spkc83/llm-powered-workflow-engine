"""Durable, database-portable case/fact/action kernel.

SQLite is the built-in adapter. Other databases implement ``CoreStore`` without
changing policy, conversation, or action semantics.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol

import aiosqlite
from pydantic import BaseModel, Field, computed_field

from workflow_engine.core.action_specs import ACTION_SPECIFICATIONS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CaseConflict(RuntimeError):
    pass


class ActionConflict(RuntimeError):
    pass


class HandoffConflict(RuntimeError):
    pass


class FactAuthority(str, Enum):
    ASSERTED = "asserted"
    OBSERVED = "observed"
    VERIFIED = "verified"
    DERIVED = "derived"


_AUTHORITY_RANK = {
    FactAuthority.ASSERTED: 0,
    FactAuthority.OBSERVED: 1,
    FactAuthority.DERIVED: 1,
    FactAuthority.VERIFIED: 2,
}


class ActionStatus(str, Enum):
    REQUESTED = "requested"
    AUTHORIZED = "authorized"
    DISPATCHED = "dispatched"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    RECONCILED = "reconciled"


class ActionProposalStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class OutboxStatus(str, Enum):
    PENDING = "pending"
    LEASED = "leased"
    DELIVERED = "delivered"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class CaseRecord(BaseModel):
    case_id: str
    customer_id: str
    procedure_id: str
    procedure_version: str
    status: str
    version: int


class FactProposal(BaseModel):
    name: str
    value: Any
    authority: FactAuthority
    source: str
    evidence_ref: str
    expires_at: str | None = None


class FactRecord(FactProposal):
    case_id: str
    committed_at: str
    superseded_at: str | None = None


class ActionCommand(BaseModel):
    action: str
    case_id: str
    policy_package_id: str
    actor_id: str
    idempotency_key: str = Field(min_length=4)
    parameters: dict[str, Any]
    parameter_fact_refs: dict[str, str]
    required_fact_authority: dict[str, FactAuthority]
    consent_evidence_ref: str | None = None
    approval_evidence_ref: str | None = None
    policy_activation_signature: str | None = None
    connector_binding_id: str | None = None
    connector_binding_version: str | None = None
    contract_version: str | None = None


class ActionRecord(BaseModel):
    action_id: str
    command: ActionCommand
    status: ActionStatus
    outcome: dict[str, Any] | None = None
    created_at: str
    updated_at: str


class ActionProposal(BaseModel):
    proposal_id: str
    action: str
    payload: dict[str, Any]
    case_id: str
    customer_id: str
    actor_id: str
    procedure_id: str
    procedure_version: str
    policy_package_id: str
    idempotency_key: str
    resource_type: str | None = None
    resource_id: str | None = None
    resource_version: int | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    connector_binding_id: str | None = None
    connector_binding_version: str | None = None
    contract_version: str | None = None
    preview: dict[str, Any] = Field(default_factory=dict)
    status: ActionProposalStatus
    confirmation_evidence_ref: str | None = None
    action_id: str | None = None
    created_at: str
    expires_at: str
    updated_at: str
    confirmed_at: str | None = None
    cancelled_at: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def safe_preview(self) -> dict[str, Any]:
        return self.preview


class OutboxRecord(BaseModel):
    outbox_id: str
    topic: str
    aggregate_id: str
    payload: dict[str, Any]
    status: OutboxStatus
    attempts: int = 0
    available_at: str
    lease_owner: str | None = None
    lease_until: str | None = None
    last_error: str | None = None
    created_at: str
    updated_at: str


class CoreStore(Protocol):
    async def initialize(self) -> None: ...
    async def create_case(self, record: CaseRecord) -> None: ...
    async def get_case(self, case_id: str) -> CaseRecord | None: ...
    async def append_fact(self, case_id: str, proposal: FactProposal, expected_version: int) -> CaseRecord: ...
    async def get_fact(self, case_id: str, name: str) -> FactRecord | None: ...
    async def insert_action(self, record: ActionRecord, expected_version: int) -> ActionRecord: ...
    async def get_action_by_key(self, key: str) -> ActionRecord | None: ...
    async def get_action(self, action_id: str) -> ActionRecord | None: ...
    async def list_actions(self, status: ActionStatus | None = None, limit: int = 100) -> list[ActionRecord]: ...
    async def list_action_events(self, action_id: str) -> list[dict[str, Any]]: ...
    async def update_action(self, action_id: str, status: ActionStatus, outcome: dict | None) -> ActionRecord: ...
    async def transition_action(self, action_id: str, expected: ActionStatus, status: ActionStatus, outcome: dict | None) -> ActionRecord: ...
    async def claim_action(self, action_id: str) -> tuple[ActionRecord, bool]: ...
    async def create_action_proposal(self, record: ActionProposal) -> ActionProposal: ...
    async def get_action_proposal(self, proposal_id: str) -> ActionProposal | None: ...
    async def list_action_proposals(
        self,
        *,
        customer_id: str | None = None,
        conversation_id: str | None = None,
        status: ActionProposalStatus | None = None,
        limit: int = 100,
    ) -> list[ActionProposal]: ...
    async def transition_action_proposal(
        self,
        proposal_id: str,
        expected: ActionProposalStatus,
        status: ActionProposalStatus,
        *,
        confirmation_evidence_ref: str | None = None,
        action_id: str | None = None,
    ) -> ActionProposal: ...
    async def enqueue_outbox(self, topic: str, aggregate_id: str, payload: dict[str, Any]) -> OutboxRecord: ...
    async def claim_outbox(self, owner: str, lease_seconds: int, limit: int = 10) -> list[OutboxRecord]: ...
    async def complete_outbox(self, outbox_id: str) -> OutboxRecord: ...
    async def fail_outbox(self, outbox_id: str, error: str, retry_at: str | None, quarantine: bool = False) -> OutboxRecord: ...
    async def list_outbox(self, status: OutboxStatus | None = None, limit: int = 100) -> list[OutboxRecord]: ...
    async def accept_message(self, envelope: dict[str, Any]) -> bool: ...
    async def accept_message_result(self, envelope: dict[str, Any]) -> dict[str, Any]: ...
    async def list_quarantined_messages(self, limit: int = 100) -> list[dict[str, Any]]: ...
    async def create_handoff(self, record: dict[str, Any]) -> None: ...
    async def get_handoff(self, handoff_id: str) -> dict[str, Any] | None: ...
    async def update_handoff(self, handoff_id: str, status: str, agent_id: str | None) -> dict[str, Any]: ...
    async def transition_handoff(self, handoff_id: str, expected: str, status: str, agent_id: str | None) -> dict[str, Any]: ...


class SQLiteCoreStore:
    """SQLite adapter with transactional optimistic concurrency and uniqueness."""

    def __init__(self, path: str | Path):
        self.path = str(path)

    async def initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS core_migrations (
                    name TEXT PRIMARY KEY, applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_cases (
                    case_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
                    procedure_id TEXT NOT NULL, procedure_version TEXT NOT NULL,
                    status TEXT NOT NULL, version INTEGER NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS case_facts (
                    case_id TEXT NOT NULL, name TEXT NOT NULL, value_json TEXT NOT NULL,
                    authority TEXT NOT NULL, source TEXT NOT NULL, evidence_ref TEXT NOT NULL,
                    committed_at TEXT NOT NULL, expires_at TEXT, superseded_at TEXT,
                    PRIMARY KEY(case_id, name),
                    FOREIGN KEY(case_id) REFERENCES workflow_cases(case_id)
                );
                CREATE TABLE IF NOT EXISTS action_attempts (
                    action_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
                    case_id TEXT NOT NULL, command_json TEXT NOT NULL, status TEXT NOT NULL,
                    outcome_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(case_id) REFERENCES workflow_cases(case_id)
                );
                CREATE TABLE IF NOT EXISTS action_events (
                    event_id TEXT PRIMARY KEY, action_id TEXT NOT NULL,
                    status TEXT NOT NULL, details_json TEXT, recorded_at TEXT NOT NULL,
                    FOREIGN KEY(action_id) REFERENCES action_attempts(action_id)
                );
                CREATE TABLE IF NOT EXISTS action_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    procedure_id TEXT NOT NULL,
                    procedure_version TEXT NOT NULL,
                    policy_package_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    resource_type TEXT,
                    resource_id TEXT,
                    resource_version INTEGER,
                    conversation_id TEXT,
                    message_id TEXT,
                    connector_binding_id TEXT,
                    connector_binding_version TEXT,
                    contract_version TEXT,
                    preview_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    confirmation_evidence_ref TEXT,
                    action_id TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    confirmed_at TEXT,
                    cancelled_at TEXT,
                    FOREIGN KEY(action_id) REFERENCES action_attempts(action_id)
                );
                CREATE INDEX IF NOT EXISTS idx_action_proposals_customer
                    ON action_proposals(customer_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_action_proposals_conversation
                    ON action_proposals(conversation_id, created_at);
                CREATE TABLE IF NOT EXISTS inbox_messages (
                    message_id TEXT PRIMARY KEY, envelope_json TEXT NOT NULL, received_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversation_inbox (
                    provider_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    envelope_json TEXT NOT NULL, received_at TEXT NOT NULL,
                    PRIMARY KEY(provider_id, message_id)
                );
                CREATE TABLE IF NOT EXISTS conversation_inbox_v3 (
                    provider_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL, sequence INTEGER,
                    envelope_json TEXT NOT NULL, ordering_status TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    PRIMARY KEY(provider_id, message_id)
                );
                CREATE TABLE IF NOT EXISTS conversation_sequences (
                    provider_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    last_sequence INTEGER NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(provider_id, conversation_id)
                );
                CREATE TABLE IF NOT EXISTS core_outbox (
                    outbox_id TEXT PRIMARY KEY, topic TEXT NOT NULL, aggregate_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL,
                    available_at TEXT NOT NULL, lease_owner TEXT, lease_until TEXT, last_error TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_core_outbox_claim
                    ON core_outbox(status, available_at, lease_until);
                CREATE TABLE IF NOT EXISTS handoffs (
                    handoff_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, case_id TEXT NOT NULL,
                    context_json TEXT NOT NULL, status TEXT NOT NULL, assigned_agent_id TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                """
            )
            await db.execute("BEGIN IMMEDIATE")
            migration = await (await db.execute(
                "SELECT 1 FROM core_migrations WHERE name='action_events_v3_backfill'"
            )).fetchone()
            if migration is None:
                # Backfill append evidence for pre-v3 actions. Exact historical
                # timestamps were not recorded, so reconstructed events are marked.
                legacy_actions = await (await db.execute(
                    """SELECT a.action_id,a.status,a.created_at,a.updated_at
                    FROM action_attempts a LEFT JOIN action_events e
                      ON e.action_id=a.action_id WHERE e.action_id IS NULL"""
                )).fetchall()
                terminal = {
                    ActionStatus.SUCCEEDED.value,
                    ActionStatus.FAILED.value,
                    ActionStatus.UNKNOWN.value,
                    ActionStatus.RECONCILED.value,
                }
                for action_id, status, created_at, updated_at in legacy_actions:
                    sequence = [ActionStatus.REQUESTED.value]
                    if status != ActionStatus.REQUESTED.value:
                        sequence.append(ActionStatus.AUTHORIZED.value)
                    if status in {ActionStatus.DISPATCHED.value, *terminal}:
                        sequence.append(ActionStatus.DISPATCHED.value)
                    if status == ActionStatus.RECONCILED.value:
                        sequence.append(ActionStatus.UNKNOWN.value)
                    if status in terminal:
                        sequence.append(status)
                    for event_status in sequence:
                        await db.execute(
                            "INSERT INTO action_events VALUES (?,?,?,?,?)",
                            (
                                f"AEV-{uuid.uuid4().hex}", action_id, event_status,
                                json.dumps({"migrated": True}),
                                updated_at if event_status == status else created_at,
                            ),
                        )
                await db.execute(
                    "INSERT INTO core_migrations VALUES (?,?)",
                    ("action_events_v3_backfill", _now()),
                )
            await db.commit()

    async def create_case(self, record: CaseRecord) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO workflow_cases VALUES (?, ?, ?, ?, ?, ?, ?)",
                (*record.model_dump().values(), _now()),
            )
            await db.commit()

    async def get_case(self, case_id: str) -> CaseRecord | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM workflow_cases WHERE case_id=?", (case_id,))).fetchone()
            return CaseRecord(**dict(row)) if row else None

    async def append_fact(self, case_id: str, proposal: FactProposal, expected_version: int) -> CaseRecord:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "UPDATE workflow_cases SET version=version+1 WHERE case_id=? AND version=?",
                (case_id, expected_version),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                raise CaseConflict(f"Case {case_id} version conflict")
            await db.execute(
                """INSERT INTO case_facts
                (case_id,name,value_json,authority,source,evidence_ref,committed_at,expires_at,superseded_at)
                VALUES (?,?,?,?,?,?,?,?,NULL)
                ON CONFLICT(case_id,name) DO UPDATE SET
                  value_json=excluded.value_json, authority=excluded.authority,
                  source=excluded.source, evidence_ref=excluded.evidence_ref,
                  committed_at=excluded.committed_at, expires_at=excluded.expires_at,
                  superseded_at=NULL""",
                (
                    case_id, proposal.name, json.dumps(proposal.value), proposal.authority.value,
                    proposal.source, proposal.evidence_ref, _now(), proposal.expires_at,
                ),
            )
            await db.commit()
        record = await self.get_case(case_id)
        assert record is not None
        return record

    async def get_fact(self, case_id: str, name: str) -> FactRecord | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM case_facts WHERE case_id=? AND name=? AND superseded_at IS NULL",
                (case_id, name),
            )).fetchone()
            if not row:
                return None
            data = dict(row)
            data["value"] = json.loads(data.pop("value_json"))
            return FactRecord(**data)

    async def insert_action(self, record: ActionRecord, expected_version: int) -> ActionRecord:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "UPDATE workflow_cases SET version=version+1 WHERE case_id=? AND version=?",
                (record.command.case_id, expected_version),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                raise CaseConflict(f"Case {record.command.case_id} version conflict")
            await db.execute(
                "INSERT INTO action_attempts VALUES (?,?,?,?,?,?,?,?)",
                (
                    record.action_id, record.command.idempotency_key, record.command.case_id,
                    record.command.model_dump_json(), record.status.value, None,
                    record.created_at, record.updated_at,
                ),
            )
            for status in (ActionStatus.REQUESTED, ActionStatus.AUTHORIZED):
                await db.execute(
                    "INSERT INTO action_events VALUES (?,?,?,?,?)",
                    (
                        f"AEV-{uuid.uuid4().hex}", record.action_id, status.value,
                        None, _now(),
                    ),
                )
            now = _now()
            await db.execute(
                "INSERT INTO core_outbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"OUT-{uuid.uuid4().hex}", "action.dispatch", record.action_id,
                    json.dumps({"action_id": record.action_id}), OutboxStatus.PENDING.value,
                    0, now, None, None, None, now, now,
                ),
            )
            await db.commit()
        return record

    async def get_action_by_key(self, key: str) -> ActionRecord | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM action_attempts WHERE idempotency_key=?", (key,)
            )).fetchone()
            return self._action_from_row(dict(row)) if row else None

    async def get_action(self, action_id: str) -> ActionRecord | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM action_attempts WHERE action_id=?", (action_id,)
            )).fetchone()
            return self._action_from_row(dict(row)) if row else None

    async def list_actions(
        self, status: ActionStatus | None = None, limit: int = 100
    ) -> list[ActionRecord]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            if status is None:
                cursor = await db.execute(
                    "SELECT * FROM action_attempts ORDER BY created_at LIMIT ?", (limit,)
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM action_attempts WHERE status=? ORDER BY created_at LIMIT ?",
                    (status.value, limit),
                )
            return [self._action_from_row(dict(row)) for row in await cursor.fetchall()]

    async def list_action_events(self, action_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute(
                """SELECT event_id,action_id,status,details_json,recorded_at
                FROM action_events WHERE action_id=? ORDER BY rowid""",
                (action_id,),
            )).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            details_json = event.pop("details_json")
            event["details"] = json.loads(details_json) if details_json else None
            events.append(event)
        return events

    async def update_action(self, action_id: str, status: ActionStatus, outcome: dict | None) -> ActionRecord:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "UPDATE action_attempts SET status=?, outcome_json=?, updated_at=? WHERE action_id=?",
                (status.value, json.dumps(outcome) if outcome is not None else None, _now(), action_id),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                raise KeyError(action_id)
            await db.execute(
                "INSERT INTO action_events VALUES (?,?,?,?,?)",
                (
                    f"AEV-{uuid.uuid4().hex}", action_id, status.value,
                    json.dumps(outcome) if outcome is not None else None, _now(),
                ),
            )
            await db.commit()
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM action_attempts WHERE action_id=?", (action_id,))).fetchone()
            if not row:
                raise KeyError(action_id)
            return self._action_from_row(dict(row))

    async def transition_action(
        self,
        action_id: str,
        expected: ActionStatus,
        status: ActionStatus,
        outcome: dict | None,
    ) -> ActionRecord:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """UPDATE action_attempts SET status=?, outcome_json=?, updated_at=?
                WHERE action_id=? AND status=?""",
                (
                    status.value,
                    json.dumps(outcome) if outcome is not None else None,
                    _now(),
                    action_id,
                    expected.value,
                ),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                raise ActionConflict(
                    f"Action {action_id} transition conflict from {expected.value}"
                )
            await db.execute(
                "INSERT INTO action_events VALUES (?,?,?,?,?)",
                (
                    f"AEV-{uuid.uuid4().hex}", action_id, status.value,
                    json.dumps(outcome) if outcome is not None else None, _now(),
                ),
            )
            await db.commit()
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM action_attempts WHERE action_id=?", (action_id,)
            )).fetchone()
            assert row is not None
            return self._action_from_row(dict(row))

    async def claim_action(self, action_id: str) -> tuple[ActionRecord, bool]:
        """Atomically move one authorized action to dispatched."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """UPDATE action_attempts SET status=?, updated_at=?
                WHERE action_id=? AND status=?""",
                (ActionStatus.DISPATCHED.value, _now(), action_id, ActionStatus.AUTHORIZED.value),
            )
            claimed = cursor.rowcount == 1
            if claimed:
                await db.execute(
                    "INSERT INTO action_events VALUES (?,?,?,?,?)",
                    (
                        f"AEV-{uuid.uuid4().hex}", action_id,
                        ActionStatus.DISPATCHED.value, None, _now(),
                    ),
                )
            await db.commit()
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM action_attempts WHERE action_id=?", (action_id,)
            )).fetchone()
            if not row:
                raise KeyError(action_id)
            return self._action_from_row(dict(row)), claimed

    @staticmethod
    def _action_from_row(row: dict[str, Any]) -> ActionRecord:
        return ActionRecord(
            action_id=row["action_id"], command=ActionCommand.model_validate_json(row["command_json"]),
            status=ActionStatus(row["status"]),
            outcome=json.loads(row["outcome_json"]) if row["outcome_json"] else None,
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    async def create_action_proposal(self, record: ActionProposal) -> ActionProposal:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO action_proposals
                (proposal_id,action,payload_json,case_id,customer_id,actor_id,
                 procedure_id,procedure_version,policy_package_id,idempotency_key,
                 resource_type,resource_id,resource_version,conversation_id,message_id,
                 connector_binding_id,connector_binding_version,contract_version,
                 preview_json,status,confirmation_evidence_ref,action_id,created_at,
                 expires_at,updated_at,confirmed_at,cancelled_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.proposal_id,
                    record.action,
                    json.dumps(record.payload),
                    record.case_id,
                    record.customer_id,
                    record.actor_id,
                    record.procedure_id,
                    record.procedure_version,
                    record.policy_package_id,
                    record.idempotency_key,
                    record.resource_type,
                    record.resource_id,
                    record.resource_version,
                    record.conversation_id,
                    record.message_id,
                    record.connector_binding_id,
                    record.connector_binding_version,
                    record.contract_version,
                    json.dumps(record.preview),
                    record.status.value,
                    record.confirmation_evidence_ref,
                    record.action_id,
                    record.created_at,
                    record.expires_at,
                    record.updated_at,
                    record.confirmed_at,
                    record.cancelled_at,
                ),
            )
            await db.commit()
        return record

    async def get_action_proposal(self, proposal_id: str) -> ActionProposal | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM action_proposals WHERE proposal_id=?", (proposal_id,)
            )).fetchone()
        return self._proposal_from_row(dict(row)) if row else None

    async def list_action_proposals(
        self,
        *,
        customer_id: str | None = None,
        conversation_id: str | None = None,
        status: ActionProposalStatus | None = None,
        limit: int = 100,
    ) -> list[ActionProposal]:
        clauses: list[str] = []
        params: list[Any] = []
        if customer_id is not None:
            clauses.append("customer_id=?")
            params.append(customer_id)
        if conversation_id is not None:
            clauses.append("conversation_id=?")
            params.append(conversation_id)
        if status is not None:
            clauses.append("status=?")
            params.append(status.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute(
                f"SELECT * FROM action_proposals {where} ORDER BY created_at DESC LIMIT ?",
                params,
            )).fetchall()
        return [self._proposal_from_row(dict(row)) for row in rows]

    async def transition_action_proposal(
        self,
        proposal_id: str,
        expected: ActionProposalStatus,
        status: ActionProposalStatus,
        *,
        confirmation_evidence_ref: str | None = None,
        action_id: str | None = None,
    ) -> ActionProposal:
        now = _now()
        confirmed_at = now if status is ActionProposalStatus.CONFIRMED else None
        cancelled_at = now if status is ActionProposalStatus.CANCELLED else None
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """UPDATE action_proposals
                SET status=?, confirmation_evidence_ref=COALESCE(?, confirmation_evidence_ref),
                    action_id=COALESCE(?, action_id), updated_at=?,
                    confirmed_at=COALESCE(?, confirmed_at),
                    cancelled_at=COALESCE(?, cancelled_at)
                WHERE proposal_id=? AND status=?""",
                (
                    status.value,
                    confirmation_evidence_ref,
                    action_id,
                    now,
                    confirmed_at,
                    cancelled_at,
                    proposal_id,
                    expected.value,
                ),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                raise ActionConflict(
                    f"Action proposal {proposal_id} transition conflict from {expected.value}"
                )
            await db.commit()
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM action_proposals WHERE proposal_id=?", (proposal_id,)
            )).fetchone()
        assert row is not None
        return self._proposal_from_row(dict(row))

    @staticmethod
    def _proposal_from_row(row: dict[str, Any]) -> ActionProposal:
        return ActionProposal(
            proposal_id=row["proposal_id"],
            action=row["action"],
            payload=json.loads(row["payload_json"]),
            case_id=row["case_id"],
            customer_id=row["customer_id"],
            actor_id=row["actor_id"],
            procedure_id=row["procedure_id"],
            procedure_version=row["procedure_version"],
            policy_package_id=row["policy_package_id"],
            idempotency_key=row["idempotency_key"],
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            resource_version=row["resource_version"],
            conversation_id=row["conversation_id"],
            message_id=row["message_id"],
            connector_binding_id=row["connector_binding_id"],
            connector_binding_version=row["connector_binding_version"],
            contract_version=row["contract_version"],
            preview=json.loads(row["preview_json"]),
            status=ActionProposalStatus(row["status"]),
            confirmation_evidence_ref=row["confirmation_evidence_ref"],
            action_id=row["action_id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            updated_at=row["updated_at"],
            confirmed_at=row["confirmed_at"],
            cancelled_at=row["cancelled_at"],
        )

    async def accept_message(self, envelope: dict[str, Any]) -> bool:
        return bool((await self.accept_message_result(envelope))["accepted"])

    async def accept_message_result(self, envelope: dict[str, Any]) -> dict[str, Any]:
        provider_id = envelope.get("provider_id", "local")
        message_id = envelope["message_id"]
        conversation_id = envelope.get("conversation_id", "")
        sequence = envelope.get("sequence")
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            existing = await (await db.execute(
                """SELECT ordering_status,sequence FROM conversation_inbox_v3
                WHERE provider_id=? AND message_id=?""",
                (provider_id, message_id),
            )).fetchone()
            if existing and existing[0] != "quarantined":
                await db.rollback()
                return {"accepted": False, "status": "duplicate", "reason": "message_id"}

            ordering_status = "accepted"
            reason = None
            if sequence is not None:
                row = await (await db.execute(
                    """SELECT last_sequence FROM conversation_sequences
                    WHERE provider_id=? AND conversation_id=?""",
                    (provider_id, conversation_id),
                )).fetchone()
                last_sequence = row[0] if row else None
                if last_sequence is not None and sequence <= last_sequence:
                    await db.rollback()
                    return {
                        "accepted": False,
                        "status": "duplicate",
                        "reason": "sequence_already_processed",
                    }
                if last_sequence is not None and sequence > last_sequence + 1:
                    ordering_status = "quarantined"
                    reason = f"sequence_gap:expected={last_sequence + 1}:received={sequence}"

            if existing:
                await db.execute(
                    """UPDATE conversation_inbox_v3 SET envelope_json=?,ordering_status=?,
                    received_at=? WHERE provider_id=? AND message_id=?""",
                    (
                        json.dumps(envelope), ordering_status, _now(), provider_id, message_id,
                    ),
                )
            else:
                await db.execute(
                    "INSERT INTO conversation_inbox_v3 VALUES (?,?,?,?,?,?,?)",
                    (
                        provider_id, message_id, conversation_id, sequence,
                        json.dumps(envelope), ordering_status, _now(),
                    ),
                )
            if ordering_status == "accepted" and sequence is not None:
                await db.execute(
                    """INSERT INTO conversation_sequences VALUES (?,?,?,?)
                    ON CONFLICT(provider_id,conversation_id) DO UPDATE SET
                    last_sequence=excluded.last_sequence,updated_at=excluded.updated_at""",
                    (provider_id, conversation_id, sequence, _now()),
                )
            await db.commit()
            return {
                "accepted": ordering_status == "accepted",
                "status": ordering_status,
                "reason": reason,
            }

    async def list_quarantined_messages(self, limit: int = 100) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute(
                """SELECT * FROM conversation_inbox_v3 WHERE ordering_status='quarantined'
                ORDER BY received_at LIMIT ?""",
                (limit,),
            )).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["envelope"] = json.loads(data.pop("envelope_json"))
            result.append(data)
        return result

    async def enqueue_outbox(
        self, topic: str, aggregate_id: str, payload: dict[str, Any]
    ) -> OutboxRecord:
        now = _now()
        record = OutboxRecord(
            outbox_id=f"OUT-{uuid.uuid4().hex}", topic=topic, aggregate_id=aggregate_id,
            payload=payload, status=OutboxStatus.PENDING, available_at=now,
            created_at=now, updated_at=now,
        )
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO core_outbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record.outbox_id, record.topic, record.aggregate_id, json.dumps(record.payload),
                    record.status.value, record.attempts, record.available_at, None, None, None,
                    record.created_at, record.updated_at,
                ),
            )
            await db.commit()
        return record

    async def claim_outbox(
        self, owner: str, lease_seconds: int, limit: int = 10
    ) -> list[OutboxRecord]:
        """Lease due records with SQLite-compatible compare-and-set locking."""
        now = _now()
        lease_until = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            rows = await (await db.execute(
                """SELECT outbox_id FROM core_outbox
                WHERE available_at <= ? AND (
                    status IN (?, ?) OR (status=? AND lease_until < ?)
                ) ORDER BY created_at LIMIT ?""",
                (
                    now, OutboxStatus.PENDING.value, OutboxStatus.FAILED.value,
                    OutboxStatus.LEASED.value, now, limit,
                ),
            )).fetchall()
            ids = [row["outbox_id"] for row in rows]
            for outbox_id in ids:
                await db.execute(
                    """UPDATE core_outbox SET status=?, lease_owner=?, lease_until=?,
                    attempts=attempts+1, updated_at=? WHERE outbox_id=?""",
                    (OutboxStatus.LEASED.value, owner, lease_until, now, outbox_id),
                )
            await db.commit()
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            claimed = await (await db.execute(
                f"SELECT * FROM core_outbox WHERE outbox_id IN ({placeholders})", ids
            )).fetchall()
            return [self._outbox_from_row(dict(row)) for row in claimed]

    async def complete_outbox(self, outbox_id: str) -> OutboxRecord:
        return await self._update_outbox(
            outbox_id, OutboxStatus.DELIVERED, retry_at=None, error=None
        )

    async def fail_outbox(
        self,
        outbox_id: str,
        error: str,
        retry_at: str | None,
        quarantine: bool = False,
    ) -> OutboxRecord:
        status = OutboxStatus.QUARANTINED if quarantine else OutboxStatus.FAILED
        return await self._update_outbox(outbox_id, status, retry_at=retry_at, error=error)

    async def _update_outbox(
        self,
        outbox_id: str,
        status: OutboxStatus,
        retry_at: str | None,
        error: str | None,
    ) -> OutboxRecord:
        now = _now()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """UPDATE core_outbox SET status=?, available_at=?, lease_owner=NULL,
                lease_until=NULL, last_error=?, updated_at=? WHERE outbox_id=?""",
                (status.value, retry_at or now, error, now, outbox_id),
            )
            await db.commit()
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM core_outbox WHERE outbox_id=?", (outbox_id,)
            )).fetchone()
        if not row:
            raise KeyError(outbox_id)
        return self._outbox_from_row(dict(row))

    async def list_outbox(
        self, status: OutboxStatus | None = None, limit: int = 100
    ) -> list[OutboxRecord]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            if status is None:
                cursor = await db.execute(
                    "SELECT * FROM core_outbox ORDER BY created_at LIMIT ?", (limit,)
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM core_outbox WHERE status=? ORDER BY created_at LIMIT ?",
                    (status.value, limit),
                )
            return [self._outbox_from_row(dict(row)) for row in await cursor.fetchall()]

    @staticmethod
    def _outbox_from_row(row: dict[str, Any]) -> OutboxRecord:
        data = dict(row)
        data["payload"] = json.loads(data.pop("payload_json"))
        return OutboxRecord(**data)

    async def create_handoff(self, record: dict[str, Any]) -> None:
        async with aiosqlite.connect(self.path) as db:
            case = await (await db.execute(
                "SELECT 1 FROM workflow_cases WHERE case_id=?", (record["case_id"],)
            )).fetchone()
            if case is None:
                raise KeyError(record["case_id"])
            await db.execute(
                "INSERT INTO handoffs VALUES (?,?,?,?,?,?,?,?)",
                (
                    record["handoff_id"], record["conversation_id"], record["case_id"],
                    json.dumps(record["context"]), record["status"], None,
                    record["created_at"], record["updated_at"],
                ),
            )
            await db.commit()

    async def get_handoff(self, handoff_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM handoffs WHERE handoff_id=?", (handoff_id,))).fetchone()
            if not row:
                return None
            data = dict(row)
            data["context"] = json.loads(data.pop("context_json"))
            return data

    async def update_handoff(self, handoff_id: str, status: str, agent_id: str | None) -> dict[str, Any]:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE handoffs SET status=?, assigned_agent_id=?, updated_at=? WHERE handoff_id=?",
                (status, agent_id, _now(), handoff_id),
            )
            await db.commit()
        result = await self.get_handoff(handoff_id)
        if result is None:
            raise KeyError(handoff_id)
        return result

    async def transition_handoff(
        self,
        handoff_id: str,
        expected: str,
        status: str,
        agent_id: str | None,
    ) -> dict[str, Any]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """UPDATE handoffs SET status=?,assigned_agent_id=?,updated_at=?
                WHERE handoff_id=? AND status=?""",
                (status, agent_id, _now(), handoff_id, expected),
            )
            await db.commit()
            if cursor.rowcount != 1:
                raise HandoffConflict(
                    f"Handoff {handoff_id} transition conflict from {expected}"
                )
        result = await self.get_handoff(handoff_id)
        assert result is not None
        return result


class CaseKernel:
    def __init__(self, store: CoreStore):
        self.store = store

    async def create_case(self, case_id: str, customer_id: str, procedure_id: str, version: str) -> CaseRecord:
        record = CaseRecord(
            case_id=case_id, customer_id=customer_id, procedure_id=procedure_id,
            procedure_version=version, status="active", version=0,
        )
        await self.store.create_case(record)
        return record

    async def commit_fact(self, case_id: str, proposal: FactProposal, expected_version: int) -> CaseRecord:
        return await self.store.append_fact(case_id, proposal, expected_version)

    async def authorize_action(self, command: ActionCommand, expected_version: int) -> ActionRecord:
        duplicate = await self.store.get_action_by_key(command.idempotency_key)
        if duplicate:
            if duplicate.command != command:
                raise ValueError(
                    "Idempotency key is already bound to a different action command"
                )
            return duplicate
        specification = ACTION_SPECIFICATIONS.get(command.action)
        if specification is None:
            raise ValueError(f"Unknown consequential action: {command.action}")
        missing = specification.required_parameters - command.parameters.keys()
        if missing:
            raise ValueError(f"Missing required action parameters: {', '.join(sorted(missing))}")
        if specification.requires_consent and not command.consent_evidence_ref:
            raise ValueError(f"Action {command.action} requires explicit consent evidence")
        if specification.requires_approval and not command.approval_evidence_ref:
            raise ValueError(f"Action {command.action} requires approval evidence")
        unverified = specification.authoritative_parameters - command.parameter_fact_refs.keys()
        if unverified:
            raise ValueError(
                "Authoritative parameters lack fact references: " + ", ".join(sorted(unverified))
            )
        for parameter, fact_name in command.parameter_fact_refs.items():
            fact = await self.store.get_fact(command.case_id, fact_name)
            if fact is None:
                raise ValueError(f"Missing required fact: {fact_name}")
            required = command.required_fact_authority[parameter]
            if _AUTHORITY_RANK[fact.authority] < _AUTHORITY_RANK[required]:
                raise ValueError(f"Fact {fact_name} has insufficient authority")
            if command.parameters.get(parameter) != fact.value:
                raise ValueError(f"Parameter {parameter} does not match authoritative fact")
        now = _now()
        record = ActionRecord(
            action_id=f"ACT-{uuid.uuid4().hex}", command=command,
            status=ActionStatus.AUTHORIZED, created_at=now, updated_at=now,
        )
        return await self.store.insert_action(record, expected_version)

    async def mark_dispatched(self, action_id: str) -> ActionRecord:
        action, _claimed = await self.store.claim_action(action_id)
        return action

    async def record_outcome(self, action_id: str, status: ActionStatus, outcome: dict | None) -> ActionRecord:
        if status not in {ActionStatus.SUCCEEDED, ActionStatus.FAILED, ActionStatus.UNKNOWN, ActionStatus.RECONCILED}:
            raise ValueError("Invalid terminal/reconciliation status")
        current = await self.store.get_action(action_id)
        if current is None:
            raise KeyError(action_id)
        allowed = {
            ActionStatus.DISPATCHED: {
                ActionStatus.SUCCEEDED,
                ActionStatus.FAILED,
                ActionStatus.UNKNOWN,
            },
            ActionStatus.UNKNOWN: {
                ActionStatus.UNKNOWN,
                ActionStatus.FAILED,
                ActionStatus.RECONCILED,
            },
        }
        if status not in allowed.get(current.status, set()):
            raise ValueError(
                f"Invalid action transition: {current.status.value} -> {status.value}"
            )
        return await self.store.transition_action(
            action_id, current.status, status, outcome
        )


StoreFactory = Callable[[str], CoreStore]


def create_core_store(
    database_url: str,
    adapters: dict[str, StoreFactory] | None = None,
) -> CoreStore:
    """Resolve a database adapter without coupling the kernel to a vendor."""
    scheme = database_url.split(":", 1)[0].split("+", 1)[0]
    if scheme == "sqlite":
        path = database_url.split("///", 1)[-1]
        return SQLiteCoreStore(path)
    adapter = (adapters or {}).get(scheme)
    if adapter is None:
        raise ValueError(f"No core store adapter configured for database scheme '{scheme}'")
    return adapter(database_url)
