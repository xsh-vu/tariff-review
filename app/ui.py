from __future__ import annotations

import json
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


def load_json(path: Any) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def display_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "Not recorded"
    return value.replace("T", " ").replace("Z", " UTC")


def evaluation_case_rows(result: dict[str, Any]) -> list[dict[str, str]]:
    measured_at = display_timestamp(result.get("measured_at"))
    labels = {
        "live_description_edit_changes_review": (
            "Live description edit changes the review"
        ),
        "prompt_injection_text_does_not_force_classification": (
            "Prompt-injection text does not force a classification"
        ),
        "remote_mcp_and_structured_output": (
            "Remote MCP and strict Structured Outputs complete end to end"
        ),
    }
    rows = []
    for case in result.get("cases", []):
        raw_name = str(case.get("name", "Unnamed check"))
        if raw_name.startswith("live_classification:"):
            label = f"Live classification — {raw_name.split(':', 1)[1]}"
        elif raw_name.startswith("classification:"):
            label = f"Deterministic classification — {raw_name.split(':', 1)[1]}"
        else:
            label = labels.get(raw_name, raw_name.replace("_", " ").title())

        detail_parts = []
        if "expected_outcome" in case:
            detail_parts.append(
                "Outcome: "
                f"expected {case.get('expected_outcome')}; "
                f"observed {case.get('actual_outcome')}"
            )
        if "expected_code" in case:
            detail_parts.append(
                "HTS: "
                f"expected {case.get('expected_code') or 'no proposal'}; "
                f"observed {case.get('actual_code') or 'no proposal'}"
            )
        elif "actual_outcome" in case:
            detail_parts.append(
                f"Observed {case.get('actual_outcome')} at "
                f"{case.get('actual_code') or 'no proposed code'}"
            )
        if case.get("transport"):
            calls = sorted(set(case.get("successful_calls", [])))
            detail_parts.append(
                f"Transport: {case['transport']}; tools: {', '.join(calls)}"
            )
        if not detail_parts:
            detail_parts.append("Recorded behavior matched the expected safeguard.")
        rows.append(
            {
                "Result": "Passed" if case.get("passed") else "Failed",
                "Check": label,
                "Recorded evidence": " · ".join(detail_parts),
                "Run (UTC)": measured_at,
            }
        )
    return rows


def render_evaluation_tab(
    fixture_eval: dict[str, Any] | None,
    live_eval: dict[str, Any] | None,
    live_preflight: dict[str, Any] | None,
) -> None:
    st.header("Evaluation evidence")
    st.caption(
        "Recorded results are displayed as measured. The deterministic suite checks "
        "application behavior; the live suite measures the Responses API and remote "
        "MCP workflow."
    )

    st.subheader("Application regression suite")
    if fixture_eval:
        summary = fixture_eval.get("summary", {})
        passed_col, run_col, duration_col = st.columns(3)
        passed_col.metric(
            "Checks passed",
            f"{summary.get('passed', '—')}/{summary.get('total', '—')}",
        )
        run_col.metric("Last run", display_timestamp(fixture_eval.get("measured_at")))
        duration_col.metric(
            "Suite duration", f"{fixture_eval.get('elapsed_seconds', '—')} s"
        )
        st.info(
            "These are deterministic workflow and safety regressions. They do not "
            "measure model accuracy or OpenAI API performance."
        )
        fixture_rows = evaluation_case_rows(fixture_eval)
        st.dataframe(
            fixture_rows,
            hide_index=True,
            height=35 * (len(fixture_rows) + 1) + 3,
        )
        with st.expander("Regression-suite limitations and recorded totals"):
            st.json(
                {
                    "evaluation_mode": fixture_eval.get("evaluation_mode"),
                    "financial_checks": fixture_eval.get("financial_checks"),
                    "limitations": fixture_eval.get("limitations", []),
                }
            )
    else:
        st.info("No application regression result is recorded yet.")

    st.divider()
    st.subheader("Live OpenAI integration checks")
    if live_eval:
        summary = live_eval.get("summary", {})
        aggregate = live_eval.get("aggregate", {})
        passed_col, run_col, calls_col = st.columns(3)
        passed_col.metric(
            "Checks passed",
            f"{summary.get('passed', '—')}/{summary.get('total', '—')}",
            live_eval.get("status", "unknown"),
        )
        run_col.metric("Last run", display_timestamp(live_eval.get("measured_at")))
        calls_col.metric("Responses API calls", aggregate.get("api_calls", "—"))
        usage_col, latency_col, cost_col = st.columns(3)
        usage_col.metric("Total tokens", aggregate.get("total_tokens", "—"))
        latency_col.metric(
            "Measured latency", f"{aggregate.get('latency_seconds', '—')} s"
        )
        cost_col.metric(
            "Estimated API cost",
            f"${aggregate.get('estimated_api_cost_usd', '—')}",
        )
        live_rows = evaluation_case_rows(live_eval)
        st.dataframe(
            live_rows,
            hide_index=True,
            height=35 * (len(live_rows) + 1) + 3,
        )

        executions = []
        for execution in live_eval.get("executions", []):
            executions.append(
                {
                    "Run (UTC)": display_timestamp(execution.get("measured_at")),
                    "Response ID": execution.get("response_id", "—"),
                    "Model": execution.get("model", "—"),
                    "Tokens": execution.get("api_usage", {}).get("total_tokens", "—"),
                    "Latency (s)": execution.get("latency_seconds", "—"),
                    "Estimated cost": (
                        f"${execution.get('api_cost_usd')}"
                        if execution.get("api_cost_usd") is not None
                        else "—"
                    ),
                }
            )
        if executions:
            with st.expander("Individual live API executions"):
                st.dataframe(executions, hide_index=True)
        if live_eval.get("failure"):
            st.error(
                "Latest live evaluation failed safely: "
                f"{live_eval['failure'].get('message')}"
            )
        with st.expander("Live-evaluation limitations and recorded totals"):
            st.json(
                {
                    "evaluation_mode": live_eval.get("evaluation_mode"),
                    "financial_checks": live_eval.get("financial_checks"),
                    "limitations": live_eval.get("limitations", []),
                }
            )
    elif live_preflight and live_preflight.get("status") == "failed":
        failure = live_preflight.get("failure", {})
        st.error(
            "Latest live preflight failed safely: "
            f"{failure.get('type', 'unknown error')} · "
            f"run {display_timestamp(live_preflight.get('measured_at'))} · "
            f"{live_preflight.get('elapsed_seconds', '—')} s"
        )
        st.caption(failure.get("message", "No failure detail recorded."))
    else:
        st.info(
            "No live OpenAI evaluation has been recorded. Run `python -m evals.live` "
            "after configuring the API and remote MCP path."
        )


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

fixture_eval = load_json(PROJECT_ROOT / "evals" / "results.json")
live_eval = load_json(PROJECT_ROOT / "evals" / "live_results.json")
live_preflight = load_json(PROJECT_ROOT / "runs" / "live_preflight.json")

def render_review_tab() -> None:
    products = repository.get_catalog("northfield-home-goods")
    product_by_id = {product["sku_id"]: product for product in products}
    default_skus = ["NF-DW-001", "NF-DW-002", "NF-DW-003", "NF-DW-004"]
    st.caption(
        "Select one or more products for the audit. To edit a product description, "
        "select only one product; its temporary review-only editor will appear below."
    )
    sku_ids = st.multiselect(
        "Choose products to review",
        list(product_by_id),
        default=default_skus,
        format_func=lambda sku: f"{sku} — {product_by_id[sku]['name']}",
        help=(
            "Select one or more products. When exactly one product is selected, its "
            "review-only description editor appears below."
        ),
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
    if st.button(
        run_label,
        type="primary",
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
                    "Actual calls will be listed below after the "
                    "Responses API returns them."
                )
            st.session_state.review = run_review(
                mode,
                sku_ids,
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
        proposal = review["proposal"]
        st.divider()
        st.header("Audit results")
        over, under, status = st.columns(3)
        over.metric("Potential overpayment", money(review["potential_overpayment_total"]))
        under.metric("Underpayment exposure", money(review["potential_underpayment_total"]))
        status.metric("Review status", proposal["status"].title())
        st.caption(
            "Potential differences are not guaranteed refunds. Chapter 99 duties, trade remedies, "
            "preferences, origin, deadlines, and recovery eligibility are excluded."
        )

        ordered_outcomes = [
            "potential_overpayment",
            "potential_underpayment",
            "needs_info",
            "confirmed",
        ]
        findings = sorted(
            proposal["findings"], key=lambda item: ordered_outcomes.index(item["outcome"])
        )
        for finding in findings:
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
            st.divider()

        execution = review["execution"]
        if execution["mode"] == "live_responses_api_remote_mcp":
            st.subheader("Measured OpenAI execution")
            response_col, model_col, tokens_col, latency_col, cost_col = st.columns(5)
            response_col.metric("Response ID", execution["response_id"] or "—")
            model_col.metric("Model", execution["model"] or "—")
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
                f"successful calls: {', '.join(remote.get('successful_calls', [])) or 'none'} · "
                "strict structured output validated"
            )
            basis = execution.get("cost_basis", {})
            if basis.get("pricing_source_url"):
                st.markdown(
                    f"Cost basis: published rates observed {basis.get('pricing_observed_at')} · "
                    f"[OpenAI pricing source]({basis['pricing_source_url']}). "
                    "Billing records remain authoritative."
                )
        with st.expander("Full execution metadata"):
            st.json(execution)
            if execution["mode"] != "live_responses_api_remote_mcp":
                st.warning("Fixture timing and correctness are not OpenAI API measurements.")

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


review_tab, evaluation_tab = st.tabs(["Tariff review", "Evaluation evidence"])
with review_tab:
    render_review_tab()
with evaluation_tab:
    render_evaluation_tab(fixture_eval, live_eval, live_preflight)
