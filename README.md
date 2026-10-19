# Harbor & Crane Tariff Classification Audit Demo

This repository implements a bounded vertical slice for a premium tariff audit of 12 synthetic Northfield Home Goods SKUs. It uses verified CBP CROSS links, a versioned six-line HTS rate fixture, deterministic base-duty calculations, strict model output validation, and explicit broker approval before a local correction draft.

No workflow files with CBP. Potential overpayments are screening estimates, not guaranteed refunds. Only Column 1 General base duties are in scope.

## Quick start

Requires Python 3.11 or newer.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q
.venv/bin/streamlit run app/ui.py
```

The panel-facing UI defaults to the live Responses API + MCP workflow. If live
configuration is unavailable, the review action is disabled rather than silently
falling back to local logic.

The deterministic fixture implementation remains available for development,
regression testing, and an explicitly disclosed presentation emergency. It is
hidden by default. To expose the presenter-only fallback, start Streamlit with:

```bash
ENABLE_FIXTURE_PREVIEW=true .venv/bin/streamlit run app/ui.py
```

The fallback is visibly labeled as local deterministic behavior and must not be
presented as an OpenAI API result.

## Live Responses API + MCP mode

Copy `.env.example` to `.env` and set `OPENAI_API_KEY`, `OPENAI_MODEL`, and exactly one of:

- `MCP_TUNNEL_ID` for a private/local server exposed through Secure MCP Tunnel; or
- `MCP_SERVER_URL` for a remotely reachable Streamable HTTP endpoint.

For an authenticated remote endpoint, set `MCP_AUTH_TOKEN`. The server-side application passes that token in the MCP tool's `authorization` field; it is never put in prompts, tool arguments, or UI output. A production service must acquire, refresh, revoke, and securely store OAuth tokens outside this demo.

Prefer a project service-account key over a personal key. A service account still
authenticates through its generated secret API key, so place that value in
`OPENAI_API_KEY`. The local `.env` is ignored by version control. Give the key only
the permissions needed for Responses and tunnel operation, set an expiration date,
and rotate or revoke it after the demo.

Run the local Streamable HTTP MCP server:

```bash
.venv/bin/python -m server.mcp_server
```

The endpoint is `/mcp` by default. Keep `MCP_HOST=127.0.0.1` when using a private tunnel. Do not expose this unauthenticated prototype directly to the public internet.

For the private-tunnel path, install the official
[`openai/tunnel-client`](https://github.com/openai/tunnel-client/releases) and
verify the release checksum. The tested setup used v0.0.16. With the local MCP
server running, create and validate a profile, then keep the tunnel daemon
running:

```bash
tunnel-client init \
  --sample sample_mcp_remote_no_auth \
  --profile harbor-crane \
  --tunnel-id "$MCP_TUNNEL_ID" \
  --mcp-server-url http://127.0.0.1:8000/mcp \
  --control-plane-api-key-ref env:OPENAI_API_KEY
tunnel-client doctor --profile harbor-crane --explain
tunnel-client run --profile harbor-crane
```

The runtime-key principal needs Tunnels Read + Use. The tunnel daemon and the
Responses API may use the same narrowly scoped service-account key for this
prototype; production deployments should separate credentials where practical.

Then run the UI:

```bash
.venv/bin/streamlit run app/ui.py
```

Live review calls use a five-tool evidence-only `allowed_tools` policy, one batched catalog lookup, one batched entry lookup, compact strict `text.format` JSON Schema output, and deterministic post-validation and duty calculation in application code. A validated `mcp_list_tools` item may be reused for five minutes within the same UI session and exact review policy; prior product data and review results are not carried forward. The draft workflow uses a separate one-tool policy, pauses on one `mcp_approval_request`, displays the exact arguments, and continues with an `mcp_approval_response`. The MCP server also requires a matching, single-use local approval token before it writes a draft.

### Live gate

Keep the MCP server and `tunnel-client` running, then execute the authenticated
one-SKU preflight:

```bash
.venv/bin/python -m scripts.live_preflight
```

The preflight writes a redacted `runs/live_preflight.json` only after attempting
the real Responses API path. It verifies MCP tool discovery and calls, strict
Structured Outputs, the expected classification, response metadata, and a dated
cost estimate. A failed preflight is also recorded and displayed in the UI. On
2026-10-18, the first authenticated attempt reached the API but failed safely
with `credit_balance_exhausted`; no response or usage metrics are claimed for that
attempt.

Run the focused live evaluation next:

```bash
.venv/bin/python -m evals.live
```

This records `evals/live_results.json`, which the Streamlit UI displays alongside
the clearly separated application regression results. The live evaluation covers
the four demo outcomes plus the product-description edit. It is still a synthetic
workflow evaluation, not an independent held-out legal benchmark.

The 2026-10-18 validation passed 6/6 focused checks with 8,455 tokens, 71.462
seconds of aggregate API latency, and a $0.035618 published-rate cost estimate.
See [`LIVE_VALIDATION.md`](LIVE_VALIDATION.md) for response IDs, the timed
approval rehearsal, and the failures observed during integration.

## Evaluation

```bash
.venv/bin/python -m evals.run
.venv/bin/python -m evals.heldout.validate
```

This writes `evals/results.json`. Until live credentials and a reachable MCP path are configured, these results measure only deterministic fixture behavior. They do not claim model correctness, API latency, token use, or cost.

The second command validates the 20-case historical CBP CROSS held-out set,
including answer isolation and zero overlap with the searchable ruling cache.
See [`evals/heldout/README.md`](evals/heldout/README.md) for methodology,
official sources, limitations, and the optional live CBP status check. The set
has not yet been run against a model, and licensed-broker review remains
pending.

## Demo path

1. Review `NF-DW-001` through `NF-DW-004` to show an overpayment, underpayment escalation, missing-information abstention, and a correct classification.
2. Inspect official ruling links and the deterministic $12,480 potential base-duty difference on `NF-DW-001`.
3. Prepare a draft, inspect the exact arguments, then approve or deny it. The result remains a local, unfiled draft.
4. Edit `NF-DW-003` to state that laboratory testing confirms a vacuum and rerun that SKU; it changes from `needs_info` to potential underpayment exposure.
5. Show measured execution metadata. Only live mode may be presented as OpenAI API usage or latency.

## Evidence and scope

- [PROJECT.md](PROJECT.md) — product objective and scope
- [ARCHITECTURE.md](ARCHITECTURE.md) — trust boundaries and API/MCP design
- [PHASE1_EVIDENCE.md](PHASE1_EVIDENCE.md) — approved scenario evidence table
- [TODO.md](TODO.md) — phased implementation checklist
- [LIVE_VALIDATION.md](LIVE_VALIDATION.md) — dated live metrics, failures, and rehearsal record
- [presentation/harbor-crane-tariff-audit-demo-v2.pptx](presentation/harbor-crane-tariff-audit-demo-v2.pptx) — presentation deck
- [presentation/DEMO_RUNBOOK.md](presentation/DEMO_RUNBOOK.md) — timed five-minute demonstration script

The legal cache is intentionally narrow. Entry dates are fixed to the verified 2026 HTS revision observation date; unsupported historical dates fail instead of silently applying a current rate.
