"""Shiny for Python chat UI for the LLM Workflow Engine."""

import pandas as pd
import httpx
from shiny import App, reactive, render, ui

API_BASE = "http://localhost:8000"

# --- Test scenario definitions ---

TEST_SCENARIOS = {
    "positive": [
        {
            "label": "Refund eligible order (natural)",
            "customer_id": "CUST-456",
            "message": "I bought some headphones from TechMart about a week ago and I'd like a refund",
            "description": "Natural language — search_orders finds ORD-123",
        },
        {
            "label": "Complaint about product (natural)",
            "customer_id": "CUST-456",
            "message": "I'm unhappy with the quality of the wireless headphones I got from TechMart",
            "description": "Natural language complaint flow",
        },
        {
            "label": "Fraud alert triage",
            "customer_id": None,
            "message": "I need to investigate fraud alert FA-001",
            "description": "High severity alert",
        },
        {
            "label": "EFT dispute — Tier 1 (within 2 days)",
            "customer_id": "CUST-456",
            "message": "I want to dispute an unauthorized charge on my debit card. I noticed a $150 charge from QuickMart Online yesterday that I didn't make.",
            "description": "DISP-001 — Tier 1, $50 max liability, should file + provisional credit",
        },
        {
            "label": "EFT dispute — Tier 2 (within 60 days)",
            "customer_id": "CUST-789",
            "message": "I need to dispute an unauthorized ACH transfer. About two weeks ago I noticed $2500 was withdrawn from my account by MegaCorp Services. I never authorized this.",
            "description": "DISP-002 — Tier 2, $500 max liability, should file + provisional credit",
        },
        {
            "label": "EFT dispute — error (wrong amount)",
            "customer_id": "CUST-345",
            "message": "I was charged the wrong amount on my debit card at FreshMart Grocery. The receipt shows $45.50 but my account was debited $455.00. This happened a couple of days ago.",
            "description": "DISP-004 — Error dispute, Tier 1, should file dispute for billing error",
        },
    ],
    "negative": [
        {
            "label": "Refund outside window (natural)",
            "customer_id": "CUST-345",
            "message": "I want to return a laptop stand I bought from HomeOffice Supplies last month",
            "description": "Natural language — outside 30-day window",
        },
        {
            "label": "Order still processing",
            "customer_id": "CUST-012",
            "message": "I want a refund for order ORD-789",
            "description": "Status: processing, not delivered",
        },
        {
            "label": "Invalid order ID",
            "customer_id": "CUST-456",
            "message": "I want a refund for order ORD-FAKE",
            "description": "Order does not exist",
        },
        {
            "label": "Wrong customer (natural)",
            "customer_id": "CUST-789",
            "message": "I want a refund for some headphones I bought from TechMart for about $80",
            "description": "search_orders returns no results for CUST-789",
        },
        {
            "label": "General question (no procedure)",
            "customer_id": "guest",
            "message": "What is your return policy?",
            "description": "No matching procedure",
        },
        {
            "label": "EFT dispute — Tier 3 (outside 60-day window)",
            "customer_id": "CUST-012",
            "message": "I want to dispute an unauthorized debit card charge from about 3 months ago. Someone used my card at LuxuryGoods Outlet for $500.",
            "description": "DISP-003 — Tier 3, beyond 60 days, should be denied under Reg E",
        },
        {
            "label": "EFT dispute — non-EFT payment method",
            "customer_id": "CUST-456",
            "message": "I want to dispute an unauthorized charge on my credit card. Someone used my Visa credit card to make a $200 purchase at ElectroMart.",
            "description": "Credit card not covered by Reg E — should redirect to Reg Z process",
        },
        {
            "label": "EFT dispute — no matching transaction",
            "customer_id": "CUST-789",
            "message": "I want to dispute a debit card charge of $999 from a store called FakeStore that happened last week.",
            "description": "Transaction doesn't exist — dispute_not_found path",
        },
    ],
    "multi_turn": [
        {
            "label": "Escalation path",
            "customer_id": "CUST-345",
            "message": "I want a refund for order ORD-999",
            "description": "Will be denied → user can request escalation in follow-up",
        },
        {
            "label": "Complaint → resolution",
            "customer_id": "CUST-789",
            "message": "My order ORD-456 hasn't arrived yet and it's been 3 days",
            "description": "Shipped, not delivered → delivery complaint flow",
        },
        {
            "label": "EFT dispute → escalation",
            "customer_id": "CUST-012",
            "message": "I want to dispute an unauthorized charge on my debit card from about 3 months ago. Someone charged $500 at LuxuryGoods Outlet.",
            "description": "Tier 3 deny → follow up with 'I want to speak to a supervisor' to test escalation",
        },
    ],
}


def _scenario_button(scenario, idx, category):
    btn_id = f"scenario_{category}_{idx}"
    return ui.tags.div(
        ui.input_action_button(
            btn_id,
            scenario["label"],
            class_="btn-outline-secondary btn-sm w-100 mb-1",
        ),
        ui.tags.small(scenario["description"], class_="text-muted d-block mb-2"),
    )


def _scenario_section(title, scenarios, category, btn_class=""):
    buttons = [_scenario_button(s, i, category) for i, s in enumerate(scenarios)]
    return ui.tags.div(
        ui.tags.h6(title, class_=f"mt-2 {btn_class}"),
        *buttons,
    )


app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.h4("Customer"),
        ui.output_ui("customer_selector"),
        ui.hr(),
        ui.h4("Session"),
        ui.output_text("session_id_display"),
        ui.input_action_button("new_session", "New Session", class_="btn-outline-primary w-100 mb-2"),
        ui.output_ui("session_history"),
        ui.hr(),
        ui.h4("Workflow State"),
        ui.output_ui("workflow_state_display"),
        ui.hr(),
        ui.h4("Procedures"),
        ui.output_ui("procedure_list"),
        ui.hr(),
        ui.p(ui.tags.small("Backend: ", ui.tags.code(API_BASE))),
        width=300,
    ),
    ui.navset_tab(
        ui.nav_panel(
            "Chat",
            ui.chat_ui("chat"),
        ),
        ui.nav_panel(
            "Test Scenarios",
            ui.layout_columns(
                ui.card(
                    ui.card_header("Positive Scenarios (Happy Path)"),
                    _scenario_section("", TEST_SCENARIOS["positive"], "positive"),
                ),
                ui.card(
                    ui.card_header("Negative Scenarios (Edge Cases)"),
                    _scenario_section("", TEST_SCENARIOS["negative"], "negative"),
                ),
                ui.card(
                    ui.card_header("Multi-Turn Flow Scenarios"),
                    _scenario_section("", TEST_SCENARIOS["multi_turn"], "multi_turn"),
                ),
                col_widths=[4, 4, 4],
            ),
        ),
        ui.nav_panel(
            "Data Browser",
            ui.layout_columns(
                ui.card(
                    ui.card_header("Browse Tables"),
                    ui.input_select(
                        "table_select",
                        "Select table:",
                        choices=[
                            "customers",
                            "orders",
                            "order_items",
                            "accounts",
                            "transactions",
                            "fraud_alerts",
                            "devices",
                            "login_history",
                            "risk_indicators",
                            "cases",
                            "case_notes",
                            "escalations",
                            "refunds",
                            "disputes",
                            "knowledge_articles",
                        ],
                    ),
                    ui.input_action_button("load_table", "Load", class_="btn-primary"),
                ),
                col_widths=[12],
            ),
            ui.output_data_frame("table_data"),
        ),
    ),
    title="LLM Workflow Engine",
    fillable=True,
)


def server(input, output, session):
    # Reactive values
    session_id = reactive.value(None)
    selected_customer = reactive.value("CUST-456")
    table_rows = reactive.value([])
    workflow_state = reactive.value({})

    chat = ui.Chat("chat")

    # --- Customer selector ---

    @render.ui
    async def customer_selector():
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{API_BASE}/api/customers")
                resp.raise_for_status()
                data = resp.json()
                choices = {c["customer_id"]: f"{c['name']} ({c['customer_id']})" for c in data["customers"]}
                choices["guest"] = "Guest (no account)"
                return ui.input_select(
                    "customer_select",
                    "Select customer:",
                    choices=choices,
                    selected=selected_customer(),
                )
        except Exception:
            return ui.p("Could not load customers", class_="text-muted")

    # --- Chat ---

    def _get_user_id():
        """Return the user_id to send to the API based on selected customer."""
        cid = input.customer_select() if hasattr(input, "customer_select") else selected_customer()
        return cid if cid else "guest"

    @chat.on_user_submit
    async def on_user_message():
        user_msg = chat.user_input()
        if not user_msg:
            return

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                payload = {
                    "message": user_msg,
                    "user_id": _get_user_id(),
                }
                sid = session_id()
                if sid is not None:
                    payload["session_id"] = sid

                resp = await client.post(f"{API_BASE}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()

                session_id.set(data["session_id"])
                await chat.append_message({"role": "assistant", "content": data["response"]})

                # Fetch workflow state after each response
                await _refresh_workflow_state()
        except httpx.HTTPStatusError as e:
            await chat.append_message({"role": "assistant", "content": f"Error: {e.response.status_code} — {e.response.text}"})
        except httpx.ConnectError:
            await chat.append_message({"role": "assistant", "content": "Cannot connect to backend. Is the FastAPI server running on port 8000?"})

    async def _refresh_workflow_state():
        sid = session_id()
        if sid is None:
            workflow_state.set({})
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{API_BASE}/api/session/{sid}/state",
                    params={"user_id": _get_user_id()},
                )
                resp.raise_for_status()
                data = resp.json()
                workflow_state.set(data.get("state", {}))
        except Exception:
            workflow_state.set({})

    # --- Workflow state display ---

    @render.ui
    def workflow_state_display():
        state = workflow_state()
        if not state:
            return ui.p("No active workflow", class_="text-muted small")
        items = []
        label_map = {
            "current_procedure_name": "Procedure",
            "current_step": "Current Step",
            "steps_completed": "Steps Completed",
            "workflow_status": "Status",
            "escalation_reason": "Escalation",
        }
        for key, label in label_map.items():
            if key in state and state[key]:
                items.append(
                    ui.tags.div(
                        ui.tags.strong(f"{label}: ", class_="small"),
                        ui.tags.span(str(state[key]), class_="small"),
                    )
                )
        return ui.tags.div(*items) if items else ui.p("No active workflow", class_="text-muted small")

    # --- Session management ---

    # Track known sessions: list of {session_id, label}
    session_list = reactive.value([])

    async def _load_session_history():
        """Fetch session list from backend for the current user."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{API_BASE}/api/sessions",
                    params={"user_id": _get_user_id()},
                )
                resp.raise_for_status()
                data = resp.json()
                session_list.set(data.get("sessions", []))
        except Exception:
            pass

    @reactive.effect
    @reactive.event(input.new_session)
    async def _new_session():
        session_id.set(None)
        workflow_state.set({})
        await chat.clear_messages()
        await chat.append_message({"role": "assistant", "content": "New session started. Type a message to begin."})

    @render.text
    def session_id_display():
        sid = session_id()
        return f"ID: {sid[:12]}..." if sid else "No active session"

    @render.ui
    async def session_history():
        """Render a session history selector."""
        await _load_session_history()
        sessions = session_list()
        if not sessions:
            return ui.tags.small("No previous sessions", class_="text-muted")
        choices = {}
        for s in sessions:
            sid = s["session_id"]
            proc = s.get("procedure", "")
            status = s.get("status", "")
            label = f"{sid[:8]}..."
            if proc:
                label += f" ({proc})"
            if status:
                label += f" [{status}]"
            choices[sid] = label
        return ui.tags.div(
            ui.tags.small("Previous sessions:", class_="text-muted"),
            ui.input_select("session_select", None, choices=choices, width="100%"),
            ui.input_action_button(
                "restore_session", "Restore Session",
                class_="btn-outline-secondary btn-sm w-100 mt-1",
            ),
        )

    @reactive.effect
    @reactive.event(input.restore_session)
    async def _restore_session():
        """Switch to a previously saved session."""
        sid = input.session_select()
        if not sid:
            return
        session_id.set(sid)
        workflow_state.set({})
        await chat.clear_messages()
        await chat.append_message({
            "role": "assistant",
            "content": f"Restored session `{sid[:12]}...`. Send a message to continue the conversation.",
        })
        await _refresh_workflow_state()

    # --- Test scenario handlers ---

    async def _run_scenario(scenario):
        """Set customer, start new session, and send the scenario message."""
        cid = scenario["customer_id"] or "guest"
        selected_customer.set(cid)
        # Start fresh session
        session_id.set(None)
        workflow_state.set({})
        await chat.clear_messages()
        # Send the scenario message
        await chat.append_message({"role": "assistant", "content": f"**Test scenario:** {scenario['label']}\n\n*{scenario['description']}*\n\nCustomer: {cid}"})
        await chat.append_message({"role": "user", "content": scenario["message"]})
        # Trigger the API call
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                payload = {
                    "message": scenario["message"],
                    "user_id": cid,
                }
                resp = await client.post(f"{API_BASE}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                session_id.set(data["session_id"])
                await chat.append_message({"role": "assistant", "content": data["response"]})
                await _refresh_workflow_state()
        except httpx.HTTPStatusError as e:
            await chat.append_message({"role": "assistant", "content": f"Error: {e.response.status_code} — {e.response.text}"})
        except httpx.ConnectError:
            await chat.append_message({"role": "assistant", "content": "Cannot connect to backend. Is the FastAPI server running on port 8000?"})

    # Register scenario button handlers dynamically
    def _make_scenario_handler(scenario, category, idx):
        btn_id = f"scenario_{category}_{idx}"

        @reactive.effect
        @reactive.event(getattr(input, btn_id))
        async def _handler():
            await _run_scenario(scenario)

    for category, scenarios in TEST_SCENARIOS.items():
        for idx, scenario in enumerate(scenarios):
            _make_scenario_handler(scenario, category, idx)

    # --- Procedures list ---

    @render.ui
    async def procedure_list():
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{API_BASE}/api/procedures")
                resp.raise_for_status()
                data = resp.json()
                items = []
                for proc in data["procedures"]:
                    desc = proc["description"]
                    items.append(
                        ui.tags.div(
                            ui.tags.strong(proc["name"]),
                            ui.tags.br(),
                            ui.tags.small(desc[:80] + "..." if len(desc) > 80 else desc),
                            class_="mb-2",
                        )
                    )
                return ui.tags.div(*items) if items else ui.p("No procedures loaded")
        except Exception:
            return ui.p("Could not load procedures", class_="text-muted")

    # --- Data browser ---

    @reactive.effect
    @reactive.event(input.load_table)
    async def _load_table():
        table_name = input.table_select()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{API_BASE}/api/tables/{table_name}")
                resp.raise_for_status()
                data = resp.json()
                table_rows.set(data["rows"])
        except Exception:
            table_rows.set([])

    @render.data_frame
    def table_data():
        rows = table_rows()
        if not rows:
            return pd.DataFrame({"message": ["No data. Click Load to fetch a table."]})
        return pd.DataFrame(rows)


app = App(app_ui, server)
