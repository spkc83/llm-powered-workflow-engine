import httpx
import pytest

from workflow_engine.ui import WorkflowApiClient


def test_ui_client_reads_runtime_backend_and_token(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "http://backend:8000/")
    monkeypatch.setenv("BACKEND_AUTH_TOKEN", "token")
    client = WorkflowApiClient()
    assert client.base_url == "http://backend:8000"
    assert client.headers == {"Authorization": "Bearer token"}


@pytest.mark.asyncio
async def test_ui_client_uses_canonical_v3_routes(monkeypatch):
    seen = []

    async def fake_request(self, method, url, **kwargs):
        seen.append((method, url, kwargs))
        return httpx.Response(200, json={"ok": True}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = WorkflowApiClient("http://backend:8000")
    await client.customers()
    await client.chat({"message": "hello", "user_id": "guest"})
    await client.actions_catalog()
    await client.propose_action({"action": "issue_refund"})
    await client.action_proposals("conversation")
    await client.action_proposal("proposal")
    await client.confirm_action_proposal("proposal")
    await client.cancel_action_proposal("proposal")
    await client.action_status("action")
    await client.session_state("session", "guest")
    await client.sessions("guest")
    await client.procedures()
    await client.table("customers")

    assert [item[1] for item in seen] == [
        "http://backend:8000/api/v1/customers",
        "http://backend:8000/api/v1/chat",
        "http://backend:8000/api/v1/actions/catalog",
        "http://backend:8000/api/v1/action-proposals",
        "http://backend:8000/api/v1/action-proposals",
        "http://backend:8000/api/v1/action-proposals/proposal",
        "http://backend:8000/api/v1/action-proposals/proposal/confirm",
        "http://backend:8000/api/v1/action-proposals/proposal/cancel",
        "http://backend:8000/api/v1/actions/action",
        "http://backend:8000/api/v1/session/session/state",
        "http://backend:8000/api/v1/sessions",
        "http://backend:8000/api/v1/procedures",
        "http://backend:8000/api/v1/tables/customers",
    ]
    assert seen[3][2]["json"] == {"action": "issue_refund"}
    assert seen[4][2]["params"] == {"conversation_id": "conversation"}


def test_action_proposal_card_requires_host_confirmation_and_shows_events():
    import app_ui

    card = app_ui._action_proposal_card(
        {
            "proposal_id": "PROP-1",
            "action": "issue_refund",
            "state": "pending",
            "safe_preview": {"order_id": "ORD-123", "amount": 79.99},
            "expires_at": "2026-07-13T12:00:00Z",
        },
        {
            "action_id": "ACT-1",
            "status": "unknown",
            "outcome": {"reason": "timeout_after_commit"},
            "events": [{"status": "authorized"}, {"status": "unknown"}],
        },
    )
    markup = str(card)
    assert "Confirm action" in markup
    assert "Cancel" in markup
    assert "assistant cannot confirm" in markup
    assert "ORD-123" in markup
    assert "timeout_after_commit" in markup
    assert "Refresh status" in markup


def test_cancelled_action_proposal_card_has_no_confirmation_controls():
    import app_ui

    markup = str(
        app_ui._action_proposal_card(
            {
                "proposal_id": "PROP-2",
                "action": "flag_account",
                "state": "cancelled",
                "safe_preview": {"account_id": "ACCT-1"},
            }
        )
    )
    assert "cancelled" in markup
    assert "Confirm action" not in markup


def test_action_status_envelope_preserves_event_history():
    import app_ui

    record = app_ui._action_record(
        {
            "action": {"action_id": "ACT-2", "status": "succeeded"},
            "events": [{"status": "authorized"}, {"status": "succeeded"}],
        }
    )
    assert record["action_id"] == "ACT-2"
    assert record["events"][-1]["status"] == "succeeded"


def test_shiny_app_imports_with_operator_console():
    import app_ui

    assert app_ui.app is not None
    assert app_ui.API_BASE


@pytest.mark.asyncio
async def test_shiny_app_renders_over_asgi():
    import app_ui

    transport = httpx.ASGITransport(app=app_ui.app.starlette_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "LLM Workflow Engine" in response.text
    assert "Typed action demo" in response.text
