from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLISHED_HISTORICAL_RESULT = (
    PROJECT_ROOT
    / "evals"
    / "heldout"
    / "results"
    / "postfix-full-20261019.json"
)


class EvaluationResultError(ValueError):
    pass


def load_published_historical_result(
    path: Path = PUBLISHED_HISTORICAL_RESULT,
) -> dict[str, Any]:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationResultError(
            f"Historical evaluation result could not be loaded: {exc}"
        ) from exc

    required_sections = {
        "run_id",
        "model",
        "started_at",
        "summary",
        "mcp_reliability",
        "execution",
        "cases",
        "limitations",
    }
    missing = required_sections - set(result)
    if missing:
        raise EvaluationResultError(
            f"Historical evaluation result is missing: {sorted(missing)}"
        )

    summary = result["summary"]
    mcp = result["mcp_reliability"]
    if not isinstance(result["cases"], list):
        raise EvaluationResultError("Historical evaluation cases must be a list")
    if summary.get("total_cases") != len(result["cases"]):
        raise EvaluationResultError(
            "Historical evaluation case count does not match the result summary"
        )
    if mcp.get("successful_calls", 0) > mcp.get("expected_calls", 0):
        raise EvaluationResultError(
            "Historical evaluation reports more successful than expected MCP calls"
        )
    return result


def nonmatching_case_rows(result: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for case in result["cases"]:
        if case.get("exact_match"):
            continue
        abstained = bool(case.get("abstained"))
        rows.append(
            {
                "Case": str(case["case_id"]),
                "Result": "Asked for more information" if abstained else "Incorrect",
                "Model answer": str(case.get("actual_code") or "No classification"),
                "Historical answer": str(case.get("expected_code") or "—"),
            }
        )
    return rows
