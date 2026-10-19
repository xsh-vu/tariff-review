from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Finding(StrictModel):
    sku_id: str
    proposed_code: str | None
    outcome: Literal[
        "potential_overpayment", "potential_underpayment", "needs_info", "confirmed"
    ]
    deciding_rule: str
    legal_notes_cited: list[str]
    rulings_cited: list[str]
    route_to: Literal["broker", "counsel", "supplier"]
    missing_fact: str | None

    @model_validator(mode="after")
    def check_outcome_contract(self) -> "Finding":
        if self.outcome == "needs_info":
            if self.proposed_code is not None or self.missing_fact is None:
                raise ValueError("needs_info requires a missing fact and no proposed code")
        elif self.proposed_code is None:
            raise ValueError("completed findings require a proposed code")
        expected_route = {
            "potential_overpayment": "broker",
            "potential_underpayment": "counsel",
            "needs_info": "supplier",
            "confirmed": "broker",
        }[self.outcome]
        if self.route_to != expected_route:
            raise ValueError(f"{self.outcome} findings must route to {expected_route}")
        return self


class ClassificationProposal(StrictModel):
    run_id: str
    client_id: str
    findings: list[Finding]


def strict_response_format() -> dict:
    return {
        "type": "json_schema",
        "name": "classification_proposal",
        "strict": True,
        "schema": ClassificationProposal.model_json_schema(),
    }


def validate_evidence_and_codes(
    proposal: ClassificationProposal,
    known_ruling_ids: set[str],
    known_codes: set[str],
) -> None:
    for finding in proposal.findings:
        unknown_rulings = set(finding.rulings_cited) - known_ruling_ids
        if unknown_rulings:
            raise ValueError(
                f"{finding.sku_id} cites unfetched rulings: {sorted(unknown_rulings)}"
            )
        if finding.proposed_code and finding.proposed_code not in known_codes:
            raise ValueError(f"Unknown proposed code: {finding.proposed_code}")

