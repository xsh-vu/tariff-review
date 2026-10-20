# Live Validation Record

**Initial validation date:** 2026-10-18

**Latest added run:** 2026-10-20

**Environment:** OpenAI Responses API, GPT-6.1 Sol, default service tier, authenticated Secure MCP Tunnel, local Streamable HTTP MCP server  
**Pricing basis:** Published OpenAI standard short-context rates observed 2026-10-18; billing records remain authoritative.

This record reports actual runs. The cases and entry values are synthetic, and the evaluation is a focused workflow check rather than an independent legal-accuracy benchmark.

## Authenticated preflight

The successful one-SKU preflight proved OpenAI-hosted discovery and invocation of the private MCP server together with strict Structured Outputs.

| Measure | Actual result |
|---|---:|
| Status | Passed, 7/7 checks |
| Response ID | `resp_0107c156127b660b006ad527c9706087d1a0f742e2bfd27070` |
| Model | `gpt-6.1-sol` |
| Total tokens | 3,038 |
| API latency | 26.563 seconds |
| End-to-end preflight time | 26.620 seconds |
| Estimated API cost | $0.012512 |
| Expected finding | `NF-DW-001` potential overpayment; proposed `7323.93.0080` |
| Deterministic potential difference | $12,480.00 |

The response discovered the approved tool inventory and successfully called product, entry, HTS, ruling-search, and ruling-detail tools through the tunnel.

## Focused live evaluation

The final evaluation passed all six checks:

1. Evidence-backed potential overpayment.
2. Underpayment routed as compliance exposure.
3. Missing-information abstention.
4. Correct classification left unchanged.
5. Broker-entered description edit changed the review to the expected underpayment outcome.
6. Secure MCP Tunnel calls and strict Structured Outputs were present.

| Measure | Actual result |
|---|---:|
| Status | Passed, 6/6 checks |
| Responses | `resp_0058a2c10e8ed717006ad52892d26c87d1bee9cca9695d8cfc`, `resp_01b468b5cd211fff006ad528bb7c8887d1a5998cf1ddc291b0` |
| Total tokens | 8,455 |
| Aggregate API latency | 71.462 seconds |
| End-to-end evaluation time | 71.525 seconds |
| Estimated API cost | $0.035618 |
| Potential overpayment total | $12,480.00 |
| Underpayment exposure total | $6,240.00 |

## Four-SKU live performance check

On 2026-10-20, a fresh four-SKU Responses API review completed within the
20-second target at an estimated cost of approximately one cent. The run reused
the validated `mcp_list_tools` discovery item, matching the normal warm-session
demo behavior, but it did not reuse a product result, evidence result, or prior
model conclusion. All four read-only MCP tools executed again.

| Measure | Actual result |
|---|---:|
| Status | Passed; all four expected outcomes returned |
| Run ID | `RUN-11EDB47495` |
| Response ID | `resp_0f3ac44bf2e22fb9006ad7a5aa87f487d1b71fa0b9e08a8151` |
| Model / service tier | `gpt-6.1-sol` / default |
| Total tokens | 3,639 |
| Input / output tokens | 2,900 / 739 |
| API latency | 15.147 seconds |
| Estimated API cost | $0.011122 (1.1122 cents) |
| MCP discovery reused | Yes; validated tool schemas only |
| MCP calls | 4/4 successful: catalog, entries, batched HTS, batched rulings |
| Structured Output | Validated |
| Potential overpayment total | $12,480.00 |
| Underpayment exposure total | $6,240.00 |

The immediately preceding cold-session control also passed functionally but took
20.879 seconds, so it did not meet the under-20-second criterion. It used 3,524
tokens and had an estimated API cost of $0.010811. This distinction prevents the
warm-session result from being presented as cold-start performance.

## Approval continuation and rehearsal

The UI displayed the exact proposed `draft_correction` arguments and hid the single-use token. The human explicitly approved one local draft. The successful continuation used `previous_response_id`, an `mcp_approval_response`, and the MCP tool definition as required by the official OpenAI approval example.

| Measure | Actual result |
|---|---:|
| Timed workflow | 216 seconds (3:36) |
| Review response | `resp_083cd1874f7db72d006ad52913f7b887d1a053a81ba2a0c372` |
| Review tokens / latency / estimated cost | 5,415 / 52.148 s / $0.023422 |
| Continuation response | `resp_0bb0eb54876b7d52006ad529dcf86087d1a67624ec17d7bda8` |
| Continuation tokens / latency / estimated cost | 1,150 / 5.077 s / $0.003452 |
| Draft | `DRAFT-1C89864C7E` |
| Stored state | `status: draft_only`; `not_filed: true` |
| Approval ledger | One token consumed; raw token not stored in the draft |

The review and continuation figures above exclude the approval-request response and the rejected continuation attempt, whose usage was not returned to the application. They must not be presented as the complete rehearsal cost.

## Failures observed

| Stage | Observed failure | Safe outcome | Resolution |
|---|---|---|---|
| First preflight | `credit_balance_exhausted` after 6.853 seconds | No model response or draft | Organization credits added; preflight rerun |
| First live evaluation | 5/6 checks; edited description remained `needs_info` | No false classification was forced | Routed overrides through `get_catalog` and required exact override use; 20 tests passed before rerun |
| First approved continuation | MCP server not enabled on the continuation request | No draft created; approved token remained unconsumed | Re-sent the MCP tool definition, matching the official documentation; exact approved action retried |

## Verification

- `python -m pytest -q`: 20 passed.
- Python compilation check: passed.
- Deterministic evaluation: 14/14.
- Focused live evaluation: 6/6.
- Private tunnel readiness: passed.
- Approved correction-draft write: exactly one local draft, explicitly unfiled.

Official integration references:

- [MCP servers and approval handling](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)
- [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI API pricing](https://developers.openai.com/api/docs/pricing)
