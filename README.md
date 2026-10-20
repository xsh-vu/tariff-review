# Harbor & Crane Tariff Classification Audit Demo

Harbor & Crane is a fictional customs brokerage testing a premium tariff-audit
service for its importer client, Northfield Home Goods. Dana, a licensed customs
broker at Harbor & Crane, uses this application to identify potential base-duty
overpayments, surface underpayment exposure, request missing product facts, and
confirm classifications that do not need to change.

The demonstration is a bounded prototype built with the OpenAI Responses API,
remote MCP tools, strict Structured Outputs, deterministic duty calculations, and
explicit human approval before a local correction draft is created.

Nothing in this application is filed with CBP. Potential overpayments are screening
estimates, not guaranteed refunds. Calculations include only Column 1 General base
duties; Chapter 99 duties, trade remedies, preference programs, origin, deadlines,
and recovery eligibility are excluded.

## Five-minute demo

### Start the prepared environment

These instructions assume `.venv`, `.env`, the `harbor-crane` tunnel profile, and
the `tunnel-client` binary were configured previously. For first-time setup, see
[First-time setup](#first-time-setup).

Open three terminals in the repository root and keep all three processes running.

**Terminal 1 — local MCP server**

```bash
.venv/bin/python -m server.mcp_server
```

The local Streamable HTTP endpoint listens at `http://127.0.0.1:8000/mcp` by
default. This prototype server does not authenticate inbound requests, so keep it
on loopback and do not expose port 8000 publicly. The Secure MCP Tunnel connects
outbound to OpenAI without making the local endpoint public.

**Terminal 2 — private tunnel**

Load the runtime key from the ignored local `.env`, verify the existing profile,
and start the tunnel:

```bash
set -a
source .env
set +a
export CONTROL_PLANE_API_KEY="$OPENAI_API_KEY"
tunnel-client doctor --profile harbor-crane --explain
tunnel-client run --profile harbor-crane
```

`doctor` must pass, and `run` must remain active during the demo.

**Terminal 3 — Streamlit application**

```bash
.venv/bin/streamlit run app/ui.py
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). The page should show:

> Live workflow ready · OpenAI Responses API · remote MCP

If it does not, use the [Troubleshooting](#troubleshooting) section rather than
interpreting or describing the application as live.

### Primary demo scenario

The UI initially selects four synthetic stainless-steel drinkware SKUs. Turn on
**Run fresh review** so the walkthrough uses a new Responses API and MCP execution.
The expected evidence-backed outcomes are:

| SKU | Product fact being tested | Expected outcome | Expected classification result | Base-duty difference |
|---|---|---|---|---:|
| `NF-DW-001` | Double-walled, but supplier confirms no vacuum | Potential overpayment | `9617.00.1000` → `7323.93.0080` | **+$12,480** |
| `NF-DW-002` | Confirmed vacuum-sealed bottle | Potential underpayment—escalate | `7323.93.0080` → `9617.00.1000` | **−$6,240** |
| `NF-DW-003` | “Insulated” without evidence that a vacuum exists | Needs more information | No proposed change until the missing fact is supplied | — |
| `NF-DW-004` | Laboratory-confirmed complete vacuum flask | Classification confirmed | Remains `9617.00.1000` | $0 |

The signed difference is:

```text
duty at declared code − duty at proposed code
```

A positive amount is a potential overpayment; a negative amount is potential
underpayment exposure. The application totals them separately rather than netting
them together.

### Suggested review sequence

1. **Run the four-SKU review.** Observe the actual lifecycle events while the
   Responses API decides which read-only MCP tools to call.
2. **Inspect `NF-DW-001`.** See the proposed classification, retrieved CBP ruling
   links, and deterministic **$12,480** potential base-duty difference.
3. **Review the safeguards.** See that `NF-DW-002` is escalated as underpayment
   exposure, `NF-DW-003` is not guessed, and `NF-DW-004` is not falsely flagged.
4. **Observe human approval.** Select **Prepare correction draft** for
   `NF-DW-001`, inspect the exact pending tool arguments, and then choose **Approve
   one draft** or **Deny draft**. Approval creates only a local, unfiled draft.
5. **Observe how a product-fact change affects the review.** In the `NF-DW-003`
   result, replace the review-only description with:

   ```text
   14 oz complete stainless-steel vacuum flask with laboratory-confirmed sub-atmospheric pressure between its walls.
   ```

   Select **Rerun review with updated description for NF-DW-003**. The application
   reruns the displayed four-SKU batch with an override only for `NF-DW-003`; it
   does not alter the stored catalog. `NF-DW-003` should change from **Needs more
   information** to **Potential underpayment—escalate**, with a **−$4,160**
   difference. The four-SKU underpayment total should therefore become **−$10,400**.
6. **Open “OpenAI execution details.”** Review the current run’s response ID,
   model, tokens, latency, estimated cost, MCP event timeline, and pinned historical
   benchmark: 17/20 exact matches, 20/20 mechanically valid citations, and 40/40
   successful MCP calls.

Only live-mode measurements represent actual OpenAI API usage, latency, or model
performance.

### Optional live-readiness check

Run these checks while the MCP server and tunnel are active:

```bash
.venv/bin/pytest -q
.venv/bin/python -m scripts.live_preflight
```

The preflight makes a real one-SKU Responses API request and writes a redacted
record to `runs/live_preflight.json`. Confirm that it reports `"status": "passed"`.
It consumes API credits, so it is a deliberate readiness check rather than an
application startup requirement.

## First-time setup

### 1. Install the Python environment

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q
cp .env.example .env
```

The committed `.env.example` contains names and safe defaults only. The local
`.env` is ignored by Git and must never be committed.

### 2. Configure OpenAI and the MCP connection

Set `OPENAI_API_KEY` and `OPENAI_MODEL` in `.env`. A project service-account key is
preferred over a personal key. A service account still authenticates through its
generated secret API key, so its secret belongs in `OPENAI_API_KEY`.

Choose exactly one MCP transport:

- **Private local MCP server:** set `MCP_TUNNEL_ID` and leave `MCP_SERVER_URL` and
  `MCP_AUTH_TOKEN` blank.
- **Externally authenticated HTTPS MCP server:** set an HTTPS `MCP_SERVER_URL` and
  `MCP_AUTH_TOKEN`, and leave `MCP_TUNNEL_ID` blank. The endpoint or a gateway in
  front of it must validate that token. The application rejects configuration
  without a token, but that client-side check does not prove that the remote server
  enforces authentication.

The application places the remote MCP token in the Responses API tool’s
`authorization` field. It does not place credentials in model instructions, tool
arguments, Streamlit session caches, or UI output. The local server in
`server/mcp_server.py` does not validate bearer tokens and is intended only for
the loopback-plus-tunnel configuration. Do not put it directly behind a public URL
without adding and testing authentication at the server or gateway boundary.

### 3. Configure Secure MCP Tunnel

Create a tunnel in [OpenAI Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels),
then install the latest official
[`openai/tunnel-client`](https://github.com/openai/tunnel-client/releases/latest)
release and verify its checksum. The tunnel runtime key needs **Tunnels Read +
Use**. A tunnel creator additionally needs **Tunnels Manage**.

Download the release for the interviewer's operating system and CPU architecture,
verify its published checksum, and place the extracted executable in the local user
path. The example below is the path tested on an Intel Mac with the macOS
`x86_64`/`amd64` v0.0.16 release; use the matching artifact and extracted folder
for the machine and release being configured:

```bash
mkdir -p "$HOME/.local/bin"
install -m 755 \
  "$HOME/Downloads/tunnel-client-v0.0.16/tunnel-client" \
  "$HOME/.local/bin/tunnel-client"
command -v tunnel-client
tunnel-client help quickstart
```

`command -v` should print `$HOME/.local/bin/tunnel-client`. This repository's
tested shell configuration already includes `$HOME/.local/bin` in `PATH`. If a
different terminal does not, add `export PATH="$HOME/.local/bin:$PATH"` to
`~/.zshrc`, then open a new terminal or run `source ~/.zshrc`.

With `MCP_TUNNEL_ID` and `OPENAI_API_KEY` populated in `.env`, start the local MCP
server in another terminal, then create the profile once:

```bash
set -a
source .env
set +a
export CONTROL_PLANE_API_KEY="$OPENAI_API_KEY"
tunnel-client init \
  --sample sample_mcp_remote_no_auth \
  --profile harbor-crane \
  --tunnel-id "$MCP_TUNNEL_ID" \
  --mcp-server-url http://127.0.0.1:8000/mcp \
  --control-plane-api-key-ref env:CONTROL_PLANE_API_KEY
tunnel-client doctor --profile harbor-crane --explain
```

`init` creates `~/.config/tunnel-client/harbor-crane.yaml`; it is a one-time step
for each machine. Do not create or edit that profile by hand. After `doctor` ends
with `RESULT pass`, start the foreground daemon and leave it running:

```bash
tunnel-client run --profile harbor-crane
```

The CLI may print a generic note about creating a ChatGPT connector. That is not
required for this application: the Responses API connects by using `MCP_TUNNEL_ID`
from `.env`.

The prototype may use one narrowly scoped service-account key for Responses and
the tunnel runtime. A production deployment should separate credentials and add
formal acquisition, rotation, revocation, and secret-storage controls.

## What the live workflow implements

The review imports only four read-only MCP tools:

- `get_catalog`
- `get_entries`
- `search_hts_batch`
- `search_rulings_batch`

Ruling search returns full bounded records, including ruling IDs and official
source URLs. The model response uses strict `text.format` JSON Schema. Application
code then validates SKU coverage, tariff codes, retrieved citation IDs, and outcome
semantics before calculating financial differences deterministically.

The UI streams observed Responses API and MCP lifecycle events. During quiet
periods it emits a four-second waiting heartbeat without claiming unobserved work.
A validated MCP tool-discovery record may be reused for 30 minutes in the same
Streamlit session when the server identity and tool policy match. That discovery
cache contains schemas—not credentials, product records, tool results, or model
conclusions.

Separately, an exact validated tariff-review result may be reused for 30 minutes
when the selected SKU batch, description overrides, model, schema, code, evidence,
and MCP configuration are unchanged. The UI labels a result-cache hit and reports
zero incremental OpenAI requests, MCP calls, and API cost. Select **Run fresh
review** to bypass it. Failed reviews, approval state, and drafts are never cached.

Correction drafting uses a separate one-tool MCP policy. The Responses API pauses
on an `mcp_approval_request`; the UI displays the proposed tool and arguments; and
the user’s decision is continued with an `mcp_approval_response`. The MCP server
also requires a matching, current, single-use application approval token. Neither
approval path files anything externally.

These integration choices follow the official OpenAI documentation for
[remote MCP tools and approvals](https://developers.openai.com/api/docs/guides/tools-connectors-mcp),
[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels),
and [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## Evaluation evidence

### Application regression suite

```bash
.venv/bin/python -m evals.run
```

This writes `evals/results.json`. It exercises deterministic workflow behavior and
must not be described as model accuracy, API latency, or API cost.

### Focused live workflow evaluation

```bash
.venv/bin/python -m evals.live
```

This writes `evals/live_results.json` and covers the four primary demo outcomes,
the description edit, remote MCP use, and strict Structured Outputs. It uses
synthetic Northfield scenarios rather than independent historical rulings.

Every invocation replaces `evals/live_results.json`, including an invocation that
fails because credentials, the MCP server, or the tunnel are unavailable. Copy a
result to a separately named file before rerunning if it must be preserved as dated
evidence. A passing prior file must never be presented as the outcome of a newer
failed run.

### Historical CBP CROSS benchmark

```bash
.venv/bin/python -m evals.heldout.validate
.venv/bin/python -m evals.heldout.run --preflight-only
.venv/bin/python -m evals.heldout.run \
  --output evals/heldout/results/<dated-result>.json
```

The runner loads only sanitized product descriptions and case dates before model
execution. It allows two read-only historical-evidence MCP tools, persists raw
responses, and loads the hidden answer key only afterward for deterministic grading.
See [`evals/heldout/README.md`](evals/heldout/README.md) for the methodology.

The application displays the explicitly pinned clean post-fix result
`evals/heldout/results/postfix-full-20261019.json`; it does not treat `latest.json`
as an alias for the best run. The retained `latest.json` baseline includes four
tool-schema failures and is kept to show that the reliability grader records MCP
failures instead of silently excluding them.

The clean October 19, 2026 `gpt-6.1-sol` run produced:

- 17/20 exact and six-digit matches (85%)
- 20/20 mechanically valid citations
- 40/40 successful MCP calls
- 57,563 tokens
- 9.256-second p50 and 16.059-second p95 latency
- `$0.165598` estimated API cost at the dated published-rate basis

These are selected-case prototype results across three product families—not broad
customs-classification accuracy. Mechanical citation validity means that each cited
identifier was retrieved through MCP; it does not prove that every legal analogy was
persuasive. Licensed-broker review and repeated candidate-model comparisons remain
future work. See [`evals/heldout/results/README.md`](evals/heldout/results/README.md)
for the failure-bearing baseline, remediation run, and clean post-fix result.

## Presenter-only emergency fallback

The normal UI never silently falls back from OpenAI to local logic. If live service
is unavailable and an explicitly disclosed local product-behavior preview is still
useful, start Streamlit with:

```bash
ENABLE_FIXTURE_PREVIEW=true .venv/bin/streamlit run app/ui.py
```

Select **Emergency deterministic fixture preview** in the disclosed fallback
control. The UI labels it as local deterministic behavior. Do not interpret its
results, timing, or correctness as an OpenAI execution.

## Troubleshooting

| Symptom | Check |
|---|---|
| Live review is disabled | Confirm `.env` contains `OPENAI_API_KEY`, `OPENAI_MODEL`, and exactly one of `MCP_TUNNEL_ID` or authenticated HTTPS `MCP_SERVER_URL`. Restart Streamlit after changing `.env`. |
| `zsh: command not found: tunnel-client` | Install the extracted executable into `$HOME/.local/bin` as shown above, confirm that directory is in `PATH`, then open a new terminal and run `command -v tunnel-client`. |
| `profile_load FAIL` or `harbor-crane.yaml: no such file` | The tunnel profile has not been initialized on this machine. Run the one-time `tunnel-client init` command in **Configure Secure MCP Tunnel**, then rerun `doctor`. |
| MCP server reports `address already in use` on `127.0.0.1:8000` | Another MCP server is already listening. Run `lsof -nP -iTCP:8000 -sTCP:LISTEN`. Reuse it if its command is this repository's `.venv/bin/python -m server.mcp_server`; otherwise stop the identified process with `kill -TERM <PID>` and start the server again. |
| MCP discovery or a tool call fails | Confirm the local MCP server is still running, confirm `tunnel-client run` is connected, and rerun `tunnel-client doctor --profile harbor-crane --explain`. |
| `ModuleNotFoundError` when launching | Run commands from the repository root and use `.venv/bin/streamlit run app/ui.py`. |
| Review appears not to make a new call | The exact batch may have hit the 30-minute session result cache. Check the cache notice or select **Run fresh review**. |
| Review stops safely | Read the expanded progress log. The application intentionally rejects tool errors, missing evidence, invalid citations, unsupported codes, incomplete output, or inconsistent calculations. |
| API reports billing or authorization failure | Verify the project, service-account permissions, API credits, and tunnel permissions in OpenAI Platform. Do not substitute fixture measurements for a failed live run. |

## Shutdown and restart

Each demo process runs in the foreground. Press `Control-C` once in its terminal to
stop Streamlit, `tunnel-client`, or the MCP server cleanly. On the next demo run,
start them again in this order:

1. `.venv/bin/python -m server.mcp_server`
2. `tunnel-client doctor --profile harbor-crane --explain`, followed by
   `tunnel-client run --profile harbor-crane`
3. `.venv/bin/streamlit run app/ui.py`

Do not run a second copy of a service on the same port. Use the `lsof` command in
Troubleshooting when a previous terminal was closed without stopping its process.

## Repository guide

- [`PROJECT.md`](PROJECT.md) — customer, business objective, scope, and success criteria
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — data flow, trust boundaries, API/MCP design, and tradeoffs
- [`PHASE1_EVIDENCE.md`](PHASE1_EVIDENCE.md) — scenario evidence, source provenance, and classification rationale
- [`LIVE_VALIDATION.md`](LIVE_VALIDATION.md) — dated live metrics, integration failures, and rehearsal record
- [`TODO.md`](TODO.md) — implementation phases and acceptance checklist
- [`evals/heldout/README.md`](evals/heldout/README.md) — historical-case selection and evaluation method

The customer and entry records are synthetic. HTS lines and CBP ruling links are
bounded, dated fixtures based on official public sources. Entry dates are fixed to
the supported 2026 HTS revision observation date; unsupported historical dates fail
instead of silently using a current rate.
