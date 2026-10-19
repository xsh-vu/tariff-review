from __future__ import annotations

import pytest
from pydantic import ValidationError

from evals.heldout.grade import grade_case
from evals.heldout.run import _load_cases, preflight_cases
from evals.heldout.schema import HistoricalClassification


def test_all_heldout_cases_have_eligible_dated_evidence() -> None:
    _, cases = _load_cases()

    results = preflight_cases(cases)

    assert len(results) == 20
    assert {item["status"] for item in results} == {"eligible"}


def test_historical_schema_requires_evidence_for_completed_answer() -> None:
    with pytest.raises(ValidationError):
        HistoricalClassification(
            case_id="CASE-1",
            proposed_code="9617.00.1000",
            reason="Vacuum-insulated vessel.",
            hts_evidence_ids=[],
            rulings_cited=[],
            needs_more_information=False,
            missing_information=None,
        )


def test_grader_separates_exact_match_from_mcp_reliability() -> None:
    record = {
        "case": {"case_id": "CASE-1", "as_of_date": "2025-01-15"},
        "status": "validated",
        "proposal": {
            "proposed_code": "9617.00.1000",
            "hts_evidence_ids": ["HTS-9617"],
            "rulings_cited": ["N321134"],
            "needs_more_information": False,
        },
        "response": {"id": "response-without-hidden-answer"},
        "mcp": {
            "trace": [
                {"name": "search_historical_hts", "error": None},
                {"name": "search_rulings_batch", "error": None},
            ],
            "fetched_hts_codes": ["9617.00.1000"],
            "fetched_hts_evidence_ids": ["HTS-9617"],
            "fetched_ruling_ids": ["N321134"],
            "revision_published_on": "2025-01-01",
        },
    }
    answer = {
        "case_id": "CASE-1",
        "ruling_id": "TARGET-SECRET",
        "expected_base_code": "9617.00.1000",
        "expected_six_digit_code": "9617.00",
        "official_url": "https://rulings.cbp.gov/ruling/TARGET-SECRET",
    }

    result = grade_case(record, answer)

    assert result["exact_match"] is True
    assert result["citation_valid"] is True
    assert result["mcp_reliable"] is True
    assert result["mcp_calls_successful"] == 2
    assert result["target_ruling_leaked"] is False
