"""Bounded workers for durable action delivery and ambiguous-outcome reconciliation."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from workflow_engine.core.gateway import ActionGateway
from workflow_engine.core.kernel import ActionStatus, CoreStore


@dataclass(frozen=True)
class WorkerRun:
    claimed: int
    completed: int
    failed: int


class ActionDeliveryWorker:
    def __init__(
        self,
        store: CoreStore,
        gateway: ActionGateway,
        *,
        owner: str | None = None,
        lease_seconds: int = 30,
        max_attempts: int = 5,
    ):
        self.store = store
        self.gateway = gateway
        self.owner = owner or f"action-worker-{uuid.uuid4().hex[:10]}"
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    async def run_once(self, limit: int = 10) -> WorkerRun:
        records = await self.store.claim_outbox(self.owner, self.lease_seconds, limit)
        completed = 0
        failed = 0
        for record in records:
            if record.topic != "action.dispatch":
                await self.store.fail_outbox(
                    record.outbox_id,
                    f"unsupported_topic:{record.topic}",
                    retry_at=None,
                    quarantine=True,
                )
                failed += 1
                continue
            action = await self.store.get_action(record.payload["action_id"])
            if action is None:
                await self.store.fail_outbox(
                    record.outbox_id, "action_not_found", retry_at=None, quarantine=True
                )
                failed += 1
                continue
            try:
                # A direct request may already have dispatched the action. The action
                # claim prevents a second provider call; the outbox is then settled.
                await self.gateway.dispatch(action)
                await self.store.complete_outbox(record.outbox_id)
                completed += 1
            except Exception as exc:
                quarantine = record.attempts >= self.max_attempts
                retry_at = None
                if not quarantine:
                    retry_at = (
                        datetime.now(timezone.utc)
                        + timedelta(seconds=min(300, 2 ** max(0, record.attempts - 1)))
                    ).isoformat()
                await self.store.fail_outbox(
                    record.outbox_id,
                    type(exc).__name__,
                    retry_at=retry_at,
                    quarantine=quarantine,
                )
                failed += 1
        return WorkerRun(claimed=len(records), completed=completed, failed=failed)


class ReconciliationWorker:
    def __init__(
        self,
        store: CoreStore,
        gateway: ActionGateway,
        *,
        dispatch_stale_seconds: int = 30,
    ):
        self.store = store
        self.gateway = gateway
        self.dispatch_stale_seconds = dispatch_stale_seconds

    async def run_once(self, limit: int = 100) -> WorkerRun:
        unknown = await self.store.list_actions(ActionStatus.UNKNOWN, limit)
        dispatched = await self.store.list_actions(ActionStatus.DISPATCHED, limit)
        stale_before = datetime.now(timezone.utc) - timedelta(
            seconds=self.dispatch_stale_seconds
        )
        due_unknown = [
            action
            for action in unknown
            if datetime.fromisoformat(action.updated_at) <= stale_before
        ]
        stale_dispatched = [
            action
            for action in dispatched
            if datetime.fromisoformat(action.updated_at) <= stale_before
        ]
        actions = (due_unknown + stale_dispatched)[:limit]
        completed = 0
        failed = 0
        for action in actions:
            try:
                result = await self.gateway.reconcile(action)
                if result.status in {ActionStatus.RECONCILED, ActionStatus.FAILED}:
                    completed += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
        return WorkerRun(claimed=len(actions), completed=completed, failed=failed)
