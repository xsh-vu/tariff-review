from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from agent.schema import ClassificationProposal, Finding, MissingInformation
from data.duty import DutyCalculator
from data.repository import Repository


class FixtureReviewer:
    """Deterministic preview and evaluator; never presented as an OpenAI run."""

    def __init__(
        self,
        repository: Repository | None = None,
        calculator: DutyCalculator | None = None,
    ) -> None:
        self.repository = repository or Repository()
        self.calculator = calculator or DutyCalculator(self.repository)

    def _classify(
        self, product: dict[str, Any], description: str
    ) -> tuple[str | None, list[str], str | None, str]:
        text = description.lower()
        family = product["family"]
        if family == "stainless_drinkware":
            if "no vacuum" in text or "without vacuum" in text:
                return (
                    "7323.93.0080",
                    ["N224817", "N241154", "N321134"],
                    None,
                    "Vacuum construction is the decisive physical distinction.",
                )
            if "vacuum-sealed" in text or "vacuum flask" in text or "sub-atmospheric" in text:
                return (
                    "9617.00.1000",
                    ["N224817"],
                    None,
                    "A complete vessel with confirmed sub-atmospheric pressure is treated as a vacuum vessel.",
                )
            return (
                None,
                ["N224817", "N321134"],
                "Supplier specification or laboratory evidence confirming whether a vacuum exists between the walls",
                "Double-wall or insulated wording alone does not establish vacuum construction.",
            )
        if family == "plastic_housewares":
            if any(term in text for term in ("ornament", "decoration", "statuette")) and (
                "no utilitarian" in text or "no opening" in text or "only" in text
            ):
                return (
                    "3926.40.0090",
                    ["N328023", "N321767"],
                    None,
                    "The article's primary role is ornamentation rather than household utility.",
                )
            if "planter" in text and any(
                term in text for term in ("grow plants", "hold soil", "drainage")
            ):
                return (
                    "3924.90.5650",
                    ["N328023", "N283412"],
                    None,
                    "A reusable planter with a receptacle and growing function is a household article.",
                )
            return (
                None,
                ["N328023", "H296920"],
                "The article's primary household function and whether it is a usable receptacle",
                "The record does not establish utilitarian household use versus ornamentation.",
            )
        if family == "ceramic_mugs":
            if "non-porcelain" in text or "stoneware" in text or "earthenware" in text:
                return (
                    "6912.00.4400",
                    ["L85060", "N295888"],
                    None,
                    "A mug made of ceramic other than porcelain or china falls in heading 6912.",
                )
            if "porcelain" in text and "confirms" in text:
                return (
                    "6911.10.4500",
                    ["L85060", "N295888"],
                    None,
                    "A mug whose body meets the Chapter 69 porcelain definition falls in heading 6911.",
                )
            return (
                None,
                ["L85060", "N295888"],
                "Supplier or laboratory evidence for ceramic body composition, absorption, and translucency",
                "The generic word ceramic does not distinguish porcelain from other ceramic bodies.",
            )
        raise ValueError(f"Unsupported family: {family}")

    def review(
        self,
        sku_ids: list[str],
        description_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        run_id = f"FIXTURE-{uuid.uuid4().hex[:10].upper()}"
        products = self.repository.get_catalog("northfield-home-goods", sku_ids)
        overrides = description_overrides or {}
        findings: list[Finding] = []
        missing: list[MissingInformation] = []
        calculations: dict[str, dict[str, Any]] = {}

        for product in products:
            description = overrides.get(product["sku_id"], product["description"])
            proposed, evidence_ids, missing_fact, rationale = self._classify(
                product, description
            )
            declared = product["declared_code"]
            if proposed is None:
                outcome = "needs_info"
                route = "supplier"
                action = "Request the missing product specification before classifying."
                missing.append(
                    MissingInformation(
                        sku_id=product["sku_id"], required_fact=missing_fact or "Unknown"
                    )
                )
            elif proposed == declared:
                outcome = "confirmed"
                route = "broker"
                action = "Retain the declared classification; no correction is indicated."
            else:
                calculation = self.calculator.compute_duty_delta(
                    product["client_id"], product["sku_id"], declared, proposed
                )
                calculations[product["sku_id"]] = calculation
                outcome = calculation["direction"]
                route = "counsel" if outcome == "potential_underpayment" else "broker"
                action = (
                    "Escalate potential underpayment for compliance review."
                    if outcome == "potential_underpayment"
                    else "Broker should validate recovery eligibility before preparing a draft."
                )
            findings.append(
                Finding(
                    sku_id=product["sku_id"],
                    declared_code=declared,
                    proposed_code=proposed,
                    outcome=outcome,
                    deciding_rule=rationale,
                    legal_notes_cited=(
                        ["HTS Chapter 69 Note 5"]
                        if product["family"] == "ceramic_mugs"
                        else []
                    ),
                    rulings_cited=evidence_ids,
                    confidence_or_uncertainty=(
                        "Incomplete: decisive product evidence is missing."
                        if proposed is None
                        else "Supported for this synthetic fact pattern; broker verification required."
                    ),
                    recommended_action=action,
                    route_to=route,
                    missing_fact=missing_fact,
                )
            )

        proposal = ClassificationProposal(
            run_id=run_id,
            client_id="northfield-home-goods",
            status="incomplete" if missing else "complete",
            scope="Column 1 General base-duty screening; synthetic demo data",
            source_revision=self.repository.source_revision,
            findings=findings,
            missing_information=missing,
            warnings=[
                "Potential duty differences are not guaranteed refunds.",
                "Chapter 99 duties, trade remedies, preference programs, and recovery eligibility are excluded.",
                "This fixture preview is deterministic and is not an OpenAI API result.",
            ],
        )
        overpayment = sum(
            Decimal(item["potential_base_duty_difference"])
            for item in calculations.values()
            if Decimal(item["potential_base_duty_difference"]) > 0
        )
        underpayment = sum(
            -Decimal(item["potential_base_duty_difference"])
            for item in calculations.values()
            if Decimal(item["potential_base_duty_difference"]) < 0
        )
        return {
            "proposal": proposal.model_dump(mode="json"),
            "calculations": calculations,
            "potential_overpayment_total": f"{overpayment:.2f}",
            "potential_underpayment_total": f"{underpayment:.2f}",
            "execution": {
                "mode": "deterministic_fixture_preview",
                "api_usage": None,
                "latency_seconds": None,
                "api_cost_usd": None,
            },
        }

