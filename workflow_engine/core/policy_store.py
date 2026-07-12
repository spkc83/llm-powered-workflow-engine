"""Durable policy repository and simple separated author/approver workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List as TypingList, Protocol

import aiosqlite

from workflow_engine.core.policy import (
    PolicyLifecycle,
    PolicyPackage,
    PolicyRegistry,
    PolicySigner,
)


class PolicyRepository(Protocol):
    async def initialize(self) -> None: ...
    async def save(self, package: PolicyPackage) -> None: ...
    async def get(self, package_id: str) -> PolicyPackage | None: ...
    async def list(self, lifecycle: PolicyLifecycle | None = None) -> PolicyPackageList: ...
    async def replace_active(self, active: PolicyPackage, retired: TypingList[PolicyPackage]) -> None: ...


PolicyRepositoryFactory = Callable[[str], PolicyRepository]
PolicyPackageList = TypingList[PolicyPackage]


def create_policy_repository(
    database_url: str,
    adapters: dict[str, PolicyRepositoryFactory] | None = None,
) -> PolicyRepository:
    scheme = database_url.split(":", 1)[0].split("+", 1)[0]
    if scheme == "sqlite":
        return SQLitePolicyRepository(database_url.split("///", 1)[-1])
    factory = (adapters or {}).get(scheme)
    if factory is None:
        raise ValueError(
            f"No policy repository adapter configured for database scheme '{scheme}'"
        )
    return factory(database_url)


class SQLitePolicyRepository:
    def __init__(self, path: str | Path):
        self.path = str(path)

    async def initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS policy_packages (
                package_id TEXT PRIMARY KEY, procedure_id TEXT NOT NULL, version TEXT NOT NULL,
                jurisdiction TEXT NOT NULL, lifecycle TEXT NOT NULL, package_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
            )
            await db.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_policy
                ON policy_packages(procedure_id, jurisdiction)
                WHERE lifecycle='active'"""
            )
            await db.commit()

    async def save(self, package: PolicyPackage) -> None:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO policy_packages
                (package_id,procedure_id,version,jurisdiction,lifecycle,package_json,updated_at)
                VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(package_id) DO UPDATE SET
                  lifecycle=excluded.lifecycle, package_json=excluded.package_json,
                  updated_at=CURRENT_TIMESTAMP""",
                (
                    package.package_id,
                    package.procedure_id,
                    package.version,
                    package.jurisdiction,
                    package.lifecycle.value,
                    package.model_dump_json(),
                ),
            )
            await db.commit()

    async def replace_active(
        self, active: PolicyPackage, retired: list[PolicyPackage]
    ) -> None:
        """Atomically retire prior packages and activate one replacement."""
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            for package in retired:
                await db.execute(
                    """UPDATE policy_packages SET lifecycle=?, package_json=?,
                    updated_at=CURRENT_TIMESTAMP WHERE package_id=?""",
                    (
                        PolicyLifecycle.RETIRED.value,
                        package.model_dump_json(),
                        package.package_id,
                    ),
                )
            await db.execute(
                """INSERT INTO policy_packages
                (package_id,procedure_id,version,jurisdiction,lifecycle,package_json,updated_at)
                VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(package_id) DO UPDATE SET lifecycle=excluded.lifecycle,
                  package_json=excluded.package_json, updated_at=CURRENT_TIMESTAMP""",
                (
                    active.package_id,
                    active.procedure_id,
                    active.version,
                    active.jurisdiction,
                    active.lifecycle.value,
                    active.model_dump_json(),
                ),
            )
            await db.commit()

    async def get(self, package_id: str) -> PolicyPackage | None:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute(
                "SELECT package_json FROM policy_packages WHERE package_id=?", (package_id,)
            )).fetchone()
        return PolicyPackage.model_validate_json(row[0]) if row else None

    async def list(
        self, lifecycle: PolicyLifecycle | None = None
    ) -> list[PolicyPackage]:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            if lifecycle is None:
                cursor = await db.execute(
                    "SELECT package_json FROM policy_packages ORDER BY procedure_id,version"
                )
            else:
                cursor = await db.execute(
                    """SELECT package_json FROM policy_packages WHERE lifecycle=?
                    ORDER BY procedure_id,version""",
                    (lifecycle.value,),
                )
            rows = await cursor.fetchall()
        return [PolicyPackage.model_validate_json(row[0]) for row in rows]


class PolicyService:
    def __init__(
        self,
        repository: PolicyRepository,
        signer: PolicySigner,
        registry: PolicyRegistry,
    ):
        self.repository = repository
        self.signer = signer
        self.registry = registry

    async def hydrate(self) -> None:
        for package in await self.repository.list():
            if package.lifecycle in {PolicyLifecycle.ACTIVE, PolicyLifecycle.RETIRED}:
                self.registry.load_history(package)

    async def require_active(self, package_id: str) -> PolicyPackage:
        package = await self._require(package_id)
        if package.lifecycle is not PolicyLifecycle.ACTIVE or not self.signer.verify(package):
            raise ValueError(f"Policy package is not active: {package_id}")
        self.registry.load_history(package)
        return package

    async def require_authorization_snapshot(
        self, package_id: str, activation_signature: str
    ) -> PolicyPackage:
        package = await self._require(package_id)
        if package.lifecycle not in {PolicyLifecycle.ACTIVE, PolicyLifecycle.RETIRED}:
            raise ValueError("Policy package is not executable history")
        if not self.signer.verify(package):
            raise ValueError("Policy history signature is invalid")
        if package.activation_signature != activation_signature:
            raise ValueError("Action policy activation snapshot does not match history")
        self.registry.load_history(package)
        return package

    async def create_draft(self, package: PolicyPackage) -> PolicyPackage:
        if package.lifecycle is not PolicyLifecycle.DRAFT:
            raise ValueError("New policy packages must begin as drafts")
        if await self.repository.get(package.package_id):
            raise ValueError(f"Policy package already exists: {package.package_id}")
        allowed = package.rules.get("allowed_actions", [])
        if not isinstance(allowed, list) or not all(
            isinstance(action, str) for action in allowed
        ):
            raise ValueError("allowed_actions must be a list of action names")
        if allowed:
            from workflow_engine.core.action_specs import ACTION_SPECIFICATIONS

            unknown = set(allowed) - ACTION_SPECIFICATIONS.keys()
            if unknown:
                raise ValueError(
                    "Policy contains unknown actions: " + ", ".join(sorted(unknown))
                )
        await self.repository.save(package)
        return package

    async def approve(self, package_id: str, approver: str) -> PolicyPackage:
        package = await self._require(package_id)
        if package.lifecycle is not PolicyLifecycle.DRAFT:
            raise ValueError("Only draft policies can be approved")
        approved = self.signer.approve(package, approver)
        await self.repository.save(approved)
        return approved

    async def activate(self, package_id: str) -> PolicyPackage:
        package = await self._require(package_id)
        active = self.signer.activate(package)
        prior = [
            existing
            for existing in await self.repository.list(PolicyLifecycle.ACTIVE)
            if existing.procedure_id == active.procedure_id
            and existing.jurisdiction == active.jurisdiction
            and existing.package_id != active.package_id
        ]
        retired = [self.signer.retire(existing) for existing in prior]
        await self.repository.replace_active(active, retired)
        for existing in retired:
            self.registry.retire(existing.package_id)
        self.registry.load(active)
        return active

    async def retire(self, package_id: str) -> PolicyPackage:
        package = await self._require(package_id)
        retired = self.signer.retire(package)
        await self.repository.save(retired)
        self.registry.retire(package_id)
        return retired

    async def _require(self, package_id: str) -> PolicyPackage:
        package = await self.repository.get(package_id)
        if package is None:
            raise KeyError(package_id)
        return package
