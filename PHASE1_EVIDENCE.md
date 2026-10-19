# Phase 1 — Candidate Evidence Set

## How to read this page

This page explains how the demo scenarios were constructed before the application was implemented. Northfield Home Goods is fictional, so its product records and **declared classifications** represent made-up importer data created to demonstrate realistic audit outcomes. The **product facts** are also synthetic, but they were deliberately modeled on characteristics that mattered in real CBP rulings—for example, whether a drink container has a true vacuum, whether a plastic object is useful or merely decorative, and whether a mug is porcelain or another ceramic material.

The **proposed classifications**, tariff descriptions, and duty rates use real Harmonized Tariff Schedule (HTS) provisions that were checked against official U.S. International Trade Commission (USITC) sources. The cited CBP CROSS rulings are genuine public rulings used as analogous evidence. Because each ruling applies to its own facts, applying its reasoning to a Northfield product remains a review hypothesis for a licensed broker, not a binding legal conclusion.

The **outcome** and **why the result may change** columns are project-authored summaries. They compare the fictional declared code with the evidence-supported alternative and explain the decisive fact in plain language. Base-rate differences use Column 1 General duties only and indicate potential differences—not guaranteed refunds or complete customs liability.

**Status:** Three scenario families approved and implemented  
**Research date:** 2026-10-18  
**Rate basis:** Column 1 General base duty only. Candidate rates below were checked against the 2026 Harmonized Tariff Schedule (HTS) Revision 21 material available from the U.S. International Trade Commission (USITC) and the cited U.S. Customs and Border Protection (CBP) rulings. Before generating dated entries, the fixture builder must verify the rate against the HTS revision effective on each entry date.

The “declared” classifications below are proposed fictional importer Northfield records, not claims about an actual importer. A changed classification is a review hypothesis tied to the stated facts, not legal advice or proof of refund eligibility.

## Candidate scenario table

| Outcome | Synthetic product facts | Declared classification | Proposed classification | Base rates | Why the result may change |
|---|---|---|---|---|---|
| Potential overpayment | 16 oz stainless-steel, double-wall tumbler; supplier confirms **no vacuum** | 9617.00.1000, vacuum vessel ≤1 L | 7323.93.0080, other stainless-steel household article | 7.2% → 2.0% (5.2 percentage points) | CBP laboratory-based rulings distinguish a true sub-atmospheric vacuum vessel from a double-wall vessel with no vacuum. The draft fixture must state the no-vacuum fact explicitly. |
| Potential underpayment | Molded polyresin acorn used only as indoor decoration; no receptacle or household utility | 3924.90.5650, other plastic household article | 3926.40.0090, other plastic ornamental article | 3.4% → 5.3% (1.9 percentage points) | CBP classifies primarily ornamental polyresin articles in 3926.40 and utilitarian plastic household articles in 3924.90. |
| Needs information | Stainless-steel “insulated” tumbler described only as double-wall; no laboratory or supplier statement about vacuum pressure | 7323.93.0080 | No proposal until vacuum construction is verified; possible 7323.93.0080 or 9617.00.1000 | 2.0% or 7.2% | “Insulated” and “double-wall” do not establish a vacuum. The decisive physical fact is missing, so the system should request supplier/lab evidence rather than guess. |
| Correctly classified | HDPE planter designed to hold and grow plants around the home | 3924.90.5650 | 3924.90.5650 (unchanged) | 3.4% → 3.4% | CBP rulings consistently treat functional plastic planters as household articles. This is the false-positive guard. |
| Potential overpayment | Straight-sided ceramic mug; supplier/lab confirms non-porcelain stoneware or earthenware | 6911.10.4500, porcelain/china mug | 6912.00.4400, non-porcelain ceramic mug | 14.0% → 10.0% (4.0 percentage points) | The chapter definitions and CBP rulings make ceramic body composition decisive. The fixture must include adequate material evidence and mug-form facts. |

## Official evidence registry

### Vacuum versus non-vacuum stainless drinkware

- [CBP N224817](https://rulings.cbp.gov/ruling/N224817) — laboratory confirmed pressure below atmospheric pressure; classified under 9617.00.1000 at 7.2%.
- [CBP N241154](https://rulings.cbp.gov/ruling/N241154) — laboratory found no vacuum; classified under 7323.93.0080 at 2%.
- [CBP N321134](https://rulings.cbp.gov/ruling/N321134) — double-wall tumbler with no vacuum properties; classified under 7323.93.0080. Its 2021 ruling states Free, demonstrating why the application must use the schedule effective on the entry date rather than copying a ruling's historical rate.
- [USITC HTS Chapter 96](https://hts.usitc.gov/search?query=9617.00.1000) — 2026 Revision 21 lists 9617.00.1000 at 7.2% Column 1 General.
- [USITC HTS 7323.93](https://hts.usitc.gov/search?query=7323.93.0080) — 2026 Revision 21 lists 7323.93.00 at 2% Column 1 General.

### Utilitarian versus ornamental plastic housewares

- [CBP N328023](https://rulings.cbp.gov/ruling/N328023) — ornamental polyresin acorn under 3926.40.0090 and utilitarian polyresin planter under 3924.90.5650.
- [CBP N283412](https://rulings.cbp.gov/ruling/N283412) — functional HDPE planters under 3924.90.5650 at 3.4%.
- [CBP N321767](https://rulings.cbp.gov/ruling/N321767) — polyresin gnome statuettes under 3926.40.0090 at 5.3%.
- [CBP H296920](https://rulings.cbp.gov/ruling/H296920) — explains the household-function analysis separating heading 3924 from residual heading 3926.
- [USITC HTS 3924.90.56](https://hts.usitc.gov/search?query=3924.90.5650) — 3.4% Column 1 General.
- [USITC HTS 3926.40.00](https://hts.usitc.gov/search?query=3926.40.0090) — 5.3% Column 1 General.

### Porcelain versus other ceramic mugs

- [CBP L85060](https://rulings.cbp.gov/ruling/L85060) — porcelain mugs under 6911.10.4500 at 14%.
- [CBP N295888](https://rulings.cbp.gov/ruling/N295888) — dolomite earthenware mugs under 6912.00.4400 at 10%.
- [USITC HTS 6911.10.45 and 6912.00.44](https://hts.usitc.gov/search?query=6911.10.3710) — 2026 Revision 21 lists porcelain mugs at 14% and non-porcelain ceramic mugs at 10%; Chapter 69 Note 5 defines porcelain, stoneware, and earthenware by physical characteristics.

## Recommended approval

Approve all three families for the 12-SKU fixture, but make stainless drinkware the live-edit centerpiece. It has the clearest fact change and largest base-rate spread. Use the plastic family for the underpayment and correctly classified controls. Use the ceramic family for a second potential overpayment and a material-evidence check, not as the live edit.

## Constraints before fixture generation

1. Pin a specific HTS revision for each synthetic entry date and cache the source row; never copy a rate from a ruling without matching the entry period.
2. Give each product only facts supported by its analogous rulings. Do not imply that an analogous ruling binds a different product.
3. Keep origin-based Chapter 99 duties, trade remedies, preference programs, refund eligibility, and filing deadlines out of the calculator.
4. Do not calculate or advertise dollar differences until the synthetic values and deterministic calculator exist.
