from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator


class HistoricalClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    proposed_code: str | None
    reason: str
    hts_evidence_ids: list[str]
    rulings_cited: list[str]
    needs_more_information: bool
    missing_information: str | None

    @model_validator(mode="after")
    def validate_decision(self) -> "HistoricalClassification":
        if self.needs_more_information:
            if self.proposed_code is not None or not self.missing_information:
                raise ValueError(
                    "needs_more_information requires no code and a missing fact"
                )
        else:
            if self.proposed_code is None or self.missing_information is not None:
                raise ValueError(
                    "a completed classification requires a code and no missing fact"
                )
            if not self.hts_evidence_ids:
                raise ValueError(
                    "a completed classification requires retrieved HTS evidence"
                )
        return self


def strict_historical_response_format() -> dict:
    return {
        "type": "json_schema",
        "name": "historical_classification",
        "strict": True,
        "schema": HistoricalClassification.model_json_schema(),
    }
