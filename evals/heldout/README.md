# Held-out CBP CROSS evaluation set

This directory contains 20 historical classification cases derived from official
U.S. Customs and Border Protection CROSS rulings. It is designed to evaluate
classification generalization separately from the application's searchable
ruling corpus.

## Separation

- `cases.json` contains only sanitized product facts and case dates. It contains
  no ruling identifiers, official source links, expected HTSUS codes, duty
  rates, or holdings.
- `answer_key.json` contains the private gold labels and official provenance. It
  must be loaded only by the evaluator after a model response is complete.
- Neither file is loaded by `data.repository.Repository` or exposed through the
  MCP ruling tools.
- `validate.py` fails if a held-out ruling appears in
  `data/source_data/rulings.json` or if an expected ruling ID or HTSUS code leaks
  into `cases.json`.

## Review performed

On 2026-10-18, every case was manually compared with its official CBP CROSS API
record for:

1. Product facts material to the classification.
2. Ruling date and base HTSUS holding.
3. Base Column 1 General rate stated in the ruling, when present.
4. `operationallyRevoked`, `modifiedBy`, and `revokedBy` status fields.
5. Absence from the application's nine-ruling searchable evidence cache.

This is an independent source-verification review performed for the prototype.
It is **not** review by a licensed customs broker, a legal opinion, or evidence
that the current model classifies these cases correctly. Broker review remains
pending.

Run the offline integrity checks with:

```bash
python -m evals.heldout.validate
```

Recheck all records against the live official CBP API with:

```bash
python -m evals.heldout.validate --verify-live
```

## Case inventory

| Case | Family | CROSS ruling | Date | Historical base HTSUS answer |
|---|---|---|---|---|
| PR-DW-001 | Stainless drinkware | [N356922](https://rulings.cbp.gov/ruling/N356922) | 2026-01-28 | 9617.00.1000 |
| PR-DW-002 | Stainless drinkware | [N349684](https://rulings.cbp.gov/ruling/N349684) | 2025-09-25 | 9617.00.1000 |
| PR-DW-003 | Stainless drinkware | [962648](https://rulings.cbp.gov/ruling/962648) | 1999-11-09 | 9617.00.10 |
| PR-DW-004 | Stainless drinkware | [N218293](https://rulings.cbp.gov/ruling/N218293) | 2012-08-31 | 7323.93.0080 |
| PR-DW-005 | Stainless drinkware | [N269864](https://rulings.cbp.gov/ruling/N269864) | 2015-11-17 | 7323.93.0080 |
| PR-DW-006 | Stainless drinkware | [N297166](https://rulings.cbp.gov/ruling/N297166) | 2018-06-13 | 7323.93.0080 |
| PR-DW-007 | Stainless drinkware | [N357245](https://rulings.cbp.gov/ruling/N357245) | 2026-07-14 | 9617.00.1000 |
| PR-PL-001 | Plastic housewares | [N338807](https://rulings.cbp.gov/ruling/N338807) | 2024-03-29 | 3924.90.5650 |
| PR-PL-002 | Plastic housewares | [N302665](https://rulings.cbp.gov/ruling/N302665) | 2019-02-22 | 3924.90.5650 |
| PR-PL-003 | Plastic housewares | [N289553](https://rulings.cbp.gov/ruling/N289553) | 2017-09-19 | 3924.90.5650 |
| PR-PL-004 | Plastic housewares | [N277216](https://rulings.cbp.gov/ruling/N277216) | 2016-08-03 | 3924.90.5650 |
| PR-PL-005 | Plastic housewares | [N173957](https://rulings.cbp.gov/ruling/N173957) | 2011-07-28 | 3924.90.5650 |
| PR-PL-006 | Plastic housewares | [N277786](https://rulings.cbp.gov/ruling/N277786) | 2016-08-23 | 3926.40.0090 |
| PR-PL-007 | Plastic housewares | [N267258](https://rulings.cbp.gov/ruling/N267258) | 2015-08-25 | 3926.40.0090 |
| PR-CE-001 | Ceramic drinkware | [N347310](https://rulings.cbp.gov/ruling/N347310) | 2025-04-22 | 6911.10.8010 |
| PR-CE-002 | Ceramic drinkware | [N276348](https://rulings.cbp.gov/ruling/N276348) | 2016-07-06 | 6911.10.2500 |
| PR-CE-003 | Ceramic drinkware | [N262709](https://rulings.cbp.gov/ruling/N262709) | 2015-04-14 | 6912.00.4400 |
| PR-CE-004 | Ceramic drinkware | [N326579](https://rulings.cbp.gov/ruling/N326579) | 2022-06-10 | 6912.00.4500 |
| PR-CE-005 | Ceramic drinkware | [N323611](https://rulings.cbp.gov/ruling/N323611) | 2022-01-20 | 6912.00.4810 |
| PR-CE-006 | Ceramic drinkware | [N360981](https://rulings.cbp.gov/ruling/N360981) | 2026-05-19 | 6912.00.4500 |

## Scoring guidance

Report at least two classification scores:

- Exact match against the ruling-date base code.
- Six-digit subheading match, which is less sensitive to historical statistical
  suffix changes.

Score abstentions separately. Do not give the model the target ruling, its
identifier, this README, or `answer_key.json`. Permitted evidence may include
the applicable historical HTSUS text and genuinely analogous rulings from the
searchable corpus. Log which evidence was actually retrieved.

Run models repeatedly and report sample size, pass counts, latency, tokens,
cost, and failures. Do not characterize results on these 20 selected cases as a
broad estimate of customs-classification accuracy.

## Limitations

- The set is deliberately limited to the demo's three product families.
- CROSS rulings apply to their specific facts; they are not universal legal
  rules for other importers or merchandise.
- Historical decisions may reflect the tariff schedule and interpretive posture
  in effect on the ruling date. PR-DW-006 is intentionally retained as a
  temporal challenge because its 2018 partial-vacuum outcome differs from some
  later vacuum-vessel outcomes.
- Chapter 99 duties, conditional special programs such as 9817, origin,
  valuation, admissibility, and refund eligibility are outside the scoring
  target.
- The selected examples are not a random sample of all CROSS rulings.

