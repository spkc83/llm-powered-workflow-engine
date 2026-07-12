"""Tests for the FastAPI backend endpoints.

Uses httpx AsyncClient with the FastAPI app directly (no live server required).
ADK runner calls are mocked so these tests run without a Gemini API key.
"""
import uuid

import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# App import — patch ADK runner before main.py initialises it
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    """Import and return the FastAPI app, patching ADK heavy imports."""
    # Patch Runner so it doesn't connect to Gemini at import time
    with patch("google.adk.runners.Runner.__init__", return_value=None):
        import main as m
        return m.app


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_health_returns_ok_status(self, client):
        resp = await client.get("/health")
        data = resp.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_includes_procedures_loaded(self, client):
        resp = await client.get("/health")
        data = resp.json()
        assert "procedures_loaded" in data
        assert isinstance(data["procedures_loaded"], int)
        assert data["procedures_loaded"] >= 3


# ---------------------------------------------------------------------------
# /api/procedures
# ---------------------------------------------------------------------------

class TestProceduresEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200(self, client):
        resp = await client.get("/api/procedures")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_procedures_list(self, client):
        resp = await client.get("/api/procedures")
        data = resp.json()
        assert "procedures" in data
        assert isinstance(data["procedures"], list)

    @pytest.mark.asyncio
    async def test_returns_all_four_procedures(self, client):
        resp = await client.get("/api/procedures")
        data = resp.json()
        assert len(data["procedures"]) == 4  # 3 original + cs_eft_dispute

    @pytest.mark.asyncio
    async def test_each_procedure_has_required_fields(self, client):
        resp = await client.get("/api/procedures")
        data = resp.json()
        for proc in data["procedures"]:
            assert "id" in proc
            assert "name" in proc
            assert "description" in proc
            assert "trigger_intents" in proc

    @pytest.mark.asyncio
    async def test_includes_cs_refund_procedure(self, client):
        resp = await client.get("/api/procedures")
        data = resp.json()
        ids = [p["id"] for p in data["procedures"]]
        assert "cs_refund" in ids

    @pytest.mark.asyncio
    async def test_includes_fraud_triage_procedure(self, client):
        resp = await client.get("/api/procedures")
        data = resp.json()
        ids = [p["id"] for p in data["procedures"]]
        assert "fraud_alert_triage" in ids

    @pytest.mark.asyncio
    async def test_trigger_intents_is_list(self, client):
        resp = await client.get("/api/procedures")
        data = resp.json()
        for proc in data["procedures"]:
            assert isinstance(proc["trigger_intents"], list)


# ---------------------------------------------------------------------------
# /api/session/{session_id}/state
# ---------------------------------------------------------------------------

class TestSessionStateEndpoint:
    @pytest.mark.asyncio
    async def test_unknown_session_returns_404(self, client):
        resp = await client.get(
            "/api/session/nonexistent-session-id/state",
            params={"user_id": "user-1"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_404_detail_mentions_session(self, client):
        resp = await client.get(
            "/api/session/no-such-session/state",
            params={"user_id": "user-1"},
        )
        data = resp.json()
        # Structured error format: {"error": {"code": ..., "message": ...}}
        assert "error" in data
        assert "NOT_FOUND" in data["error"]["code"]

    @pytest.mark.asyncio
    async def test_existing_session_returns_200(self, client):
        import main as m
        sid = f"test-session-{uuid.uuid4().hex[:8]}"
        await m.session_service.create_session(
            app_name="workflow_engine",
            user_id="actor:dev-user:customer:test-user",
            session_id=sid,
        )
        resp = await client.get(
            f"/api/session/{sid}/state",
            params={"user_id": "test-user"},
        )
        assert resp.status_code == 200

# ---------------------------------------------------------------------------
# /api/customers
# ---------------------------------------------------------------------------

class TestCustomersEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200(self, client):
        resp = await client.get("/api/customers")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_customers_list(self, client):
        resp = await client.get("/api/customers")
        data = resp.json()
        assert "customers" in data
        assert isinstance(data["customers"], list)

    @pytest.mark.asyncio
    async def test_returns_at_least_four_customers(self, client):
        resp = await client.get("/api/customers")
        data = resp.json()
        assert len(data["customers"]) >= 4

    @pytest.mark.asyncio
    async def test_each_customer_has_required_fields(self, client):
        resp = await client.get("/api/customers")
        data = resp.json()
        for cust in data["customers"]:
            assert "customer_id" in cust
            assert "name" in cust

    @pytest.mark.asyncio
    async def test_only_returns_id_and_name(self, client):
        resp = await client.get("/api/customers")
        data = resp.json()
        for cust in data["customers"]:
            assert set(cust.keys()) == {"customer_id", "name"}


# ---------------------------------------------------------------------------
# /api/session/{session_id}/state (continued)
# ---------------------------------------------------------------------------

class TestSessionStateEndpointShape:
    @pytest.mark.asyncio
    async def test_session_state_response_has_correct_shape(self, client):
        import main as m
        sid = f"test-session-{uuid.uuid4().hex[:8]}"
        await m.session_service.create_session(
            app_name="workflow_engine",
            user_id="actor:dev-user:customer:test-user-2",
            session_id=sid,
        )
        resp = await client.get(
            f"/api/session/{sid}/state",
            params={"user_id": "test-user-2"},
        )
        data = resp.json()
        assert "session_id" in data
        assert "state" in data
        assert data["session_id"] == sid
        assert isinstance(data["state"], dict)


class TestCoreRefundEndpoint:
    @pytest.mark.asyncio
    async def test_refund_uses_authoritative_gateway_and_is_idempotent(self, client):
        payload = {
            "customer_id": "CUST-456",
            "order_id": "ORD-123",
            "reason": "customer confirmed damaged item",
            "consent_evidence_ref": "chat-message:consent-1",
        }
        first = await client.post("/api/v1/core/refunds", json=payload)
        second = await client.post("/api/v1/core/refunds", json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["action_id"] == second.json()["action_id"]
        assert first.json()["status"] == "succeeded"

    @pytest.mark.asyncio
    async def test_refund_hides_orders_owned_by_another_customer(self, client):
        response = await client.post(
            "/api/v1/core/refunds",
            json={
                "customer_id": "CUST-789",
                "order_id": "ORD-123",
                "reason": "attempted cross-customer refund",
                "consent_evidence_ref": "chat-message:consent-2",
            },
        )
        assert response.status_code == 404


class TestIvrEndpoint:
    @pytest.mark.asyncio
    async def test_low_confidence_turn_requires_readback_and_dedupes(self, client):
        payload = {
            "message_id": f"ivr-{uuid.uuid4().hex}",
            "conversation_id": "CALL-1",
            "customer_id": "CUST-456",
            "transcript": "refund order one two three",
            "asr_confidence": 0.62,
            "interrupted": False,
        }
        first = await client.post("/api/v1/ivr/turns", json=payload)
        duplicate = await client.post("/api/v1/ivr/turns", json=payload)

        assert first.status_code == 200
        assert first.json() == {
            "accepted": True,
            "requires_readback": True,
            "proposed_authority": "asserted",
        }
        assert duplicate.json()["accepted"] is False
