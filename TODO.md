# TODO — Five-Hour Demo Build

**Scope:** 12 synthetic SKUs, 2–3 verified classification scenarios, 6–10 verified CBP CROSS rulings (four minimum), base Column 1 General duties only, draft-only corrections.

**Current status (2026-10-18):** The vertical slice passed its authenticated Responses API + private MCP tunnel preflight, focused live evaluation, broker-approved correction-draft continuation, and a 216-second timed rehearsal. Actual failures and measured usage are recorded in `LIVE_VALIDATION.md`; the application remains a bounded prototype, not a production customs-compliance system.

## Phase 1 — Evidence and synthetic data (45 minutes)

- [x] Approve 2–3 scenarios supported by official HTS text and genuine CBP rulings.
- [x] Verify each code, description, Column 1 General rate, schedule revision, ruling ID, and source URL.
- [x] Assemble 6–10 usable rulings, or document why the four-ruling minimum is the defensible stopping point.
- [x] Define 12 synthetic SKUs and bounded historical entries without inventing legal facts.
- [x] Include potential overpayment, potential underpayment, missing-information, and correctly classified fixtures.
- [x] Label duty differences as potential, not guaranteed refunds.

## Phase 2 — MCP tools and deterministic calculations (55 minutes)

- [x] Implement minimal product, entry, HTS evidence, ruling, calculator, and draft tools.
- [x] Validate tool inputs and return explicit missing/unsupported errors.
- [x] Calculate only applicable historical base Column 1 General duty.
- [x] Keep positive potential overpayments and negative underpayment exposure separate.
- [x] Prove the selected authenticated `server_url` or private `tunnel_id` path with a live MCP smoke test.
- [x] Ensure `draft_correction` cannot persist without current, single-use broker authorization.

## Phase 3 — Responses API agent (60 minutes)

- [x] Use the official SDK and a model verified by a live account preflight to support remote MCP and Structured Outputs.
- [x] Restrict MCP imports with `allowed_tools`.
- [x] Produce a strict `ClassificationProposal` schema through `text.format`.
- [x] Reject refusals, incomplete responses, failed tool calls, unfetched citations, and unsupported codes safely.
- [x] Compose calculator-owned financial values into the application-authored review record.
- [x] Record actual response ID, model, usage, elapsed time, and cost basis.

## Phase 4 — Streamlit UI and broker approval (45 minutes)

- [x] Show prioritized findings, source links, separate risk categories, and deterministic duty differences.
- [x] Support one live product-description edit and single-SKU rerun.
- [x] Display exact pending tool arguments before approval or denial.
- [x] Implement API continuation with `mcp_approval_response` for the single approved call; live proof remains pending.
- [x] Generate a local correction draft only; never file or imply filing.

## Phase 5 — Evaluation and hardening (45 minutes)

- [x] Verify one evidence-backed potential overpayment and its arithmetic.
- [x] Verify underpayment is escalated and never presented as savings.
- [x] Verify missing decisive information causes abstention.
- [x] Verify a correctly classified SKU is not falsely flagged.
- [x] Test citation validity, prompt injection, tool failure, invalid dates/codes, and approval denial/replay.
- [x] Record actual results, failures, latency, token usage, and API cost; do not fabricate metrics.

## Phase 6 — Slides, documentation, and rehearsal (50 minutes)

- [x] Prepare 3–5 slides centered on premium-audit revenue and the importer aha moment.
- [x] Clearly label synthetic data, illustrative commercial assumptions, measured results, and exclusions.
- [x] Document setup, run, test, and demo commands.
- [x] Capture a tested fallback run and rendered deck previews.
- [x] Rehearse the complete workflow in five minutes.

## Final acceptance criteria

- [x] Genuine Responses API + MCP workflow runs end to end.
- [x] At least one defensible, evidence-backed potential overpayment is quantified.
- [x] Potential underpayment is escalated instead of treated as an opportunity.
- [x] Missing information produces no guessed classification.
- [x] A correctly classified SKU remains unflagged.
- [x] Editing a product description triggers a new review.
- [x] Explicit human approval precedes correction-draft generation.
- [x] Actual usage, latency, cost, and evaluation results are visible.
- [x] Premium-audit revenue is explained with clearly illustrative assumptions.

## Post-demo model-selection evaluation

- [x] Create 20 historical CBP CROSS cases outside the searchable evidence corpus.
- [x] Separate sanitized model inputs from ruling IDs, codes, rates, and holdings.
- [x] Verify official source URLs, ruling-date codes, and CBP status fields.
- [x] Add deterministic checks for corpus overlap and gold-label leakage.
- [ ] Obtain licensed-customs-broker review of the case facts and gold labels.
- [ ] Run repeated GPT-6 Luna, GPT-6.1 Sol, and GPT-6 Astra comparisons.
- [ ] Record exact-code and six-digit accuracy, abstentions, citations, latency, usage, cost, and failures.
- [ ] Select the least costly model that satisfies the predefined quality and safety gates.
