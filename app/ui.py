from __future__ import annotations

import os
from decimal import Decimal
from inspect import signature
from typing import Any, Callable

import streamlit as st
from dotenv import load_dotenv

from agent.client import PendingDraft, TariffReviewClient, live_configuration_status
from agent.fixture_review import FixtureReviewer
from data.repository import PROJECT_ROOT, Repository
from server import tools as local_tools


load_dotenv(PROJECT_ROOT / ".env")
repository = Repository()
LIVE_MODE = "Live Responses API + MCP"
FIXTURE_MODE = "Emergency deterministic fixture preview"
LIVE_CLIENT_STATE_KEY = "_tariff_review_live_client"


def environment_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def money(value: str | Decimal) -> str:
    return f"${Decimal(value):,.2f}"


def display_run_time(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "Not recorded"
    return value.replace("T", " ").replace("Z", " UTC")


def prepare_local_pending(finding: dict[str, Any]) -> dict[str, Any]:
    token = local_tools.approval_store.create_pending(
        {
            "client_id": "northfield-home-goods",
            "sku_id": finding["sku_id"],
            "purpose": "single local correction draft",
        }
    )
    arguments = {
        "client_id": "northfield-home-goods",
        "sku_id": finding["sku_id"],
        "declared_code": finding["declared_code"],
        "proposed_code": finding["proposed_code"],
        "evidence_ids": finding["rulings_cited"],
        "rationale": finding["deciding_rule"],
        "route": "broker",
        "approval_token": token,
    }
    return {"mode": "fixture", "approval_token": token, "arguments": arguments}


def live_client() -> TariffReviewClient:
    """Reuse one client per UI session so validated MCP discovery can be reused."""
    client = st.session_state.get(LIVE_CLIENT_STATE_KEY)
    if not isinstance(client, TariffReviewClient):
        client = TariffReviewClient()
        st.session_state[LIVE_CLIENT_STATE_KEY] = client
    return client


def render_finding(
    finding: dict[str, Any], calculations: dict[str, dict[str, Any]]
) -> None:
    labels = {
        "potential_overpayment": "Potential overpayment",
        "potential_underpayment": "Potential underpayment — escalate",
        "needs_info": "Needs information",
        "confirmed": "Classification confirmed",
    }
    actions = {
        "potential_overpayment": (
            "Broker to validate the evidence and recovery eligibility before "
            "preparing any correction draft."
        ),
        "potential_underpayment": (
            "Escalate the potential underpayment for compliance or legal review."
        ),
        "needs_info": (
            "Request the missing product evidence from the supplier before classifying."
        ),
        "confirmed": "Retain the declared classification; no correction is indicated.",
    }
    st.subheader(f"{finding['sku_id']} · {labels[finding['outcome']]}")
    left, middle, right = st.columns(3)
    left.metric("Declared", finding["declared_code"])
    middle.metric("Proposed", finding["proposed_code"] or "No proposal")
    calculation = calculations.get(finding["sku_id"])
    if calculation:
        difference = Decimal(calculation["potential_base_duty_difference"])
        right.metric(
            "Potential base-duty difference",
            money(abs(difference)),
            "overpayment" if difference > 0 else "underpayment exposure",
        )
    else:
        right.metric("Potential base-duty difference", "—")
    st.write(finding["deciding_rule"])
    if finding["missing_fact"]:
        st.warning(f"Missing decisive fact: {finding['missing_fact']}")
    if finding["outcome"] == "potential_underpayment":
        st.error("Compliance escalation: this is exposure, not a savings opportunity.")
    links = []
    for ruling_id in finding["rulings_cited"]:
        ruling = repository.get_ruling(ruling_id)
        links.append(f"[{ruling_id}]({ruling['source_url']})")
    if links:
        st.markdown("Official CBP evidence: " + " · ".join(links))
    with st.expander("Reasoning and scoped calculation"):
        st.write(f"Route: {finding['route_to']}")
        st.write(f"Recommended action: {actions[finding['outcome']]}")
        st.write(
            "Uncertainty: decisive product evidence is still missing."
            if finding["outcome"] == "needs_info"
            else "Uncertainty: broker verification remains required."
        )
        if calculation:
            st.json(calculation)


def run_review(
    mode: str,
    sku_ids: list[str],
    edit_sku: str | None,
    edited_description: str | None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    overrides: dict[str, str] = {}
    if edit_sku is not None and edited_description is not None:
        original = repository.get_product("northfield-home-goods", edit_sku)["description"]
        if edited_description != original:
            overrides[edit_sku] = edited_description
    if mode == LIVE_MODE:
        client = live_client()
        if "progress_callback" in signature(client.review).parameters:
            return client.review(
                sku_ids, overrides, progress_callback=progress_callback
            )

        # Streamlit can hot-reload this UI while retaining an older imported
        # client module. Keep that in-flight demo process usable until restart.
        if progress_callback is not None:
            progress_callback(
                "Responses API · waiting for remote MCP orchestration and the "
                "structured review result."
            )
        review = client.review(sku_ids, overrides)
        if progress_callback is not None:
            allowed_tools = {
                "get_catalog",
                "get_entries",
                "search_hts",
                "search_rulings",
                "get_ruling",
            }
            call_counts: dict[str, int] = {}
            for call in review.get("mcp_trace", []):
                name = call.get("name")
                if name in allowed_tools and not call.get("error"):
                    call_counts[name] = call_counts.get(name, 0) + 1
            if call_counts:
                summary = ", ".join(
                    f"{name} ×{count}" if count > 1 else name
                    for name, count in call_counts.items()
                )
                progress_callback(f"MCP · actual calls returned: {summary}.")
            progress_callback(
                "Validation · strict structured output, selected-SKU coverage, "
                "and evidence provenance validated."
            )
            for sku_id in review.get("calculations", {}):
                progress_callback(
                    "Application · DutyCalculator.compute_duty_delta · calculated "
                    f"the base-duty difference for {sku_id}."
                )
            progress_callback("Audit record · validated review saved.")
        return review
    if mode == FIXTURE_MODE:
        if progress_callback is not None:
            progress_callback(
                "Fixture fallback · running the local rule-based review without "
                "the Responses API or remote MCP."
            )
        return FixtureReviewer().review(sku_ids, overrides)
    raise ValueError(f"Unsupported execution mode: {mode}")


st.set_page_config(page_title="Harbor & Crane Tariff Audit", layout="wide")
st.html(
    """
    <style>
    .st-key-openai_execution {
        background: linear-gradient(
            135deg,
            rgba(14, 116, 144, 0.10),
            rgba(15, 118, 110, 0.05)
        );
        border-color: rgba(14, 116, 144, 0.32) !important;
        box-shadow: 0 8px 24px rgba(14, 116, 144, 0.08);
    }
    .st-key-products_to_review [data-tag] {
        background-color: rgba(37, 99, 235, 0.72) !important;
        border: 1px solid rgba(96, 165, 250, 0.60) !important;
        color: #ffffff !important;
    }
    .st-key-products_to_review [data-tag] button {
        color: #ffffff !important;
    }
    .st-key-products_to_review button[aria-label="Open"] {
        background-color: rgba(37, 99, 235, 0.72) !important;
        border: 1px solid rgba(96, 165, 250, 0.60) !important;
        border-radius: 0.45rem !important;
        color: #ffffff !important;
        min-height: 2rem;
        min-width: 2rem;
        margin-right: 0.25rem;
    }
    .st-key-products_to_review button[aria-label="Open"]:hover {
        background-color: rgba(37, 99, 235, 0.90) !important;
        border-color: rgba(147, 197, 253, 0.85) !important;
    }
    .st-key-products_to_review button[aria-label="Open"] svg {
        color: #ffffff !important;
        fill: #ffffff !important;
    }
    .st-key-run_tariff_review button[kind="primary"] {
        background-color: rgba(37, 99, 235, 0.72) !important;
        border-color: rgba(96, 165, 250, 0.60) !important;
        color: #ffffff !important;
    }
    .st-key-run_tariff_review button[kind="primary"]:hover {
        background-color: rgba(37, 99, 235, 0.90) !important;
        border-color: rgba(147, 197, 253, 0.85) !important;
        color: #ffffff !important;
    }
    [data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"],
    [data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"] p {
        color: #60a5fa !important;
    }
    [data-testid="stTabs"] .react-aria-SelectionIndicator {
        background-color: #3b82f6 !important;
        border-color: #3b82f6 !important;
    }
    </style>
    """
)
st.title("Harbor & Crane · Premium Tariff Audit")
st.caption(
    "Northfield Home Goods · evidence-backed screening · Column 1 General base duty only"
)

is_live, live_message = live_configuration_status()
fixture_preview_enabled = environment_flag("ENABLE_FIXTURE_PREVIEW")
mode = LIVE_MODE

if fixture_preview_enabled:
    presenter_modes = ([LIVE_MODE] if is_live else []) + [FIXTURE_MODE]
    with st.expander("Presenter-only emergency fallback", expanded=not is_live):
        st.caption(
            "Hidden in the normal reviewer experience. Use only when the live API "
            "or MCP connection is unavailable, and identify it as a local fixture."
        )
        mode = st.radio("Execution source", presenter_modes, horizontal=True)

if mode == FIXTURE_MODE:
    st.warning(
        "Emergency fixture preview: this run uses local deterministic rules, not "
        "the OpenAI Responses API or remote MCP. Do not present its timing or "
        "correctness as model performance."
    )
elif is_live:
    st.success("Live workflow ready · OpenAI Responses API · remote MCP")
else:
    st.error(
        f"Live review unavailable: {live_message}. Configure the API and MCP "
        "connection before presenting this application."
    )

review_available = is_live or mode == FIXTURE_MODE


def render_review_results(review: dict[str, Any]) -> None:
    proposal = review["proposal"]
    with st.container(border=True):
        st.header("Tariff review results")
        over, under, status = st.columns(3)
        over.metric(
            "Potential overpayment", money(review["potential_overpayment_total"])
        )
        under.metric(
            "Underpayment exposure", money(review["potential_underpayment_total"])
        )
        status.metric("Review status", proposal["status"].title())
        st.caption(
            "Potential differences are not guaranteed refunds. Chapter 99 duties, "
            "trade remedies, preferences, origin, deadlines, and recovery eligibility "
            "are excluded."
        )

        ordered_outcomes = [
            "potential_overpayment",
            "potential_underpayment",
            "needs_info",
            "confirmed",
        ]
        findings = sorted(
            proposal["findings"],
            key=lambda item: ordered_outcomes.index(item["outcome"]),
        )
        for index, finding in enumerate(findings):
            render_finding(finding, review["calculations"])
            if finding["outcome"] == "potential_overpayment":
                if st.button(
                    f"Prepare correction draft for {finding['sku_id']}",
                    key=f"prepare-{finding['sku_id']}",
                ):
                    try:
                        if st.session_state.review_mode == LIVE_MODE:
                            pending = live_client().request_draft(finding)
                            st.session_state.pending_draft = {
                                "mode": "live",
                                **pending.to_dict(),
                            }
                        else:
                            st.session_state.pending_draft = prepare_local_pending(finding)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Draft request stopped safely: {exc}")
            if index < len(findings) - 1:
                st.divider()


def render_execution_metrics(review: dict[str, Any]) -> None:
    execution = review["execution"]
    with st.container(border=True, key="openai_execution"):
        st.subheader("Measured OpenAI execution")
        if execution["mode"] == "live_responses_api_remote_mcp":
            st.caption(
                "Last run completed: "
                f"**{display_run_time(execution.get('measured_at'))}**"
            )
            response_col, model_col = st.columns([3, 1])
            response_col.caption("Response ID")
            response_col.code(
                execution["response_id"] or "—",
                language=None,
                wrap_lines=True,
            )
            model_col.caption("Model")
            model_col.code(
                execution["model"] or "—",
                language=None,
                wrap_lines=True,
            )
            tokens_col, latency_col, cost_col = st.columns(3)
            tokens_col.metric(
                "Tokens", execution["api_usage"].get("total_tokens") or "—"
            )
            latency_col.metric("Latency", f"{execution['latency_seconds']} s")
            cost_col.metric(
                "Estimated API cost",
                (
                    f"${execution['api_cost_usd']}"
                    if execution["api_cost_usd"] is not None
                    else "—"
                ),
            )
            remote = review.get("remote_mcp", {})
            st.success(
                f"Remote MCP transport: {remote.get('transport', 'unknown')} · "
                f"successful calls: "
                f"{', '.join(remote.get('successful_calls', [])) or 'none'} · "
                "strict structured output validated"
            )
            basis = execution.get("cost_basis", {})
            if basis.get("pricing_source_url"):
                st.markdown(
                    f"Cost basis: published rates observed "
                    f"{basis.get('pricing_observed_at')} · "
                    f"[OpenAI pricing source]({basis['pricing_source_url']}). "
                    "Billing records remain authoritative."
                )
        else:
            st.warning(
                "Emergency fixture mode does not produce OpenAI API measurements."
            )
        with st.expander("Full execution metadata"):
            st.json(execution)
            if execution["mode"] != "live_responses_api_remote_mcp":
                st.warning(
                    "Fixture timing and correctness are not OpenAI API measurements."
                )


def render_review_tab() -> None:
    products = repository.get_catalog("northfield-home-goods")
    product_by_id = {product["sku_id"]: product for product in products}
    default_skus = ["NF-DW-001", "NF-DW-002", "NF-DW-003", "NF-DW-004"]
    if "products_to_review" not in st.session_state:
        st.session_state.products_to_review = default_skus
    st.caption(
        "Select one or more products for the audit. To edit a product description, "
        "select only one product; its temporary review-only editor will appear below."
    )
    sku_ids = st.multiselect(
        "Choose products to review",
        list(product_by_id),
        key="products_to_review",
        format_func=lambda sku: f"{sku} — {product_by_id[sku]['name']}",
        help=(
            "Select one or more products. When exactly one product is selected, its "
            "review-only description editor appears below."
        ),
    )
    st.caption(
        "Use the blue dropdown button on the right to browse or add products. "
        "Removing a selected product returns it to the dropdown list."
    )

    edit_sku: str | None = None
    edited_description: str | None = None
    description_changed = False

    if len(sku_ids) == 1:
        edit_sku = sku_ids[0]
        original_description = product_by_id[edit_sku]["description"]
        st.caption(
            "One product selected. You can edit its description below to test how "
            "additional product facts affect the review."
        )
        edited_description = st.text_area(
            "Review-only product description",
            value=original_description,
            height=120,
            key=f"description-{edit_sku}",
            help=(
                "This temporary edit does not change the stored Northfield product "
                "record. Describe only observable or supplier/laboratory-confirmed facts."
            ),
        )
        description_changed = edited_description != original_description
        if description_changed:
            st.info(
                f"This review will use the edited description for {edit_sku}. The "
                "stored product record will remain unchanged."
            )
    elif sku_ids:
        st.caption(
            f"{len(sku_ids)} products selected for a batch review. Description editing "
            "becomes available when exactly one product is selected."
        )
    else:
        st.info("Select at least one product to run a tariff review.")

    run_label = "Run edited SKU review" if description_changed else "Run tariff review"
    selected_sku_set = set(sku_ids)
    review_sku_ids = [sku for sku in product_by_id if sku in selected_sku_set]
    if st.button(
        run_label,
        type="primary",
        key="run_tariff_review",
        disabled=not sku_ids or not review_available,
        help=(
            "Select at least one product to review."
            if not sku_ids
            else (
                "Configure the live Responses API and MCP connection before running."
                if not review_available
                else None
            )
        ),
    ):
        progress = st.status("Tariff review in progress", expanded=True)
        try:
            st.session_state.pop("review", None)
            if mode == LIVE_MODE:
                progress.write(
                    "The model can choose from these read-only MCP tools: `get_catalog`, "
                    "`get_entries`, `search_hts`, `search_rulings`, and `get_ruling`. "
                    "Duty differences are calculated afterward by application code. "
                    "Connection and tool-call lifecycle events will appear below as "
                    "the Responses API streams them."
                )
            st.session_state.review = run_review(
                mode,
                review_sku_ids,
                edit_sku,
                edited_description,
                progress_callback=progress.write,
            )
            st.session_state.review_mode = mode
            st.session_state.pop("pending_draft", None)
            st.session_state.pop("draft_result", None)
            progress.update(
                label="Tariff review complete",
                state="complete",
                expanded=False,
            )
        except Exception as exc:
            st.session_state.pop("review", None)
            progress.update(
                label="Tariff review stopped safely",
                state="error",
                expanded=True,
            )
            st.error(f"Review stopped safely: {exc}")

    review = st.session_state.get("review")
    if review:
        st.divider()
        render_review_results(review)

    pending = st.session_state.get("pending_draft")
    if pending:
        st.header("Broker approval required")
        st.warning(
            "Review the exact pending arguments. Approval authorizes one local draft only; "
            "it does not file anything with CBP."
        )
        displayed = {
            key: ("[single-use token hidden]" if key == "approval_token" else value)
            for key, value in pending["arguments"].items()
        }
        st.json(displayed)
        approve_column, deny_column = st.columns(2)
        if approve_column.button("Approve one draft", type="primary"):
            try:
                if pending["mode"] == "live":
                    payload = {key: value for key, value in pending.items() if key != "mode"}
                    result = live_client().resolve_draft(
                        PendingDraft(**payload), approve=True
                    )
                else:
                    local_tools.approval_store.approve(
                        pending["approval_token"], pending["arguments"]
                    )
                    result = local_tools.draft_correction(**pending["arguments"])
                st.session_state.draft_result = result
                st.session_state.pop("pending_draft", None)
                st.rerun()
            except Exception as exc:
                st.error(f"Draft was not created: {exc}")
        if deny_column.button("Deny draft"):
            try:
                if pending["mode"] == "live":
                    payload = {key: value for key, value in pending.items() if key != "mode"}
                    result = live_client().resolve_draft(
                        PendingDraft(**payload), approve=False
                    )
                else:
                    local_tools.approval_store.deny(pending["approval_token"])
                    result = {"status": "denied"}
                st.session_state.draft_result = result
                st.session_state.pop("pending_draft", None)
                st.rerun()
            except Exception as exc:
                st.error(f"Denial could not be recorded: {exc}")

    draft_result = st.session_state.get("draft_result")
    if draft_result:
        if draft_result.get("status") == "denied":
            st.info("Draft request denied. No draft was created.")
        else:
            st.success("Draft created locally. It has not been filed.")
            st.json(draft_result)
            if draft_result.get("execution"):
                st.caption("The draft continuation's live API metadata is included above.")


def render_execution_tab() -> None:
    review = st.session_state.get("review")
    if review:
        render_execution_metrics(review)
    else:
        st.info(
            "Run a tariff review to see its measured OpenAI execution details here."
        )


review_tab, execution_tab = st.tabs(["Tariff review", "OpenAI execution details"])
with review_tab:
    render_review_tab()
with execution_tab:
    render_execution_tab()
