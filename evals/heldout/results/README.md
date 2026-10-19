# Historical benchmark results

These files contain measured Responses API + remote MCP results. They are not
claims of broad customs-classification accuracy: the 20 cases cover only the
three product families used by this prototype, and licensed-broker review of
the answer set remains pending.

## October 19, 2026 runs

### Initial 20-case baseline

`latest.json` records run `HIST-20261019T225927Z-3910CB3E`:

- Model: `gpt-6.1-sol`, default service tier.
- 20 evidence-eligible cases; 16 produced fully validated responses.
- 13/20 exact matches overall; 13/16 among evaluated responses.
- 36/40 successful MCP calls (90%).
- 20 API responses, 53,311 tokens, estimated cost `$0.153182`.
- p50 latency 9.443 seconds; p95 latency 12.585 seconds.

The four failures were not tunnel timeouts. In each failure the model requested
`limit_per_query: 12`, while the MCP server enforced a maximum of 8 without
publishing that maximum in the tool's input schema. The failure was retained as
evidence that the reliability grader reports infrastructure defects rather than
silently excluding them.

### Focused remediation check

`remediation-limit-schema-20261019.json` reruns only the four failed ceramic
cases after publishing JSON Schema minimum/maximum constraints:

- 4/4 exact matches and 4/4 valid citations.
- 8/8 successful MCP calls (100%).
- Estimated cost `$0.035330`.
- p50 latency 10.280 seconds; p95 latency 13.328 seconds.

### Clean post-fix 20-case run

`postfix-full-20261019.json` records run `HIST-20261019T230540Z-5CDC39FE`:

- 20/20 cases produced validated, gradable responses.
- 17/20 exact and six-digit matches (85%).
- 20/20 outputs passed mechanical citation validation.
- 40/40 expected MCP calls succeeded (100%).
- Two confident classification errors and one abstention were observed.
- No target-ruling identifier leaked into a model response.
- 57,563 tokens; estimated cost `$0.165598`.
- Mean latency 11.070 seconds; p50 9.256 seconds; p95 16.059 seconds.

Estimated costs use API-reported token categories and the OpenAI pricing page
observed on October 18, 2026. Billing records remain authoritative.
