# Five-Minute Demo Runbook

## Before the room

1. Start the MCP server and confirm `/mcp` through the selected secure tunnel or authenticated HTTPS gateway.
2. Run `.venv/bin/python -m scripts.live_preflight`; require every check to pass.
3. Run `.venv/bin/python -m evals.live` and confirm the measured result appears in the UI.
4. Run `.venv/bin/pytest -q` and `.venv/bin/python -m evals.run`.
5. Start `.venv/bin/streamlit run app/ui.py`. The reviewer UI should show only the live Responses API + MCP workflow.
6. Open `NF-DW-001` through `NF-DW-004` as the initial selection.

## Talk track

**0:00–0:35 — Commercial problem**

Harbor & Crane can sell a premium audit that reviews imported products for classification risk. The importer sees potential base-duty overpayments. The broker also sees underpayment exposure before it becomes a larger compliance problem.

**0:35–1:45 — Four outcomes in one review**

Run the four drinkware SKUs. Point out:

- `NF-DW-001`: confirmed non-vacuum construction supports 7323.93.0080 and a deterministic $12,480 potential base-duty overpayment.
- `NF-DW-002`: confirmed vacuum construction creates $6,240 of potential underpayment exposure and routes to counsel.
- `NF-DW-003`: no vacuum evidence means the review abstains and requests supplier information.
- `NF-DW-004`: the declared vacuum-vessel code remains confirmed.

State that potential overpayments are not guaranteed refunds. The demo excludes trade remedies, Chapter 99 duties, preference programs, origin, deadlines, entry status, and recovery eligibility.

**1:45–2:35 — Evidence and trust boundary**

Open the CBP ruling links for the first finding. Explain that the model proposes a classification, while application code checks that every ruling was fetched and every proposed HTS code appeared in the run's HTS search. Python owns the duty calculation.

**2:35–3:20 — Live product fact edit**

Select `NF-DW-003` only. Replace its description with:

> 14 oz complete stainless-steel vacuum flask with laboratory-confirmed sub-atmospheric pressure between its walls.

Rerun. The case changes from `needs_info` to potential underpayment exposure. The change follows a decisive fact rather than a scripted answer.

**3:20–4:15 — Human approval**

Return to `NF-DW-001`, choose **Prepare correction draft**, and show the exact pending tool arguments. Approve one draft. Emphasize that OpenAI's per-call approval and the application's expiring single-use token protect the write. The result remains a local, unfiled draft.

**Recorded rehearsal:** 216 seconds end to end on 2026-10-18, including explicit human approval. The run created one local `draft_only` record and did not file anything. See `LIVE_VALIDATION.md`.

**4:15–5:00 — Revenue and next step**

Use the deck's illustrative assumption: five audits per quarter at a $7,500 fixed fee equals $150,000 in annual service revenue. The fee does not depend on a refund outcome. Close by proposing one live pilot with a broker-selected importer sample and a documented recovery-eligibility review outside the demo's calculation scope.

## Fallback

If the API or remote MCP path is unavailable, stop the panel-facing app and restart it with `ENABLE_FIXTURE_PREVIEW=true .venv/bin/streamlit run app/ui.py`. Open the **Presenter-only emergency fallback**, select **Emergency deterministic fixture preview**, and say so before running it. Show `evals/results.json` only as application regression behavior: 14 of 14 deterministic cases passed. Do not describe fixture timing, correctness, or dollars as model measurements.
