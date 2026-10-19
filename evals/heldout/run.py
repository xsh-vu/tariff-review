from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from data.repository import HistoricalEvidenceRepository, PROJECT_ROOT
from evals.heldout.client import HistoricalCaseClient
from evals.heldout.grade import grade_run


HELDOUT_DIR = Path(__file__).resolve().parent
CASES_PATH = HELDOUT_DIR / "cases.json"
DEFAULT_RESULTS_PATH = HELDOUT_DIR / "results" / "latest.json"
DEFAULT_RUNS_DIR = PROJECT_ROOT / "runs" / "heldout"

PREFLIGHT_QUERIES = {
    "stainless_drinkware": "vacuum vessels stainless steel household drinkware",
    "plastic_housewares": "plastic household articles ornamental articles",
    "ceramic_drinkware": "porcelain china bone china ceramic mugs cups",
}


def _load_cases(case_ids: list[str] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    document = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Held-out cases document is empty")
    known = {case["case_id"] for case in cases}
    if len(known) != len(cases):
        raise ValueError("Held-out cases contain duplicate IDs")
    if case_ids:
        unknown = set(case_ids) - known
        if unknown:
            raise ValueError(f"Unknown case IDs: {sorted(unknown)}")
        selected = [case for case in cases if case["case_id"] in set(case_ids)]
    else:
        selected = cases
    for case in selected:
        required = {
            "case_id",
            "family",
            "as_of_date",
            "product_name",
            "product_facts",
        }
        if set(case) != required:
            raise ValueError(
                f"{case.get('case_id')} has unexpected sanitized-case fields"
            )
        if not isinstance(case["product_facts"], list) or not case["product_facts"]:
            raise ValueError(f"{case['case_id']} has no product facts")
    return document, selected


def preflight_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repository = HistoricalEvidenceRepository()
    results = []
    for case in cases:
        try:
            query = PREFLIGHT_QUERIES[case["family"]]
            snapshot = repository.snapshot_for(case["as_of_date"])
            matches = repository.search_hts(case["as_of_date"], query, limit=8)
            if len(matches) < 2:
                raise ValueError("fewer than two dated candidate provisions")
            results.append(
                {
                    "case_id": case["case_id"],
                    "status": "eligible",
                    "revision_id": snapshot["revision_id"],
                    "revision_published_on": snapshot["published_on"],
                    "candidate_codes": [match["code"] for match in matches],
                }
            )
        except Exception as exc:
            results.append(
                {
                    "case_id": case["case_id"],
                    "status": "not_evaluated_evidence_gap",
                    "failure": {"type": type(exc).__name__, "message": str(exc)},
                }
            )
    return results


def run_benchmark(
    case_ids: list[str] | None = None,
    output_path: Path = DEFAULT_RESULTS_PATH,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    grade: bool = True,
    client: HistoricalCaseClient | None = None,
) -> dict[str, Any]:
    cases_document, cases = _load_cases(case_ids)
    preflight = preflight_cases(cases)
    preflight_by_id = {item["case_id"]: item for item in preflight}
    run_id = f"HIST-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8].upper()}"
    run_dir = runs_dir / run_id
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=False)
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if client is None and any(item["status"] == "eligible" for item in preflight):
        load_dotenv(PROJECT_ROOT / ".env")
        client = HistoricalCaseClient()

    manifest_cases = []
    for case in cases:
        preflight_record = preflight_by_id[case["case_id"]]
        raw_path = raw_dir / f"{case['case_id']}.json"
        if preflight_record["status"] != "eligible":
            record = {
                "case": {
                    "case_id": case["case_id"],
                    "as_of_date": case["as_of_date"],
                    "product_name": case["product_name"],
                    "product_facts": case["product_facts"],
                },
                "status": "not_evaluated_evidence_gap",
                "failure": preflight_record["failure"],
                "response": None,
            }
        else:
            try:
                if client is None:
                    raise RuntimeError("HistoricalCaseClient was not initialized")
                record = client.review_case(case)
            except Exception as exc:
                record = {
                    "case": {
                        "case_id": case["case_id"],
                        "as_of_date": case["as_of_date"],
                        "product_name": case["product_name"],
                        "product_facts": case["product_facts"],
                    },
                    "status": "api_failure",
                    "failure": {"type": type(exc).__name__, "message": str(exc)},
                    "response": None,
                }
        raw_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        manifest_cases.append(
            {
                "case_id": case["case_id"],
                "preflight_status": preflight_record["status"],
                "raw_file": str(raw_path.relative_to(run_dir)),
            }
        )

    responses_persisted_at = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
    )
    manifest = {
        "run_id": run_id,
        "dataset_id": cases_document["dataset_id"],
        "dataset_version": cases_document["version"],
        "model": client.config.model if client is not None else None,
        "started_at": started_at,
        "responses_persisted_at": responses_persisted_at,
        "family_by_case": {case["case_id"]: case["family"] for case in cases},
        "cases": manifest_cases,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    if not grade:
        return {"run_dir": str(run_dir), "manifest": manifest, "preflight": preflight}
    result = grade_run(run_dir, output_path)
    result["run_dir"] = str(run_dir)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", action="append", dest="case_ids")
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--no-grade", action="store_true")
    args = parser.parse_args()

    if args.preflight_only:
        _, cases = _load_cases(args.case_ids)
        result = preflight_cases(cases)
        print(json.dumps(result, indent=2))
        return
    result = run_benchmark(
        case_ids=args.case_ids,
        output_path=args.output,
        runs_dir=args.runs_dir,
        grade=not args.no_grade,
    )
    if "summary" in result:
        print(json.dumps(result["summary"], indent=2))
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
