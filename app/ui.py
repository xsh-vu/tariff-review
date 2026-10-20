from __future__ import annotations

import os
import sys
from decimal import Decimal
from inspect import signature
from pathlib import Path
from typing import Any, Callable

import streamlit as st
from dotenv import load_dotenv

# Streamlit may launch this file with app/ as sys.path[0]. Ensure repository
# packages remain importable regardless of the caller's working directory.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from agent.client import PendingDraft, TariffReviewClient, live_configuration_status
from agent.fixture_review import FixtureReviewer
from app.evaluation_results import (
    EvaluationResultError,
    load_published_historical_result,
    nonmatching_case_rows,
)
from app.review_cache import (
    build_review_fingerprint,
    get_review_result,
    mark_live_review,
    store_review_result,
)
from app.progress import AutoScrollingStatus, run_with_heartbeat
from app.recommendations import summarize_recommendations
from data.repository import PROJECT_ROOT, Repository
from server import tools as local_tools


load_dotenv(PROJECT_ROOT / ".env")
repository = Repository()
LIVE_MODE = "Live Responses API + MCP"
FIXTURE_MODE = "Emergency deterministic fixture preview"
LIVE_CLIENT_STATE_KEY = "_tariff_review_live_client"
MCP_DISCOVERY_STATE_KEY = "_tariff_review_mcp_discovery"
REVIEW_RESULT_CACHE_STATE_KEY = "_tariff_review_result_cache"
SCROLL_TO_APPROVAL_STATE_KEY = "_tariff_review_scroll_to_approval"
SCROLL_TO_SKU_STATE_KEY = "_tariff_review_scroll_to_sku"


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
        client.restore_review_discovery_cache(
            st.session_state.get(MCP_DISCOVERY_STATE_KEY)
        )
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
    st.markdown(f"### `{finding['sku_id']}` · {labels[finding['outcome']]}")
    left, middle, right = st.columns(3)
    left.metric("Declared classification code", finding["declared_code"])
    middle.metric(
        "Proposed classification code",
        finding["proposed_code"] or "No proposal",
    )
    calculation = calculations.get(finding["sku_id"])
    if calculation:
        difference = Decimal(calculation["potential_base_duty_difference"])
        displayed_difference = (
            f"-{money(abs(difference))}" if difference < 0 else money(difference)
        )
        if difference > 0:
            with right.container(key=f"duty_overpayment_{finding['sku_id']}"):
                st.metric("Potential base-duty difference", displayed_difference)
        elif difference < 0:
            with right.container(key=f"duty_underpayment_{finding['sku_id']}"):
                st.metric("Potential base-duty difference", displayed_difference)
        else:
            right.metric("Potential base-duty difference", displayed_difference)
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
        try:
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
                    "search_hts_batch",
                    "search_rulings_batch",
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
        finally:
            if hasattr(client, "export_review_discovery_cache"):
                discovery_state = client.export_review_discovery_cache()
                if discovery_state is None:
                    st.session_state.pop(MCP_DISCOVERY_STATE_KEY, None)
                else:
                    st.session_state[MCP_DISCOVERY_STATE_KEY] = discovery_state
    if mode == FIXTURE_MODE:
        if progress_callback is not None:
            progress_callback(
                "Fixture fallback · running the local rule-based review without "
                "the Responses API or remote MCP."
            )
        return FixtureReviewer().review(sku_ids, overrides)
    raise ValueError(f"Unsupported execution mode: {mode}")


def review_description_overrides(
    edit_sku: str | None, edited_description: str | None
) -> dict[str, str]:
    if edit_sku is None or edited_description is None:
        return {}
    original = repository.get_product("northfield-home-goods", edit_sku)["description"]
    return {edit_sku: edited_description} if edited_description != original else {}


def session_review_cache() -> dict[str, dict[str, Any]]:
    cache = st.session_state.get(REVIEW_RESULT_CACHE_STATE_KEY)
    if not isinstance(cache, dict):
        cache = {}
        st.session_state[REVIEW_RESULT_CACHE_STATE_KEY] = cache
    return cache


def execute_review_with_cache(
    *,
    mode: str,
    sku_ids: list[str],
    edit_sku: str | None,
    edited_description: str | None,
    progress: AutoScrollingStatus,
    force_fresh: bool = False,
) -> dict[str, Any]:
    """Run one validated review, reusing an exact live result when available."""
    cached_review = None
    fingerprint = None
    if mode == LIVE_MODE:
        client = live_client()
        overrides = review_description_overrides(edit_sku, edited_description)
        fingerprint = build_review_fingerprint(
            client,
            repository,
            sku_ids,
            overrides,
        )
        if force_fresh:
            progress.write(
                "Session cache · bypass requested; starting a new OpenAI + MCP "
                "execution."
            )
        else:
            progress.write(
                "Session cache · checking for an exact validated match across "
                "products, description, evidence, model, schema, and tool policy."
            )
            cached_review = get_review_result(session_review_cache(), fingerprint)
        if cached_review is not None:
            progress.write(
                "Session cache · exact match found. Reusing the validated review "
                "with 0 new OpenAI requests and 0 MCP calls."
            )
            return cached_review

        progress.write(
            "The model can choose from these read-only MCP tools: `get_catalog`, "
            "`get_entries`, `search_hts_batch`, and `search_rulings_batch`. "
            "Duty differences are calculated afterward by application code. "
            "Connection and tool-call lifecycle events will appear below as the "
            "Responses API streams them."
        )

    completed_review = run_review(
        mode,
        sku_ids,
        edit_sku,
        edited_description,
        progress_callback=progress.write,
    )
    if mode == LIVE_MODE:
        completed_review = mark_live_review(completed_review)
        if fingerprint is None:
            raise RuntimeError("Live review cache fingerprint was not created")
        store_review_result(session_review_cache(), fingerprint, completed_review)
        progress.write(
            "Session cache · validated result retained for exact reruns for up to "
            "30 minutes."
        )
    return completed_review


def request_draft_with_progress(
    client: TariffReviewClient,
    finding: dict[str, Any],
    progress_callback: Callable[[str], None],
) -> PendingDraft:
    """Support Streamlit sessions that retained a pre-callback client module."""
    if "progress_callback" in signature(client.request_draft).parameters:
        return client.request_draft(
            finding,
            progress_callback=progress_callback,
        )
    progress_callback(
        "Compatibility · this hot-reloaded session has the earlier approval client; "
        "waiting for its Responses API approval request without lifecycle events."
    )
    return client.request_draft(finding)


def resolve_draft_with_progress(
    client: TariffReviewClient,
    pending: PendingDraft,
    approve: bool,
    progress_callback: Callable[[str], None],
) -> dict[str, Any]:
    """Support Streamlit sessions that retained a pre-callback client module."""
    if "progress_callback" in signature(client.resolve_draft).parameters:
        return client.resolve_draft(
            pending,
            approve=approve,
            progress_callback=progress_callback,
        )
    progress_callback(
        "Compatibility · this hot-reloaded session has the earlier approval client; "
        "waiting for its Responses API approval continuation without lifecycle events."
    )
    return client.resolve_draft(pending, approve=approve)


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
    .st-key-historical_evaluation {
        background: linear-gradient(
            135deg,
            rgba(37, 99, 235, 0.08),
            rgba(14, 116, 144, 0.04)
        );
        border-color: rgba(59, 130, 246, 0.28) !important;
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
    button[kind="primary"],
    .st-key-tariff_review_results_container button[kind="secondary"],
    .st-key-tariff_review_results_container [data-testid="stFormSubmitButton"] button {
        background-color: rgba(37, 99, 235, 0.72) !important;
        border-color: rgba(96, 165, 250, 0.60) !important;
        color: #ffffff !important;
    }
    button[kind="primary"]:hover,
    .st-key-tariff_review_results_container button[kind="secondary"]:hover,
    .st-key-tariff_review_results_container [data-testid="stFormSubmitButton"] button:hover {
        background-color: rgba(37, 99, 235, 0.90) !important;
        border-color: rgba(147, 197, 253, 0.85) !important;
        color: #ffffff !important;
    }
    [class*="st-key-duty_overpayment_"] [data-testid="stMetricValue"] {
        color: #16a34a !important;
    }
    [class*="st-key-duty_underpayment_"] [data-testid="stMetricValue"] {
        color: #dc2626 !important;
    }
    .st-key-summary_overpayment [data-testid="stMetricValue"] {
        color: #16a34a !important;
    }
    .st-key-summary_underpayment [data-testid="stMetricValue"] {
        color: #dc2626 !important;
    }
    .st-key-summary_needs_info [data-testid="stMetricValue"],
    .st-key-summary_confirmed [data-testid="stMetricValue"] {
        font-size: 1.35rem !important;
        line-height: 1.25 !important;
        white-space: normal !important;
    }
    .st-key-summary_overpayment [data-testid="stMetricLabel"],
    .st-key-summary_underpayment [data-testid="stMetricLabel"],
    .st-key-summary_needs_info [data-testid="stMetricLabel"],
    .st-key-summary_confirmed [data-testid="stMetricLabel"] {
        min-height: 3rem !important;
    }
    .st-key-summary_overpayment [data-testid="stMetricValue"],
    .st-key-summary_underpayment [data-testid="stMetricValue"],
    .st-key-summary_needs_info [data-testid="stMetricValue"],
    .st-key-summary_confirmed [data-testid="stMetricValue"] {
        align-items: flex-end !important;
        display: flex !important;
        min-height: 2.75rem !important;
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
    outcomes = [finding["outcome"] for finding in proposal["findings"]]
    outcome_counts = {
        "potential_overpayment": outcomes.count("potential_overpayment"),
        "potential_underpayment": outcomes.count("potential_underpayment"),
        "needs_info": outcomes.count("needs_info"),
        "confirmed": outcomes.count("confirmed"),
    }
    reviewed_sku_ids = list(
        dict.fromkeys(
            finding["sku_id"]
            for finding in proposal["findings"]
            if finding.get("sku_id")
        )
    )
    reviewed_sku_count = len(reviewed_sku_ids)

    def sku_count(count: int) -> str:
        return f"{count} {'SKU' if count == 1 else 'SKUs'}"

    scroll_to_sku = st.session_state.pop(SCROLL_TO_SKU_STATE_KEY, None)

    with st.container(border=True, key="tariff_review_results_container"):
        st.header(
            f"Tariff review results · {sku_count(reviewed_sku_count)} reviewed"
        )
        cache_status = review.get("result_cache") or {}
        if cache_status.get("hit"):
            st.info(
                "Reused a validated review from this browser session. No new "
                "OpenAI request or MCP tool call was made. Original live run: "
                f"{display_run_time(cache_status.get('original_measured_at'))}. "
                "Select ‘Run fresh review’ above to execute the workflow again."
            )
        over, under, needs_info, confirmed = st.columns(4)
        with over.container(key="summary_overpayment"):
            st.metric(
                "Potential overpayment "
                f"({sku_count(outcome_counts['potential_overpayment'])})",
                money(review["potential_overpayment_total"]),
            )
        with under.container(key="summary_underpayment"):
            st.metric(
                "Underpayment exposure "
                f"({sku_count(outcome_counts['potential_underpayment'])})",
                f"-{money(abs(Decimal(review['potential_underpayment_total'])))}",
            )
        with needs_info.container(key="summary_needs_info"):
            st.metric(
                f"Needs more info ({sku_count(outcome_counts['needs_info'])})",
                "Pending evidence" if outcome_counts["needs_info"] else "None",
            )
        with confirmed.container(key="summary_confirmed"):
            st.metric(
                f"Classification confirmed ({sku_count(outcome_counts['confirmed'])})",
                "No change" if outcome_counts["confirmed"] else "None",
            )
        st.caption(f"Review status: {proposal['status'].title()}.")
        st.markdown(
            "**How these amounts were calculated:** For each affected entry, the "
            "entered value is multiplied by the declared base duty rate and by the "
            "proposed base duty rate. Declared duty minus proposed duty gives the "
            "displayed difference. Potential overpayments and underpayment exposures "
            "are totaled separately rather than netted together."
        )
        st.caption(
            "Potential differences are not guaranteed refunds. Chapter 99 duties, "
            "trade remedies, preferences, origin, deadlines, and recovery eligibility "
            "are excluded."
        )

        st.subheader("Recommended next actions")
        for recommendation in summarize_recommendations(proposal["findings"]):
            sku_list = ", ".join(
                f"`{sku_id}`" for sku_id in recommendation["sku_ids"]
            )
            st.markdown(
                f"- **{recommendation['label']} "
                f"({recommendation['count']}):** {sku_list}. "
                f"{recommendation['action']}"
            )
        if any(
            finding["outcome"] == "potential_overpayment"
            for finding in proposal["findings"]
        ):
            st.info(
                "For a potential overpayment, use **Prepare correction draft** below. "
                "You will see the exact draft request before choosing **Approve one "
                "draft** or **Deny draft**. Approval creates a local draft only; "
                "nothing is filed with CBP."
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
            finding_sku_id = finding["sku_id"]
            sku_anchor_id = "tariff-result-" + "".join(
                character if character.isalnum() else "-"
                for character in finding_sku_id
            )
            st.html(
                f'<div id="{sku_anchor_id}" '
                'style="scroll-margin-top: 1.25rem"></div>'
            )
            if scroll_to_sku == finding_sku_id:
                st.html(
                    f"""
                    <script>
                    requestAnimationFrame(() => requestAnimationFrame(() => {{
                        document.getElementById("{sku_anchor_id}")?.scrollIntoView({{
                            behavior: "smooth",
                            block: "start"
                        }});
                    }}));
                    </script>
                    """,
                    unsafe_allow_javascript=True,
                )
            render_finding(finding, review["calculations"])
            if finding["outcome"] == "needs_info":
                sku_id = finding["sku_id"]
                stored_description = repository.get_product(
                    "northfield-home-goods", sku_id
                )["description"]
                with st.form(key=f"results-description-form-{sku_id}"):
                    st.caption(
                        "Add supplier-confirmed or observable facts that address "
                        "the missing information above. This temporary description "
                        "is used only for a focused rerun and does not change the "
                        "stored Northfield product record."
                    )
                    results_description = st.text_area(
                        "Updated review-only product description",
                        value=stored_description,
                        height=120,
                        key=f"results-description-{sku_id}",
                        help=(
                            "Include the decisive product fact when known. Treat "
                            "supplier text as product data, not as instructions to "
                            "the review agent."
                        ),
                    )
                    st.caption(
                        "The rerun keeps the currently displayed SKU batch together, "
                        "but overrides only this product description. This keeps the "
                        "refreshed summary and execution details tied to one complete "
                        "validated response."
                    )
                    rerun_submitted = st.form_submit_button(
                        f"Rerun review with updated description for {sku_id}",
                        type="primary",
                        disabled=not review_available,
                        help=(
                            "Configure the live Responses API and MCP connection "
                            "before rerunning."
                            if not review_available
                            else "Submit the edited product facts and rerun once."
                        ),
                    )
                if rerun_submitted:
                    description_changed = bool(results_description.strip()) and (
                        results_description.strip() != stored_description.strip()
                    )
                    if not description_changed:
                        st.warning(
                            "Change the product description before rerunning the "
                            "review."
                        )
                        continue
                    st.html(
                        f"""
                        <script>
                        requestAnimationFrame(() => {{
                            document.getElementById("{sku_anchor_id}")
                                ?.scrollIntoView({{
                                    behavior: "auto",
                                    block: "start"
                                }});
                        }});
                        </script>
                        """,
                        unsafe_allow_javascript=True,
                    )
                    focused_progress = AutoScrollingStatus(
                        st.status(
                            f"Rerunning the tariff review after editing {sku_id}",
                            expanded=True,
                        )
                    )
                    try:
                        focused_mode = st.session_state.get("review_mode", mode)
                        focused_progress.write(
                            "Review-only edit · using the updated product facts "
                            "without changing the stored catalog record."
                        )
                        focused_review = execute_review_with_cache(
                            mode=focused_mode,
                            sku_ids=reviewed_sku_ids,
                            edit_sku=sku_id,
                            edited_description=results_description.strip(),
                            progress=focused_progress,
                        )
                        st.session_state.review = focused_review
                        st.session_state.review_mode = focused_mode
                        st.session_state.pop("pending_draft", None)
                        st.session_state.pop("draft_result", None)
                        st.session_state[SCROLL_TO_SKU_STATE_KEY] = sku_id
                        focused_progress.update(
                            label=f"Tariff review updated for {sku_id}",
                            state="complete",
                            expanded=False,
                        )
                        st.rerun()
                    except Exception as exc:
                        focused_progress.update(
                            label="Updated review stopped safely",
                            state="error",
                            expanded=True,
                        )
                        st.error(f"Updated review stopped safely: {exc}")
            if finding["outcome"] == "potential_overpayment":
                if st.button(
                    f"Prepare correction draft for {finding['sku_id']}",
                    key=f"prepare-{finding['sku_id']}",
                ):
                    try:
                        draft_progress = AutoScrollingStatus(
                            st.status(
                                "Preparing broker approval request",
                                expanded=True,
                            )
                        )
                        if st.session_state.review_mode == LIVE_MODE:
                            client = live_client()
                            pending = run_with_heartbeat(
                                lambda report: request_draft_with_progress(
                                    client,
                                    finding,
                                    report,
                                ),
                                draft_progress.write,
                                waiting_message=(
                                    "waiting for the Responses API to return "
                                    "mcp_approval_request"
                                ),
                            )
                            st.session_state.pending_draft = {
                                "mode": "live",
                                **pending.to_dict(),
                            }
                        else:
                            draft_progress.write(
                                "Fixture approval gate · creating a short-lived, "
                                "single-use local token."
                            )
                            st.session_state.pending_draft = prepare_local_pending(finding)
                            draft_progress.write(
                                "Fixture approval request ready. No OpenAI or MCP "
                                "approval event was used."
                            )
                        st.session_state[SCROLL_TO_APPROVAL_STATE_KEY] = True
                        draft_progress.update(
                            label="Broker approval request ready",
                            state="complete",
                            expanded=False,
                        )
                        st.rerun()
                    except Exception as exc:
                        if "draft_progress" in locals():
                            draft_progress.update(
                                label="Approval request stopped safely",
                                state="error",
                                expanded=True,
                            )
                        st.error(f"Draft request stopped safely: {exc}")
            if index < len(findings) - 1:
                st.divider()


def render_execution_metrics(review: dict[str, Any]) -> None:
    execution = review["execution"]
    with st.container(border=True, key="openai_execution"):
        st.subheader("Measured OpenAI execution")
        cache_status = review.get("result_cache") or {}
        if cache_status.get("hit"):
            st.info(
                "Cached display: the measurements below belong to the original "
                "live execution. This reuse made 0 new OpenAI requests and 0 MCP "
                "calls, with $0.000000 incremental API cost."
            )
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
            breakdown = execution.get("latency_breakdown") or {}
            segments = breakdown.get("segments") or []
            if segments:
                st.markdown("**Observed latency by stage**")
                st.dataframe(
                    [
                        {
                            "Stage": (
                                f"{segment['phase']} · {segment['tool']}"
                                if segment.get("tool")
                                else segment["phase"]
                            ),
                            "Start (s)": segment["started_at_seconds"],
                            "End (s)": segment["completed_at_seconds"],
                            "Duration (s)": segment["duration_seconds"],
                            "Status": segment["status"],
                        }
                        for segment in segments
                    ],
                    hide_index=True,
                    width="stretch",
                )
                st.caption(
                    breakdown.get(
                        "note",
                        "Observed stages may overlap and should not be summed.",
                    )
                )
            elif breakdown.get("mcp_discovery_reused"):
                st.caption(
                    "MCP tool discovery was safely reused for this run, so no new "
                    "discovery stage was observed."
                )
            timeline = breakdown.get("event_timeline") or []
            if timeline:
                with st.expander("Streamed event timeline"):
                    st.dataframe(timeline, hide_index=True, width="stretch")
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


def render_historical_evaluation() -> None:
    try:
        result = load_published_historical_result()
    except EvaluationResultError as exc:
        st.warning(f"Historical evaluation evidence is unavailable: {exc}")
        return

    summary = result["summary"]
    mcp = result["mcp_reliability"]
    execution = result["execution"]
    total = summary["total_cases"]
    exact = summary["exact_matches"]
    citation_valid = summary["valid_citations"]

    with st.container(border=True, key="historical_evaluation"):
        st.subheader("Tested against past customs rulings")
        st.caption(
            "Pre-recorded held-out evaluation · not rerun during this demo · "
            f"{display_run_time(result['started_at'])}"
        )
        st.write(
            "We gave the same model sanitized product facts from 20 past CBP "
            "classification cases. The model could search dated tariff evidence and "
            "analogous rulings through MCP, but it could not search the target ruling "
            "or see the hidden answer until after each response was saved."
        )

        accuracy_col, citation_col, mcp_col, leakage_col = st.columns(4)
        accuracy_col.metric(
            "Exact classifications",
            f"{exact}/{total}",
            f"{summary['exact_match_rate_all_eligible_percent']}%",
        )
        citation_col.metric("Citations validated", f"{citation_valid}/{total}")
        mcp_col.metric(
            "MCP calls succeeded",
            f"{mcp['successful_calls']}/{mcp['expected_calls']}",
        )
        leakage_col.metric("Hidden-answer leaks", summary["target_ruling_leaks"])

        st.progress(
            exact / total if total else 0,
            text=(
                f"{exact} of {total} historical classifications matched the "
                "ruling-date answer exactly."
            ),
        )
        st.caption(
            f"Model: {result['model']} · one 20-case run · selected from the "
            "three demo product families. This is useful prototype evidence, not a "
            "claim of broad customs-classification accuracy."
        )

        with st.expander("See misses, method, and execution measurements"):
            misses = nonmatching_case_rows(result)
            st.markdown("**Cases that did not exactly match**")
            if misses:
                st.dataframe(misses, hide_index=True, width="stretch")
            else:
                st.success("Every case matched exactly.")
            st.caption(
                "Citation validation is mechanical: each cited identifier had to be "
                "returned by MCP. It does not mean every analogy was legally persuasive."
            )

            latency_col, tokens_col, cost_col = st.columns(3)
            latency_col.metric(
                "Evaluation latency",
                f"{execution['p50_latency_seconds']} s p50",
                f"{execution['p95_latency_seconds']} s p95",
            )
            tokens_col.metric("Evaluation tokens", f"{execution['total_tokens']:,}")
            cost_col.metric(
                "Estimated evaluation cost",
                f"${execution['estimated_api_cost_usd']}",
            )
            st.markdown(
                "**What this run also checked:** dated HTS evidence, strict structured "
                "output, retrieved-citation provenance, MCP call completion, and "
                "hidden-answer leakage."
            )
            st.markdown("**Important limitations**")
            for limitation in result["limitations"]:
                st.markdown(f"- {limitation}")
            basis = execution.get("cost_basis") or {}
            if basis.get("pricing_observed_at"):
                st.caption(
                    "Estimated cost uses published OpenAI rates observed "
                    f"{basis['pricing_observed_at']}; billing records remain "
                    "authoritative."
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
    force_fresh_review = st.checkbox(
        "Run fresh review (bypass a matching session result)",
        value=False,
        help=(
            "Leave this off to reuse an exact validated result for up to 30 minutes. "
            "Turn it on to make a new Responses API request and new MCP calls."
        ),
    )
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
        progress = AutoScrollingStatus(
            st.status("Tariff review in progress", expanded=True)
        )
        try:
            st.session_state.pop("review", None)
            st.session_state.review = execute_review_with_cache(
                mode=mode,
                sku_ids=review_sku_ids,
                edit_sku=edit_sku,
                edited_description=edited_description,
                progress=progress,
                force_fresh=force_fresh_review,
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
        scroll_to_approval = bool(
            st.session_state.pop(SCROLL_TO_APPROVAL_STATE_KEY, False)
        )
        st.html(
            """
            <div id="broker-approval" style="scroll-margin-top: 1.25rem"></div>
            """
        )
        st.header("Broker approval required")
        if scroll_to_approval:
            # This constant script contains no user or model content. It runs once
            # after the pending draft rerun so the approval controls are visible.
            st.html(
                """
                <script>
                requestAnimationFrame(() => {
                    document.getElementById("broker-approval")?.scrollIntoView({
                        behavior: "smooth",
                        block: "start"
                    });
                });
                </script>
                """,
                unsafe_allow_javascript=True,
            )
        st.warning(
            "Review the exact pending arguments. Approval authorizes one local draft only; "
            "it does not file anything with CBP."
        )
        displayed = {
            key: ("[single-use token hidden]" if key == "approval_token" else value)
            for key, value in pending["arguments"].items()
        }
        st.json(displayed)
        decision_controls = st.empty()
        with decision_controls.container():
            approve_column, deny_column = st.columns(2)
            approve_clicked = approve_column.button(
                "Approve one draft",
                type="primary",
                key="approve_pending_draft",
            )
            deny_clicked = deny_column.button(
                "Deny draft",
                key="deny_pending_draft",
            )

        if approve_clicked:
            # Remove both controls before the blocking continuation begins. This
            # prevents Streamlit from briefly retaining an old and new widget copy.
            decision_controls.empty()
            try:
                approval_progress = AutoScrollingStatus(
                    st.status(
                        "Executing approved correction draft",
                        expanded=True,
                    )
                )
                if pending["mode"] == "live":
                    payload = {key: value for key, value in pending.items() if key != "mode"}
                    client = live_client()
                    result = run_with_heartbeat(
                        lambda report: resolve_draft_with_progress(
                            client,
                            PendingDraft(**payload),
                            True,
                            report,
                        ),
                        approval_progress.write,
                        waiting_message=(
                            "waiting for the Responses API and draft_correction MCP call"
                        ),
                    )
                else:
                    approval_progress.write(
                        "Fixture approval gate · approving the exact single-use "
                        "draft arguments."
                    )
                    local_tools.approval_store.approve(
                        pending["approval_token"], pending["arguments"]
                    )
                    approval_progress.write(
                        "Fixture tool · draft_correction · validating the token, "
                        "calculation, and evidence."
                    )
                    result = local_tools.draft_correction(**pending["arguments"])
                approval_progress.update(
                    label="Correction draft created locally",
                    state="complete",
                    expanded=False,
                )
                st.session_state.draft_result = result
                st.session_state.pop("pending_draft", None)
                st.rerun()
            except Exception as exc:
                if "approval_progress" in locals():
                    approval_progress.update(
                        label="Draft creation stopped safely",
                        state="error",
                        expanded=True,
                    )
                st.error(f"Draft was not created: {exc}")
        elif deny_clicked:
            decision_controls.empty()
            try:
                denial_progress = AutoScrollingStatus(
                    st.status(
                        "Recording correction-draft denial",
                        expanded=True,
                    )
                )
                if pending["mode"] == "live":
                    payload = {key: value for key, value in pending.items() if key != "mode"}
                    client = live_client()
                    result = run_with_heartbeat(
                        lambda report: resolve_draft_with_progress(
                            client,
                            PendingDraft(**payload),
                            False,
                            report,
                        ),
                        denial_progress.write,
                        waiting_message=(
                            "waiting for the Responses API to confirm denial"
                        ),
                    )
                else:
                    denial_progress.write(
                        "Fixture approval gate · denying the single-use local token."
                    )
                    local_tools.approval_store.deny(pending["approval_token"])
                    result = {"status": "denied"}
                denial_progress.update(
                    label="Correction draft denied; no draft created",
                    state="complete",
                    expanded=False,
                )
                st.session_state.draft_result = result
                st.session_state.pop("pending_draft", None)
                st.rerun()
            except Exception as exc:
                if "denial_progress" in locals():
                    denial_progress.update(
                        label="Draft denial stopped safely",
                        state="error",
                        expanded=True,
                    )
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
    st.divider()
    render_historical_evaluation()


review_tab, execution_tab = st.tabs(["Tariff review", "OpenAI execution details"])
with review_tab:
    render_review_tab()
with execution_tab:
    render_execution_tab()
