from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from decimal import Decimal
from pathlib import Path
from typing import Any


HELDOUT_DIR = Path(__file__).resolve().parent
DEFAULT_ANSWER_KEY = HELDOUT_DIR / "answer_key.json"


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _six_digit(code: str | None) -> str | None:
    if not code:
        return None
    digits = "".join(character for character in code if character.isdigit())
    if len(digits) < 6:
        return None
    return f"{digits[:4]}.{digits[4:6]}"


def _percent(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(100 * numerator / denominator, 1)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def grade_case(record: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    proposal = record.get("proposal") or {}
    actual_code = proposal.get("proposed_code")
    raw_text = json.dumps(record.get("response"), sort_keys=True).upper()
    target_leaked = answer["ruling_id"].upper() in raw_text

    trace = (record.get("mcp") or {}).get("trace") or []
    expected_tools = ["search_historical_hts", "search_rulings_batch"]
    matching_calls = [call for call in trace if call.get("name") in expected_tools]
    call_counts = {
        name: sum(1 for call in matching_calls if call.get("name") == name)
        for name in expected_tools
    }
    successful_calls = [call for call in matching_calls if not call.get("error")]
    mcp_reliable = (
        call_counts == {name: 1 for name in expected_tools}
        and len(successful_calls) == len(expected_tools)
    )

    mcp = record.get("mcp") or {}
    fetched_codes = set(mcp.get("fetched_hts_codes") or [])
    fetched_hts_ids = set(mcp.get("fetched_hts_evidence_ids") or [])
    fetched_ruling_ids = {
        str(value).upper() for value in (mcp.get("fetched_ruling_ids") or [])
    }
    cited_hts_ids = set(proposal.get("hts_evidence_ids") or [])
    cited_ruling_ids = {
        str(value).upper() for value in (proposal.get("rulings_cited") or [])
    }
    citation_valid = bool(record.get("status") == "validated") and not (
        cited_hts_ids - fetched_hts_ids
        or cited_ruling_ids - fetched_ruling_ids
        or (actual_code and actual_code not in fetched_codes)
    )
    publication_valid = False
    if mcp.get("revision_published_on"):
        publication_valid = (
            str(mcp["revision_published_on"]) <= record["case"]["as_of_date"]
        )

    evaluated = (
        record.get("status") == "validated"
        and mcp_reliable
        and citation_valid
        and publication_valid
        and not target_leaked
    )
    exact_match = bool(evaluated and actual_code == answer["expected_base_code"])
    six_digit_match = bool(
        evaluated and _six_digit(actual_code) == answer["expected_six_digit_code"]
    )
    abstained = bool(proposal.get("needs_more_information"))

    return {
        "case_id": answer["case_id"],
        "family": record.get("family"),
        "status": record.get("status"),
        "evaluated": evaluated,
        "expected_code": answer["expected_base_code"],
        "expected_six_digit_code": answer["expected_six_digit_code"],
        "actual_code": actual_code,
        "exact_match": exact_match,
        "six_digit_match": six_digit_match,
        "abstained": abstained,
        "unsupported_confident_error": bool(
            evaluated and not abstained and not six_digit_match
        ),
        "citation_valid": citation_valid,
        "mcp_reliable": mcp_reliable,
        "mcp_calls_attempted": len(matching_calls),
        "mcp_calls_successful": len(successful_calls),
        "revision_published_on_or_before_case": publication_valid,
        "target_ruling_leaked": target_leaked,
        "rulings_cited": proposal.get("rulings_cited") or [],
        "hts_evidence_ids": proposal.get("hts_evidence_ids") or [],
        "official_answer_url": answer["official_url"],
        "failure": record.get("failure"),
    }


def grade_run(
    run_dir: Path,
    output_path: Path,
    answer_key_path: Path = DEFAULT_ANSWER_KEY,
) -> dict[str, Any]:
    manifest = _load_json(run_dir / "manifest.json")
    raw_paths = [run_dir / item["raw_file"] for item in manifest["cases"]]
    if not all(path.exists() for path in raw_paths):
        raise ValueError("All raw response records must exist before grading")

    # This is intentionally the first answer-key read in the run-and-grade flow.
    answer_document = _load_json(answer_key_path)
    answers = {item["case_id"]: item for item in answer_document["cases"]}
    graded_cases = []
    latencies = []
    costs: list[Decimal] = []
    cost_bases: list[dict[str, Any]] = []
    total_tokens = 0
    unknown_costs = 0
    for raw_path in raw_paths:
        record = _load_json(raw_path)
        case_id = record["case"]["case_id"]
        if case_id not in answers:
            raise ValueError(f"No answer key record for {case_id}")
        record["family"] = manifest["family_by_case"][case_id]
        graded_cases.append(grade_case(record, answers[case_id]))
        execution = record.get("execution") or {}
        if isinstance(execution.get("latency_seconds"), (int, float)):
            latencies.append(float(execution["latency_seconds"]))
        usage = execution.get("api_usage") or {}
        if isinstance(usage.get("total_tokens"), int):
            total_tokens += usage["total_tokens"]
        if execution.get("api_cost_usd") is None:
            if execution:
                unknown_costs += 1
        else:
            costs.append(Decimal(str(execution["api_cost_usd"])))
        if isinstance(execution.get("cost_basis"), dict):
            cost_bases.append(execution["cost_basis"])

    common_cost_basis = None
    if cost_bases and all(item == cost_bases[0] for item in cost_bases):
        common_cost_basis = cost_bases[0]

    eligible = sum(
        1 for item in manifest["cases"] if item["preflight_status"] == "eligible"
    )
    evaluated = sum(case["evaluated"] for case in graded_cases)
    exact = sum(case["exact_match"] for case in graded_cases)
    six_digit = sum(case["six_digit_match"] for case in graded_cases)
    citation_valid = sum(case["citation_valid"] for case in graded_cases)
    unsupported = sum(case["unsupported_confident_error"] for case in graded_cases)
    mcp_attempted = sum(case["mcp_calls_attempted"] for case in graded_cases)
    mcp_successful = sum(case["mcp_calls_successful"] for case in graded_cases)
    target_leaks = sum(case["target_ruling_leaked"] for case in graded_cases)
    evidence_gaps = len(manifest["cases"]) - eligible
    graded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result = {
        "evaluation_mode": "historical_cbp_cross_responses_api_remote_mcp",
        "dataset_id": manifest["dataset_id"],
        "dataset_version": manifest["dataset_version"],
        "run_id": manifest["run_id"],
        "model": manifest.get("model"),
        "started_at": manifest["started_at"],
        "responses_persisted_at": manifest["responses_persisted_at"],
        "graded_at": graded_at,
        "answer_key_loaded_after_responses_persisted": (
            graded_at >= manifest["responses_persisted_at"]
        ),
        "summary": {
            "total_cases": len(manifest["cases"]),
            "evidence_eligible_cases": eligible,
            "evidence_gap_cases": evidence_gaps,
            "evaluated_responses": evaluated,
            "exact_matches": exact,
            "exact_match_rate_all_eligible_percent": _percent(exact, eligible),
            "exact_match_rate_completed_percent": _percent(exact, evaluated),
            "six_digit_matches": six_digit,
            "six_digit_match_rate_all_eligible_percent": _percent(
                six_digit, eligible
            ),
            "valid_citations": citation_valid,
            "unsupported_confident_errors": unsupported,
            "target_ruling_leaks": target_leaks,
        },
        "mcp_reliability": {
            "expected_calls": eligible * 2,
            "attempted_calls": mcp_attempted,
            "successful_calls": mcp_successful,
            "success_rate_expected_percent": _percent(
                mcp_successful, eligible * 2
            ),
        },
        "execution": {
            "api_responses": len(latencies),
            "total_tokens": total_tokens,
            "estimated_api_cost_usd": (
                f"{sum(costs):.6f}" if costs and unknown_costs == 0 else None
            ),
            "costs_unavailable_for_responses": unknown_costs,
            "cost_basis": common_cost_basis,
            "mean_latency_seconds": (
                round(statistics.mean(latencies), 3) if latencies else None
            ),
            "p50_latency_seconds": _percentile(latencies, 0.50),
            "p95_latency_seconds": _percentile(latencies, 0.95),
        },
        "cases": graded_cases,
        "limitations": [
            "The 20 cases are selected from three demo product families and are not a random sample of customs classifications.",
            "The target rulings are excluded from MCP search, but public rulings may have appeared in base-model training data.",
            "Source verification is not licensed-broker review; broker review remains pending.",
            "Classification accuracy, MCP reliability, and evidence coverage are reported separately.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--answer-key", type=Path, default=DEFAULT_ANSWER_KEY)
    args = parser.parse_args()
    result = grade_run(args.run_dir, args.output, args.answer_key)
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
