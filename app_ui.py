"""Shiny for Python chat UI for the LLM Workflow Engine."""

import json

import httpx
import pandas as pd
from shiny import App, reactive, render, ui

from workflow_engine.ui import WorkflowApiClient

api = WorkflowApiClient()
API_BASE = api.base_url

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


def _proposal_list(payload):
    """Normalize proposal responses from chat, list, and single-record endpoints."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("action_proposals", "proposals", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    nested = payload.get("proposal")
    if isinstance(nested, dict):
        return [nested]
    return [payload] if payload.get("proposal_id") else []


def _proposal_state(proposal):
    return str(proposal.get("state") or proposal.get("status") or "pending").lower()


def _proposal_action_id(proposal):
    direct = proposal.get("action_id")
    if direct:
        return str(direct)
    result = proposal.get("result")
    if isinstance(result, dict) and result.get("action_id"):
        return str(result["action_id"])
    return None


def _action_record(payload):
    """Extract an action record from confirmation and status response envelopes."""
    if not isinstance(payload, dict):
        return None
    for key in ("action", "action_record", "receipt"):
        nested = payload.get(key)
        if isinstance(nested, dict) and nested.get("action_id"):
            record = dict(nested)
            for event_key in ("events", "event_history"):
                if event_key in payload and event_key not in record:
                    record[event_key] = payload[event_key]
            return record
    return payload if payload.get("action_id") else None


async def _confirm_and_load_action(client, proposal_id):
    """Run the same confirmation/status sequence used by the Shiny handler."""
    response = await client.confirm_action_proposal(str(proposal_id))
    record = _action_record(response)
    if record and record.get("action_id"):
        authoritative = await client.action_status(str(record["action_id"]))
        record = _action_record(authoritative) or record
    return response, record


def _json_block(value):
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def _action_event_button(input_name, identifier, label, class_name):
    encoded = json.dumps(str(identifier)).replace("</", "<\\/")
    return ui.tags.button(
        label,
        type="button",
        class_=class_name,
        onclick=(
            f"Shiny.setInputValue('{input_name}', {encoded}, "
            "{priority: 'event'})"
        ),
    )


def _action_proposal_card(proposal, action_detail=None, error=None):
    """Render a structured proposal without parsing conversational prose."""
    proposal_id = str(proposal.get("proposal_id") or "unknown")
    action_name = str(proposal.get("action") or "consequential action")
    state = _proposal_state(proposal)
    action_id = _proposal_action_id(proposal)
    if not action_id and isinstance(action_detail, dict):
        action_id = action_detail.get("action_id")
    preview = proposal.get("safe_preview") or proposal.get("preview") or {}
    badge_class = {
        "pending": "text-bg-warning",
        "confirmed": "text-bg-primary",
        "cancelled": "text-bg-secondary",
        "expired": "text-bg-dark",
    }.get(state, "text-bg-info")

    controls = []
    if state == "pending":
        controls.extend(
            [
                _action_event_button(
                    "action_confirm",
                    proposal_id,
                    "Confirm action",
                    "btn btn-success btn-sm me-2",
                ),
                _action_event_button(
                    "action_cancel",
                    proposal_id,
                    "Cancel",
                    "btn btn-outline-secondary btn-sm",
                ),
            ]
        )
    if action_id:
        controls.append(
            _action_event_button(
                "action_refresh",
                action_id,
                "Refresh status",
                "btn btn-outline-primary btn-sm ms-2",
            )
        )

    details = []
    if action_detail:
        status = action_detail.get("status", "unknown")
        details.extend(
            [
                ui.tags.h6(f"Action status: {status}", class_="mt-3"),
                ui.tags.pre(
                    _json_block(
                        {
                            key: value
                            for key, value in action_detail.items()
                            if key in {"action_id", "status", "outcome", "events", "event_history"}
                        }
                    ),
                    class_="small bg-light border rounded p-2 mb-0",
                ),
            ]
        )

    return ui.card(
        ui.card_header(
            ui.tags.span(action_name.replace("_", " ").title()),
            ui.tags.span(state, class_=f"badge {badge_class} float-end"),
        ),
        ui.tags.p(
            "Review the authoritative action preview before confirming. "
            "The assistant cannot confirm this action for you.",
            class_="small text-muted",
        ),
        ui.tags.pre(
            _json_block(preview), class_="small bg-light border rounded p-2"
        ),
        ui.tags.div(
            ui.tags.small(f"Proposal: {proposal_id}", class_="text-muted"),
            ui.tags.br(),
            ui.tags.small(
                f"Expires: {proposal.get('expires_at', 'not supplied')}",
                class_="text-muted",
            ),
            class_="mb-2",
        ),
        ui.tags.div(*controls),
        ui.tags.p(error, class_="text-danger small mt-2 mb-0") if error else None,
        *details,
        class_="mb-3 border-primary",
    )


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
            ui.tags.div(
                ui.tags.strong("Typed action demo"),
                ui.tags.span(
                    " — When the backend runs in demo/sandbox mode, confirmed actions "
                    "use the SQLite provider emulator but still pass through the same "
                    "v3 typed gateway, authorization, policy, evidence, and idempotency "
                    "controls used by production connectors. Chat can propose; only you "
                    "can confirm.",
                ),
                class_="alert alert-info py-2 small",
            ),
            ui.chat_ui("chat"),
            ui.output_ui("action_proposal_cards"),
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
        ui.nav_panel(
            "System Status",
            ui.input_action_button("refresh_status", "Refresh", class_="btn-primary mb-3"),
            ui.output_ui("system_status"),
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
    action_proposals = reactive.value([])
    action_details = reactive.value({})
    action_errors = reactive.value({})

    chat = ui.Chat("chat")

    def _remember_proposals(payload):
        incoming = _proposal_list(payload)
        if not incoming:
            return
        merged = {
            str(item.get("proposal_id")): item
            for item in action_proposals()
            if item.get("proposal_id")
        }
        for item in incoming:
            proposal_id = item.get("proposal_id")
            if proposal_id:
                merged[str(proposal_id)] = item
        action_proposals.set(list(merged.values()))

    def _patch_proposal(proposal_id, **changes):
        updated = []
        for proposal in action_proposals():
            if str(proposal.get("proposal_id")) == str(proposal_id):
                proposal = {**proposal, **changes}
            updated.append(proposal)
        action_proposals.set(updated)

    async def _refresh_action_proposals():
        sid = session_id()
        if sid is None:
            return
        try:
            _remember_proposals(await api.action_proposals(sid))
        except httpx.HTTPError:
            # Chat remains usable against an older backend during rolling upgrades.
            return

    async def _refresh_action(action_id):
        try:
            detail = await api.action_status(action_id)
            record = _action_record(detail) or detail
            current = dict(action_details())
            current[str(action_id)] = record
            action_details.set(current)
        except httpx.HTTPError as exc:
            errors = dict(action_errors())
            errors[str(action_id)] = f"Could not refresh action status: {exc}"
            action_errors.set(errors)

    # --- Customer selector ---

    @render.ui
    async def customer_selector():
        try:
            data = await api.customers()
            choices = {c["customer_id"]: f"{c['name']} ({c['customer_id']})" for c in data["customers"]}
            choices["guest"] = "Guest (no account)"
            return ui.input_select(
                "customer_select",
                "Select customer:",
                choices=choices,
                selected=selected_customer(),
            )
        except httpx.HTTPError:
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
            payload = {
                "message": user_msg,
                "user_id": _get_user_id(),
            }
            sid = session_id()
            if sid is not None:
                payload["session_id"] = sid

            data = await api.chat(payload)
            session_id.set(data["session_id"])
            await chat.append_message({"role": "assistant", "content": data["response"]})
            _remember_proposals(data)
            await _refresh_action_proposals()
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
            data = await api.session_state(sid, _get_user_id())
            workflow_state.set(data.get("state", {}))
        except httpx.HTTPError:
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

    # --- Typed action proposals ---

    @render.ui
    def action_proposal_cards():
        proposals = action_proposals()
        if not proposals:
            return ui.tags.div(
                ui.tags.h5("Action proposals"),
                ui.tags.p(
                    "No pending actions. Ask the assistant to perform a supported "
                    "action; a structured confirmation card will appear here.",
                    class_="text-muted small",
                ),
                class_="mt-3",
            )
        details = action_details()
        errors = action_errors()
        cards = []
        for proposal in proposals:
            action_id = _proposal_action_id(proposal)
            detail = details.get(str(action_id)) if action_id else None
            error = errors.get(str(proposal.get("proposal_id")))
            if not error and action_id:
                error = errors.get(str(action_id))
            cards.append(_action_proposal_card(proposal, detail, error))
        return ui.tags.div(ui.tags.h5("Action proposals"), *cards, class_="mt-3")

    @reactive.effect
    @reactive.event(input.action_confirm)
    async def _confirm_action_proposal():
        proposal_id = input.action_confirm()
        if not proposal_id:
            return
        try:
            response, record = await _confirm_and_load_action(api, str(proposal_id))
            _remember_proposals(response)
            if record:
                details = dict(action_details())
                details[str(record["action_id"])] = record
                action_details.set(details)
                _patch_proposal(
                    proposal_id,
                    status="confirmed",
                    action_id=record["action_id"],
                )
            await _refresh_action_proposals()
            proposal = next(
                (
                    item
                    for item in action_proposals()
                    if str(item.get("proposal_id")) == str(proposal_id)
                ),
                None,
            )
            action_id = _proposal_action_id(proposal or {})
            if action_id:
                await _refresh_action(action_id)
            await chat.append_message(
                {
                    "role": "assistant",
                    "content": (
                        "Action confirmation was submitted through the typed gateway. "
                        "The authoritative status is shown in the action card below."
                    ),
                }
            )
        except httpx.HTTPError as exc:
            errors = dict(action_errors())
            errors[str(proposal_id)] = f"Confirmation failed: {exc}"
            action_errors.set(errors)

    @reactive.effect
    @reactive.event(input.action_cancel)
    async def _cancel_action_proposal():
        proposal_id = input.action_cancel()
        if not proposal_id:
            return
        try:
            response = await api.cancel_action_proposal(str(proposal_id))
            _remember_proposals(response)
            _patch_proposal(proposal_id, status="cancelled")
            await _refresh_action_proposals()
        except httpx.HTTPError as exc:
            errors = dict(action_errors())
            errors[str(proposal_id)] = f"Cancellation failed: {exc}"
            action_errors.set(errors)

    @reactive.effect
    @reactive.event(input.action_refresh)
    async def _refresh_action_status():
        action_id = input.action_refresh()
        if action_id:
            await _refresh_action(str(action_id))

    # --- Session management ---

    # Track known sessions: list of {session_id, label}
    session_list = reactive.value([])

    async def _load_session_history():
        """Fetch session list from backend for the current user."""
        try:
            data = await api.sessions(_get_user_id())
            session_list.set(data.get("sessions", []))
        except httpx.HTTPError:
            session_list.set([])

    @reactive.effect
    @reactive.event(input.new_session)
    async def _new_session():
        session_id.set(None)
        workflow_state.set({})
        action_proposals.set([])
        action_details.set({})
        action_errors.set({})
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
        action_proposals.set([])
        action_details.set({})
        action_errors.set({})
        await chat.clear_messages()
        await chat.append_message({
            "role": "assistant",
            "content": f"Restored session `{sid[:12]}...`. Send a message to continue the conversation.",
        })
        await _refresh_workflow_state()
        await _refresh_action_proposals()

    # --- Test scenario handlers ---

    async def _run_scenario(scenario):
        """Set customer, start new session, and send the scenario message."""
        cid = scenario["customer_id"] or "guest"
        selected_customer.set(cid)
        # Start fresh session
        session_id.set(None)
        workflow_state.set({})
        action_proposals.set([])
        action_details.set({})
        action_errors.set({})
        await chat.clear_messages()
        # Send the scenario message
        await chat.append_message({"role": "assistant", "content": f"**Test scenario:** {scenario['label']}\n\n*{scenario['description']}*\n\nCustomer: {cid}"})
        await chat.append_message({"role": "user", "content": scenario["message"]})
        # Trigger the API call
        try:
            payload = {
                "message": scenario["message"],
                "user_id": cid,
            }
            data = await api.chat(payload)
            session_id.set(data["session_id"])
            await chat.append_message({"role": "assistant", "content": data["response"]})
            _remember_proposals(data)
            await _refresh_action_proposals()
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
            data = await api.procedures()
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
        except httpx.HTTPError:
            return ui.p("Could not load procedures", class_="text-muted")

    # --- Data browser ---

    @reactive.effect
    @reactive.event(input.load_table)
    async def _load_table():
        table_name = input.table_select()
        try:
            data = await api.table(table_name)
            table_rows.set(data["rows"])
        except httpx.HTTPError:
            table_rows.set([])

    @render.data_frame
    def table_data():
        rows = table_rows()
        if not rows:
            return pd.DataFrame({"message": ["No data. Click Load to fetch a table."]})
        return pd.DataFrame(rows)

    @render.ui
    @reactive.event(input.refresh_status)
    async def system_status():
        try:
            health = await api.health()
            metrics = await api.metrics()
            audit = await api.audit_integrity()
            return ui.tags.div(
                ui.tags.h5("Runtime"), ui.tags.pre(str(health)),
                ui.tags.h5("Core metrics"), ui.tags.pre(str(metrics)),
                ui.tags.h5("Audit integrity"), ui.tags.pre(str(audit)),
            )
        except httpx.HTTPStatusError as exc:
            return ui.p(f"Status request failed: {exc.response.status_code}", class_="text-danger")
        except httpx.ConnectError:
            return ui.p(f"Cannot connect to {API_BASE}", class_="text-danger")


app = App(app_ui, server)
