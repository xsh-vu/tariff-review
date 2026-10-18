# PROJECT.md — Tariff Classification Review

**Status:** Authenticated Responses API + private MCP tunnel vertical slice validated end to end — v0.6  
**Project type:** OpenAI Applied AI technical take-home  
**Selected product surface:** OpenAI Platform and APIs  
**Primary technology:** OpenAI Responses API + MCP  
**Data:** Synthetic customer records and public customs sources

> **Working document:** This file captures current product intent and proposed implementation. It is not an instruction to build every feature at once. Validate legal examples, API details, assumptions, and scope before implementation. `AGENTS.md` governs how Codex should work; `ARCHITECTURE.md` records confirmed technical decisions.

## 1. Executive summary

Harbor & Crane is a fictional mid-sized licensed customs brokerage serving approximately 150 importer clients. It wants to launch a **premium, proactive tariff classification audit service** for existing customers, rather than offering only transactional customs clearance and conventional compliance support.

Its specialists examine whether importers' products were assigned appropriate Harmonized Tariff Schedule (HTS) codes. Incorrect classifications can result in excess duty payments, underpayment exposure, and expensive manual investigations. Comprehensive re-reviews are research-intensive and difficult to deliver economically across many clients.

The proposed **Tariff Classification Review Agent** uses OpenAI Platform and APIs to review existing classifications, identify potential base-duty overpayments, quantify financial differences, and prepare evidence-backed recommendations for a licensed broker.

**Primary commercial value for Harbor & Crane:** Create incremental revenue from premium classification audit services, with improved delivery economics through AI-assisted review.

**Primary value for importers:** Discover potential duty recovery opportunities that may otherwise remain unidentified.

**Trust differentiator:** Recommendations are supported by authoritative tariff provisions, analogous CBP rulings, deterministic calculations, explicit uncertainty, and human approval.

The application does not guarantee refund eligibility, autonomously make legally binding classification decisions, or submit customs filings.

## 2. Customer, users, and business model

### Customer: Harbor & Crane

- **Industry:** Customs brokerage and trade compliance
- **Business model:** Customs clearance, classification, and compliance services for importers; proposed premium audit offering
- **Scale:** Approximately 150 importer clients (fictional assumption)
- **Economic buyer:** Head of Compliance, with potential commercial sponsorship from brokerage leadership
- **Primary user:** Dana, a licensed customs broker and classification lead
- **Demo client:** Northfield Home Goods, a fictional housewares importer with 12 synthetic SKUs

### Current user problem

Dana's team reviews supplier product descriptions, declared HTS codes, applicable legal notes, CBP rulings, and historical entry records to determine whether classifications warrant correction. This takes specialized judgment and substantial research. The brokerage cannot continuously review every client's catalog at the same depth.

### Proposed premium service

Harbor & Crane offers periodic, proactive tariff classification audits to importer clients. The service surfaces potential overpayments, investigates discrepancies, flags underpayment exposure, and delivers broker-reviewed findings and recommended next steps.

**Initial commercial hypothesis:** A fixed-fee annual audit priced according to catalog complexity and review scope. This avoids assuming that Harbor & Crane receives a share of refunds or that a calculated duty difference is recoverable. Pricing and customer willingness to pay are unvalidated.

### Value for Harbor & Crane

1. **Incremental revenue:** Monetize proactive classification audits as a premium service.
2. **Improved unit economics:** Reduce the research effort and cost of delivering each audit, while retaining expert review.
3. **Customer differentiation:** Offer proactive financial insights rather than only transactional customs clearance.
4. **Expansion potential:** Offer the service across the existing importer client base.

### Value for importer clients

- Identify potential duty recovery opportunities.
- Detect underpayment exposure and route it for appropriate review.
- Receive transparent, evidence-backed recommendations.
- Reduce the effort needed to investigate historical classifications.

## 3. Business problem and opportunity

### Current workflow

1. A broker selects an importer and reviews its product catalog.
2. The broker checks product descriptions and declared HTS codes.
3. The broker researches tariff provisions, section/chapter notes, and CBP rulings.
4. The broker determines which classifications warrant investigation.
5. Historical entries are analyzed to estimate duty differences.
6. The broker recommends further evidence gathering or corrective action.

This process is research-intensive, difficult to scale, and dependent on experienced classification specialists.

### Improved workflow

The agent conducts an initial evidence-backed review, prioritizes potentially material discrepancies, and calculates base-duty differences. Dana evaluates the findings and decides whether to request more information, investigate further, or approve a correction **draft**. Nothing is filed automatically.

### Critical financial distinction

A positive historical base-duty difference is **not** necessarily a legally recoverable refund. Eligibility depends on entry status, deadlines, procedures, applicable duties, and legal review. Present financial findings as **potential base-duty differences**, not guaranteed recovery.

## 4. Product objective and success metrics

### Primary business objective

Enable Harbor & Crane to launch a scalable, premium tariff classification audit service for its importer clients.

### Commercial success metrics

1. Incremental annual audit revenue.
2. Gross margin per completed audit.
3. Number and percentage of clients adopting the service.
4. Broker review hours per audit.
5. Potential duty overpayments identified for importer clients.

### Operational and quality metrics

- Review time per SKU, including human verification.
- Model/API cost per review.
- Classification correctness on a small, independently checked set of public ruling examples and workflow fixtures.
- Evidence/citation validity.
- False-correction rate.
- Appropriate underpayment escalation and abstention when facts are missing.
- Broker agreement rate during a future pilot.

Clearly distinguish **measured results**, **synthetic scenario values**, and **commercial projections**.

### Illustrative commercial scenario (not validated)

If 30 of Harbor & Crane's 150 importer clients purchase one $5,000 audit annually, the offering would generate **$150,000 in annual gross audit revenue**. This assumes 20% adoption and does **not** represent profit, validated pricing, or a revenue forecast. Broker labor, implementation, legal review, hosting, and customer acquisition costs must be included to estimate gross margin.

Do not treat this scenario as the demo's primary headline. Lead with the importer's potential base-duty savings and use brokerage economics to explain why Harbor & Crane would offer the service.

## 5. Target workflow

### Trigger

Dana selects Northfield Home Goods and initiates a classification review.

### Proposed agent workflow

1. Retrieve product descriptions and declared HTS classifications.
2. Search applicable HTS provisions and section/chapter legal notes.
3. Retrieve analogous CBP classification rulings.
4. Evaluate whether each declared classification is supported; apply relevant General Rules of Interpretation.
5. Propose a different classification where evidence supports one, or request missing information.
6. Calculate historical base-duty differences using deterministic rate lookups.
7. Produce a prioritized set of overpayment opportunities, underpayment exposures, unresolved cases, and confirmed classifications.
8. Present evidence and proposed actions for Dana's review.
9. Prepare a correction draft only after the required human approval.

### Finding details

- SKU and product description.
- Declared and proposed HTS code, when applicable.
- Classification rationale and deciding rule.
- Relevant legal notes and retrieved CBP rulings, with verifiable references.
- Historical entered value and affected entries.
- Calculated base-duty difference.
- Outcome: potential overpayment, potential underpayment, needs information, or confirmed.
- Recommended next action and routing (broker, counsel, or supplier).

## 6. Demo narrative and aha moment

### Central story

**An importer may have paid more duties than necessary, but discovering and substantiating those opportunities manually is expensive.** Harbor & Crane can offer proactive audits as a premium service because AI-assisted review makes the work more scalable.

### Demo headline

**Potential duty recovery is the business hook. Evidence, risk detection, and human oversight are why the result is trustworthy.**

### Planned synthetic findings

The five-hour build starts with 12 synthetic SKUs across only 2–3 legally verified classification scenarios. The set must contain at least one potential overpayment, one potential underpayment routed for compliance review, one missing-information case, and one correctly classified case that remains unchanged. These are planned fixture outcomes until implementation and evaluation produce measured results.

The evidence corpus targets 6–10 verified CBP CROSS rulings; four is the minimum acceptable number if research is time-consuming. Breadth is subordinate to a complete, reliable vertical slice.

### Interactive demonstration

Edit a material attribute in a product description (for example, stoneware versus porcelain), rerun the review for that SKU, and show whether the classification recommendation and duty calculation change appropriately. Select a scenario only after validating real HTS provisions, supporting rulings, and rate differences. Do not force a change where the legal classification does not support one.

### Presentation principle

The live demo should lead with **the potential base-duty difference identified for Northfield**, supported by actual synthetic entry arithmetic. The final business-value slide should explain the brokerage's premium-audit revenue opportunity and delivery economics. Avoid introducing both commercial models before demonstrating the product.

## 7. Selected OpenAI product surface

**OpenAI Platform and APIs** is the only product surface being demonstrated.

- **Responses API:** Model reasoning and tool orchestration.
- **MCP:** Access to simulated brokerage records, public tariff provisions, CBP rulings, and deterministic calculation tools.
- **Application UI:** A lightweight interface for the broker's review workflow.

Codex may be used to build the application but is **not** the product surface being demonstrated.

### Why this surface

The brokerage needs a workflow embedded in its own systems, with programmatic access to customer data, authoritative sources, calculations, structured findings, and approval controls. A custom application using OpenAI Platform and APIs supports this integration and governance model.

## 8. Proposed technical architecture

The initial design follows the attached *Tariff Classification Review — Build Plan*, subject to validation and scope reduction.

- **Application:** Python orchestration with a lightweight Streamlit UI.
- **Model interface:** OpenAI Responses API using the official SDK.
- **Tool integration:** Authenticated remote MCP server.
- **Legal data:** Dated, cached public USITC HTS provisions and CBP CROSS rulings.
- **Customer data:** Synthetic catalog and historical entry records.
- **Financial calculations:** Deterministic Python rate lookup and duty-delta calculator.
- **Output:** Structured findings, separate overpayment/underpayment totals, approved correction drafts, and audit logs.
- **Evaluation:** Held-out rulings and reproducible workflow scenarios.

### Architecture principles

- Model proposes classifications; deterministic code prices the duty difference.
- Every cited ruling must have been retrieved and its identifier verified.
- Missing decisive facts produce a request for information, not a guess.
- Underpayment exposure is always surfaced, never buried to favor a positive ROI story.
- Human approval is required for consequential draft actions; no filing occurs.
- Tool failures and incomplete evidence must be explicit.
- Tool and approval behavior must be checked against current OpenAI Developer Documentation MCP references.

### Proposed MCP capabilities (subject to simplification)

- Retrieve catalog and aggregated entry records.
- Search HTS provisions and retrieve legal notes.
- Search and retrieve CBP rulings.
- Compute duty differences from validated cached rates.
- Prepare a gated correction draft after approval.

Choose the smallest viable set of tools that demonstrates the end-to-end workflow. The precise tool count is not a product requirement.

## 9. Data and scope

### Synthetic customer data

Northfield Home Goods has 12 synthetic SKUs and a bounded set of historical entries. The live demo uses the smallest subset that reliably shows the four required outcomes.

### Public sources

- USITC Harmonized Tariff Schedule, including relevant legal notes.
- CBP Customs Rulings Online Search System (CROSS).

Record source URLs, ruling identifiers, tariff schedule revision/date, and data provenance. Check that proposed tariff codes exist in the applicable schedule.

### Initial product families

Focus on a small set of housewares where material composition or other product attributes affect classification. The baseline plan suggests plastic household articles, ceramic tableware, and iron/steel household articles. **These are candidates, not validated final scenarios.** Select tariff lines only after confirming meaningful legal distinctions and base-duty rate differences.

### Financial scope and exclusions

Initial calculations cover **Column 1 General base-duty rate differences only**. Section 301, Section 232, IEEPA-related duties, and other overlays are excluded unless explicitly added and validated. The application does not determine refund eligibility, calculate complete entry liability, or automate customs submissions.

## 10. Evaluation and acceptance criteria

### Product acceptance

- Identifies meaningful potential overpayment opportunities in the selected synthetic scenario.
- Does not conceal underpayment exposure.
- Provides verifiable evidence for changed classifications.
- Escalates uncertain classifications appropriately.
- Produces a useful, broker-reviewable output.

### Technical acceptance

- Responses API and MCP integration run end to end.
- Duty calculations reconcile with deterministic reference values.
- Citations refer to actual retrieved rulings.
- Held-out evaluation cases are not exposed in the searchable evidence index.
- Approval controls prevent unauthorized consequential actions.
- Missing data and tool failures yield explicit incomplete or escalated outcomes.

### Independent classification evaluation

A 20-case historical CBP CROSS set is isolated from the searchable evidence
corpus. It covers the three demo product families and stores sanitized facts
separately from official ruling IDs, historical codes, and holdings. The cases
have been source-verified against official CBP records, but have not yet been
run against a model or reviewed by a licensed customs broker. Report exact and
six-digit classification scores, sample size, repeat count, and limitations;
do not present this selected set as broad classification-accuracy evidence.

### Workflow scenario evaluation

Test:

1. Potential overpayment detection.
2. Underpayment escalation to counsel.
3. Correct classifications remaining unchanged, including a decoy.
4. Missing product attributes and appropriate abstention.
5. Material-description edits.
6. Prompt injection in untrusted source material.
7. Tool failures and incomplete results.
8. Deterministic duty arithmetic and citation validity.

Report actual results and failures, not invented accuracy or reliability claims.

## 11. Five-minute demonstration plan

| Time | Demo beat | Key message |
|---|---|---|
| 0:00–1:15 | Slides: customer, opportunity, workflow, architecture | Premium audits create a new revenue opportunity for Harbor & Crane; importers may find savings. |
| 1:15–2:30 | Launch Northfield review | The agent gathers product facts, legal evidence, and historical entry information. |
| 2:30–3:15 | Findings and evidence | Show a potential overpayment, its support, an underpayment escalation, and a needs-info case. |
| 3:15–3:45 | Human approval and measured API cost | The broker controls consequential actions; review cost is measurable. |
| 3:45–4:15 | Edit product description and rerun | The system responds to relevant product facts rather than relying on a scripted lookup. |
| 4:15–5:00 | Impact, governance, evaluation, next steps | Importer opportunity + brokerage revenue model + credible controls. |

Timing is provisional. Rehearse with a timer and retain a working run-log fallback.

## 12. Business-value model

### Importer opportunity

For each affected entry or SKU:

**Potential base-duty difference = Historical base duty paid − Base duty calculated at the proposed rate.**

A positive result is a potential overpayment; a negative result is potential underpayment exposure. Report the two separately, without netting away compliance risk.

These differences are not guaranteed refunds and do not include excluded tariff overlays.

### Brokerage audit revenue

**Annual gross audit revenue = Number of paying audit clients × Annual audit fee per client.**

Illustrative scenario: 5 audits per quarter × $7,500 per audit × 4 quarters = **$150,000/year**. Audit volume and fee are assumptions. This is gross revenue, not gross margin or a validated forecast.

### Brokerage delivery economics

**Gross margin per audit = Audit fee − Direct audit delivery costs.**

Delivery costs may include licensed-broker review hours, specialist escalation, API usage, hosting, and direct operating expenses. Measure API cost separately; do not equate API cost with total audit cost.

### Productivity

**Broker time saved = Manual review time − AI-assisted review time, including verification and approval.**

Measure in a pilot rather than assuming the AI eliminates expert work.

## 13. Governance and limitations

- A licensed broker reviews classification recommendations and proposed correction drafts.
- The importer of record retains applicable legal responsibilities.
- Nothing is filed automatically with CBP.
- CBP rulings must be interpreted in context; analogous rulings are not universal guarantees.
- Tariff schedules and rates are time-sensitive; cache versions must be recorded.
- The prototype's financial scope excludes tariff overlays and refund eligibility analysis.
- Client data, secrets, and tool access must be protected.
- Logs must support review without leaking credentials.
- Recommendations and uncertainty must be explainable and auditable.

## 14. Deliverables

### Required by the assignment

- Three to five concise slides.
- A presentation-ready five-minute demo of **one** OpenAI product surface: OpenAI Platform and APIs.

### Supporting artifacts (time permitting)

- Reproducible application repository and README.
- Synthetic catalog, historical entries, and data generator.
- Cached public sources with provenance.
- Sample run logs and measured API cost.
- Evaluation results and failure notes.
- Screenshots or fallback demo artifacts.

The build is capped at approximately five hours. Prioritize the narrow end-to-end demo over stretch features. The working budget is: evidence and synthetic data (45 minutes), MCP tools and deterministic calculations (55), Responses API agent (60), Streamlit UI and broker approval (45), evaluation and hardening (45), and slides/documentation/rehearsal (50).

## 15. Decisions and remaining live gate

1. **Classification scenarios:** stainless drinkware vacuum status, utilitarian versus ornamental plastic articles, and porcelain versus other ceramic mugs.
2. **Demo subset:** `NF-DW-001` through `NF-DW-004`, which contains all four required outcomes.
3. **Synthetic economics:** one dated 2026 entry per SKU using the verified 2026 Revision 21 rates; amounts remain synthetic.
4. **Commercial illustration:** five audits per quarter at a $7,500 fixed fee, clearly labeled illustrative.
5. **MCP scope:** five bounded reads, one deterministic calculator, and one approval-gated local draft tool.
6. **Evaluation scope:** deterministic workflow checks only until a live model run is available; no broad accuracy claim.
7. **Authenticated transport:** a service-account-owned key and private tunnel are configured; the official tunnel client is healthy and connected to the local MCP server.
8. **Live validation:** the authenticated preflight, 6/6 focused live evaluation, explicit approval continuation, local draft generation, and 216-second rehearsal passed on 2026-10-18. See `LIVE_VALIDATION.md` for measured results and observed failures.

**Decided:** Harbor & Crane's primary commercial value is new premium audit revenue. Importer duty recovery is the demo hook; evidence, compliance risk detection, and human oversight are the trust story.

## 16. Implementation priorities

1. Validate real tariff examples, official tariff lines, historical rates where applicable, and 6–10 public rulings (minimum four).
2. Create the 12-SKU synthetic catalog and entry fixtures around 2–3 verified scenarios.
3. Implement and verify deterministic base Column 1 General duty calculations.
4. Implement the minimal MCP reads and draft-only write tool.
5. Connect the Responses API and produce structured, cited findings.
6. Build the smallest usable Streamlit review and approval interface.
7. Run focused evaluations and record actual latency, usage, cost, and correctness.
8. Prepare slides, documentation, a fallback trace, and a timed rehearsal.

Do not expand scope until the core workflow runs reliably. Keep the product specification open to revision as evidence and implementation constraints become clearer.
