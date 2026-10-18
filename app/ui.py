from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from agent.client import PendingDraft, TariffReviewClient, live_configuration_status
from agent.fixture_review import FixtureReviewer
from data.repository import PROJECT_ROOT, Repository
from server import tools as local_tools


load_dotenv(PROJECT_ROOT / ".env")
repository = Repository()


def money(value: str | Decimal) -> str:
    return f"${Decimal(value):,.2f}"


def load_json(path: Any) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


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


def render_finding(
    finding: dict[str, Any], calculations: dict[str, dict[str, Any]]
) -> None:
    labels = {
        "potential_overpayment": "Potential overpayment",
        "potential_underpayment": "Potential underpayment — escalate",
        "needs_info": "Needs information",
        "confirmed": "Classification confirmed",
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
        st.write(f"Recommended action: {finding['recommended_action']}")
        st.write(f"Uncertainty: {finding['confidence_or_uncertainty']}")
        if calculation:
            st.json(calculation)


def run_review(
    mode: str, sku_ids: list[str], edit_sku: str, edited_description: str
) -> dict[str, Any]:
    original = repository.get_product("northfield-home-goods", edit_sku)["description"]
    overrides = {edit_sku: edited_description} if edited_description != original else {}
    if mode == "Live Responses API + MCP":
        return TariffReviewClient().review(sku_ids, overrides)
    return FixtureReviewer().review(sku_ids, overrides)


st.set_page_config(page_title="Harbor & Crane Tariff Audit", layout="wide")
st.title("Harbor & Crane · Premium Tariff Audit")
st.caption(
    "Northfield Home Goods · evidence-backed screening · Column 1 General base duty only"
)

is_live, live_message = live_configuration_status()
mode_options = ["Deterministic fixture preview"]
if is_live:
    mode_options.insert(0, "Live Responses API + MCP")
mode = st.radio("Execution mode", mode_options, horizontal=True)
if is_live:
    st.success(live_message)
else:
    st.info(f"Live mode unavailable: {live_message}. Fixture preview remains usable.")

fixture_eval = load_json(PROJECT_ROOT / "evals" / "results.json")
live_eval = load_json(PROJECT_ROOT / "evals" / "live_results.json")
live_preflight = load_json(PROJECT_ROOT / "runs" / "live_preflight.json")
with st.expander("Evaluation evidence", expanded=True):
    fixture_col, live_col = st.columns(2)
    if fixture_eval:
        fixture_summary = fixture_eval.get("summary", {})
        fixture_col.metric(
            "Deterministic fixture checks",
            f"{fixture_summary.get('passed', '—')}/{fixture_summary.get('total', '—')}",
        )
        fixture_col.caption(
            "Local workflow regression checks; these are not model-accuracy measurements."
        )
    else:
        fixture_col.info("No deterministic evaluation result is recorded yet.")
    if live_eval:
        live_summary = live_eval.get("summary", {})
        live_col.metric(
            "Live Responses API checks",
            f"{live_summary.get('passed', '—')}/{live_summary.get('total', '—')}",
            live_eval.get("status", "unknown"),
        )
        aggregate = live_eval.get("aggregate", {})
        live_col.caption(
            f"Measured {live_eval.get('measured_at', 'unknown')} · "
            f"{aggregate.get('total_tokens', '—')} tokens · "
            f"{aggregate.get('latency_seconds', '—')} s · "
            f"${aggregate.get('estimated_api_cost_usd', '—')} estimated API cost"
        )
        if live_eval.get("failure"):
            live_col.error(
                f"Latest live evaluation failed safely: {live_eval['failure'].get('message')}"
            )
    else:
        if live_preflight and live_preflight.get("status") == "failed":
            failure = live_preflight.get("failure", {})
            live_col.error(
                "Latest live preflight failed safely: "
                f"{failure.get('type', 'unknown error')} · "
                f"measured {live_preflight.get('measured_at', 'unknown')} · "
                f"{live_preflight.get('elapsed_seconds', '—')} s"
            )
            live_col.caption(failure.get("message", "No failure detail recorded."))
        else:
            live_col.info(
                "No live OpenAI evaluation has been recorded. Run `python -m evals.live` after configuring the API and remote MCP path."
            )

products = repository.get_catalog("northfield-home-goods")
product_by_id = {product["sku_id"]: product for product in products}
default_skus = ["NF-DW-001", "NF-DW-002", "NF-DW-003", "NF-DW-004"]
sku_ids = st.multiselect(
    "SKUs to review",
    list(product_by_id),
    default=default_skus,
    format_func=lambda sku: f"{sku} — {product_by_id[sku]['name']}",
)

edit_sku = st.selectbox(
    "Live-edit one product description",
    sku_ids or list(product_by_id),
    format_func=lambda sku: f"{sku} — {product_by_id[sku]['name']}",
)
edited_description = st.text_area(
    "Description supplied to this review",
    value=product_by_id[edit_sku]["description"],
    height=120,
    key=f"description-{edit_sku}",
)

if st.button("Run tariff review", type="primary", disabled=not sku_ids):
    try:
        with st.spinner("Reviewing products and validating evidence…"):
            st.session_state.review = run_review(
                mode, sku_ids, edit_sku, edited_description
            )
            st.session_state.review_mode = mode
            st.session_state.pop("pending_draft", None)
            st.session_state.pop("draft_result", None)
    except Exception as exc:
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
                    if st.session_state.review_mode == "Live Responses API + MCP":
                        pending = TariffReviewClient().request_draft(finding)
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
                result = TariffReviewClient().resolve_draft(
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
                result = TariffReviewClient().resolve_draft(
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
