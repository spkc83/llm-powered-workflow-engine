"""Durable, database-portable case/fact/action kernel.

SQLite is the built-in adapter. Other databases implement ``CoreStore`` without
changing policy, conversation, or action semantics.
"""

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol

import aiosqlite
from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CaseConflict(RuntimeError):
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


class ActionRecord(BaseModel):
    action_id: str
    command: ActionCommand
    status: ActionStatus
    outcome: dict[str, Any] | None = None
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
    async def update_action(self, action_id: str, status: ActionStatus, outcome: dict | None) -> ActionRecord: ...
    async def claim_action(self, action_id: str) -> tuple[ActionRecord, bool]: ...
    async def accept_message(self, envelope: dict[str, Any]) -> bool: ...
    async def create_handoff(self, record: dict[str, Any]) -> None: ...
    async def get_handoff(self, handoff_id: str) -> dict[str, Any] | None: ...
    async def update_handoff(self, handoff_id: str, status: str, agent_id: str | None) -> dict[str, Any]: ...


class SQLiteCoreStore:
    """SQLite adapter with transactional optimistic concurrency and uniqueness."""

    def __init__(self, path: str | Path):
        self.path = str(path)

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                PRAGMA foreign_keys=ON;
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
                CREATE TABLE IF NOT EXISTS inbox_messages (
                    message_id TEXT PRIMARY KEY, envelope_json TEXT NOT NULL, received_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS handoffs (
                    handoff_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, case_id TEXT NOT NULL,
                    context_json TEXT NOT NULL, status TEXT NOT NULL, assigned_agent_id TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                """
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
            await db.commit()
        return record

    async def get_action_by_key(self, key: str) -> ActionRecord | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM action_attempts WHERE idempotency_key=?", (key,)
            )).fetchone()
            return self._action_from_row(dict(row)) if row else None

    async def update_action(self, action_id: str, status: ActionStatus, outcome: dict | None) -> ActionRecord:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE action_attempts SET status=?, outcome_json=?, updated_at=? WHERE action_id=?",
                (status.value, json.dumps(outcome) if outcome is not None else None, _now(), action_id),
            )
            await db.commit()
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM action_attempts WHERE action_id=?", (action_id,))).fetchone()
            if not row:
                raise KeyError(action_id)
            return self._action_from_row(dict(row))

    async def claim_action(self, action_id: str) -> tuple[ActionRecord, bool]:
        """Atomically move one authorized action to dispatched."""
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """UPDATE action_attempts SET status=?, updated_at=?
                WHERE action_id=? AND status=?""",
                (ActionStatus.DISPATCHED.value, _now(), action_id, ActionStatus.AUTHORIZED.value),
            )
            await db.commit()
            claimed = cursor.rowcount == 1
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

    async def accept_message(self, envelope: dict[str, Any]) -> bool:
        async with aiosqlite.connect(self.path) as db:
            try:
                await db.execute(
                    "INSERT INTO inbox_messages VALUES (?, ?, ?)",
                    (envelope["message_id"], json.dumps(envelope), _now()),
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def create_handoff(self, record: dict[str, Any]) -> None:
        async with aiosqlite.connect(self.path) as db:
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
            return duplicate
        if command.action == "issue_refund" and not command.consent_evidence_ref:
            raise ValueError("Refund action requires explicit consent evidence")
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
        return await self.store.update_action(action_id, ActionStatus.DISPATCHED, None)

    async def record_outcome(self, action_id: str, status: ActionStatus, outcome: dict | None) -> ActionRecord:
        if status not in {ActionStatus.SUCCEEDED, ActionStatus.FAILED, ActionStatus.UNKNOWN, ActionStatus.RECONCILED}:
            raise ValueError("Invalid terminal/reconciliation status")
        return await self.store.update_action(action_id, status, outcome)


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
