from __future__ import annotations

import json
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent.client import TariffReviewClient
from data.repository import PROJECT_ROOT


DEMO_SKUS = ["NF-DW-001", "NF-DW-002", "NF-DW-003", "NF-DW-004"]
OUTPUT = PROJECT_ROOT / "evals" / "live_results.json"


def _case(name: str, passed: bool, **details: Any) -> dict[str, Any]:
    return {"name": name, "passed": passed, **details}


def evaluate_live(output: Path = OUTPUT) -> dict[str, Any]:
    load_dotenv(PROJECT_ROOT / ".env")
    started = time.perf_counter()
    expected = json.loads(
        (PROJECT_ROOT / "config" / "answer_key.json").read_text(encoding="utf-8")
    )
    try:
        client = TariffReviewClient()
        review = client.review(DEMO_SKUS)
        findings = {
            finding["sku_id"]: finding for finding in review["proposal"]["findings"]
        }
        cases = []
        for sku_id in DEMO_SKUS:
            actual = findings[sku_id]
            gold = expected[sku_id]
            cases.append(
                _case(
                    f"live_classification:{sku_id}",
                    actual["outcome"] == gold["expected_outcome"]
                    and actual["proposed_code"] == gold["expected_code"],
                    expected_outcome=gold["expected_outcome"],
                    actual_outcome=actual["outcome"],
                    expected_code=gold["expected_code"],
                    actual_code=actual["proposed_code"],
                )
            )

        edit_review = client.review(
            ["NF-DW-003"],
            {
                "NF-DW-003": (
                    "14 oz complete stainless-steel vacuum flask with "
                    "laboratory-confirmed sub-atmospheric pressure between its walls."
                )
            },
        )
        edit_finding = edit_review["proposal"]["findings"][0]
        cases.append(
            _case(
                "live_description_edit_changes_review",
                edit_finding["outcome"] == "potential_underpayment"
                and edit_finding["proposed_code"] == "9617.00.1000",
                actual_outcome=edit_finding["outcome"],
                actual_code=edit_finding["proposed_code"],
            )
        )
        cases.append(
            _case(
                "remote_mcp_and_structured_output",
                bool(review["remote_mcp"]["successful_calls"])
                and review["structured_output_validated"] is True,
                transport=review["remote_mcp"]["transport"],
                successful_calls=review["remote_mcp"]["successful_calls"],
            )
        )

        executions = [review["execution"], edit_review["execution"]]
        costs = [
            Decimal(item["api_cost_usd"])
            for item in executions
            if item["api_cost_usd"] is not None
        ]
        passed = sum(case["passed"] for case in cases)
        result = {
            "evaluation_mode": "live_responses_api_remote_mcp",
            "openai_api_evaluation": True,
            "status": "passed" if passed == len(cases) else "failed",
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "summary": {"passed": passed, "total": len(cases)},
            "cases": cases,
            "executions": executions,
            "aggregate": {
                "api_calls": len(executions),
                "total_tokens": sum(
                    item["api_usage"]["total_tokens"] or 0 for item in executions
                ),
                "latency_seconds": round(
                    sum(item["latency_seconds"] for item in executions), 3
                ),
                "estimated_api_cost_usd": (
                    f"{sum(costs):.6f}" if len(costs) == len(executions) else None
                ),
            },
            "financial_checks": {
                "potential_overpayment_total": review[
                    "potential_overpayment_total"
                ],
                "potential_underpayment_total": review[
                    "potential_underpayment_total"
                ],
            },
            "limitations": [
                "The four classification cases are synthetic workflow fixtures, not an independent held-out legal benchmark.",
                "Published-rate cost is an estimate from API token categories; billing records remain authoritative.",
            ],
        }
    except Exception as exc:
        result = {
            "evaluation_mode": "live_responses_api_remote_mcp",
            "openai_api_evaluation": True,
            "status": "failed",
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "summary": {"passed": 0, "total": 0},
            "failure": {"type": type(exc).__name__, "message": str(exc)},
        }
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    result = evaluate_live()
    print(json.dumps(result, indent=2))
    if result["status"] != "passed":
        sys.exit(1)


if __name__ == "__main__":
    main()
