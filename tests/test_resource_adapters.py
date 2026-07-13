import pytest

from workflow_engine.database.db import init_db
from workflow_engine.database.seed import seed_all
from workflow_engine.integrations.resources import ReferenceDataResourceProvider


@pytest.mark.asyncio
async def test_reference_order_is_exposed_as_versioned_authoritative_resource(
    tmp_path, monkeypatch
) -> None:
    import workflow_engine.database.db as db_module
    import workflow_engine.database.seed as seed_module

    path = tmp_path / "reference.db"
    monkeypatch.setattr(db_module, "DB_PATH", path)
    monkeypatch.setattr(seed_module, "DB_PATH", path)
    await init_db()
    await seed_all()

    provider = ReferenceDataResourceProvider()
    first = await provider.get_resource("order", "ORD-123")
    second = await provider.get_resource("order", "ORD-123")

    assert first is not None
    assert first["payload"]["refund_amount"] == 79.99
    assert first["payload"]["customer_id"] == "CUST-456"
    assert first["version"] == second["version"]


@pytest.mark.asyncio
async def test_reference_adapter_rejects_unknown_resource_type() -> None:
    assert (
        await ReferenceDataResourceProvider().get_resource("arbitrary_table", "x")
        is None
    )
