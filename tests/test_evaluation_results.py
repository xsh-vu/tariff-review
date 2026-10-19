from __future__ import annotations

import json

import pytest

from app.evaluation_results import (
    EvaluationResultError,
    load_published_historical_result,
    nonmatching_case_rows,
)


def test_published_historical_result_matches_recorded_clean_run() -> None:
    result = load_published_historical_result()

    assert result["run_id"] == "HIST-20261019T230540Z-5CDC39FE"
    assert result["summary"]["exact_matches"] == 17
    assert result["mcp_reliability"]["successful_calls"] == 40
    assert len(nonmatching_case_rows(result)) == 3


def test_published_result_loader_rejects_inconsistent_case_count(tmp_path) -> None:
    path = tmp_path / "result.json"
    path.write_text(
        json.dumps(
            {
                "run_id": "run",
                "model": "model",
                "started_at": "2026-10-19T00:00:00Z",
                "summary": {"total_cases": 2},
                "mcp_reliability": {
                    "successful_calls": 2,
                    "expected_calls": 2,
                },
                "execution": {},
                "cases": [{}],
                "limitations": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationResultError, match="case count"):
        load_published_historical_result(path)
