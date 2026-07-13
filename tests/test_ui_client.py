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
    await client.session_state("session", "guest")
    await client.sessions("guest")
    await client.procedures()
    await client.table("customers")

    assert [item[1] for item in seen] == [
        "http://backend:8000/api/v1/customers",
        "http://backend:8000/api/v1/chat",
        "http://backend:8000/api/v1/session/session/state",
        "http://backend:8000/api/v1/sessions",
        "http://backend:8000/api/v1/procedures",
        "http://backend:8000/api/v1/tables/customers",
    ]


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
