from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HELDOUT_DIR = Path(__file__).resolve().parent
CASES_PATH = HELDOUT_DIR / "cases.json"
ANSWER_KEY_PATH = HELDOUT_DIR / "answer_key.json"
SEARCHABLE_RULINGS_PATH = PROJECT_ROOT / "data" / "source_data" / "rulings.json"

FULL_CODE_PATTERN = re.compile(r"^\d{4}\.\d{2}\.\d{2,4}$")
SIX_DIGIT_PATTERN = re.compile(r"^\d{4}\.\d{2}$")
EXPECTED_FAMILY_COUNTS = {
    "stainless_drinkware": 7,
    "plastic_housewares": 7,
    "ceramic_drinkware": 6,
}


class HeldoutValidationError(ValueError):
    """Raised when the held-out set is invalid or leaks a gold answer."""


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_dataset() -> dict[str, Any]:
    cases_document = _load_json(CASES_PATH)
    answer_document = _load_json(ANSWER_KEY_PATH)
    searchable_rulings = _load_json(SEARCHABLE_RULINGS_PATH)

    if cases_document["dataset_id"] != answer_document["dataset_id"]:
        raise HeldoutValidationError("Cases and answer key use different dataset IDs")
    if cases_document["version"] != answer_document["version"]:
        raise HeldoutValidationError("Cases and answer key use different versions")

    cases = cases_document["cases"]
    answers = answer_document["cases"]
    if len(cases) != 20 or len(answers) != 20:
        raise HeldoutValidationError("Held-out dataset must contain exactly 20 cases")

    case_ids = [item["case_id"] for item in cases]
    answer_ids = [item["case_id"] for item in answers]
    if len(set(case_ids)) != len(case_ids):
        raise HeldoutValidationError("Duplicate case IDs in sanitized cases")
    if len(set(answer_ids)) != len(answer_ids):
        raise HeldoutValidationError("Duplicate case IDs in answer key")
    if set(case_ids) != set(answer_ids):
        raise HeldoutValidationError("Cases and answer key do not contain the same IDs")

    family_counts = Counter(item["family"] for item in cases)
    if dict(family_counts) != EXPECTED_FAMILY_COUNTS:
        raise HeldoutValidationError(
            f"Unexpected family distribution: {dict(family_counts)}"
        )

    for item in cases:
        date.fromisoformat(item["as_of_date"])
        facts = item.get("product_facts")
        if not isinstance(facts, list) or not facts:
            raise HeldoutValidationError(f"{item['case_id']} has no product facts")
        if any(not isinstance(fact, str) or not fact.strip() for fact in facts):
            raise HeldoutValidationError(
                f"{item['case_id']} contains a blank or non-string product fact"
            )

    searchable_ids = {
        str(item["ruling_id"]).upper() for item in searchable_rulings
    }
    answer_ids_by_case = {item["case_id"]: item for item in answers}
    ruling_ids = [item["ruling_id"].upper() for item in answers]
    if len(set(ruling_ids)) != len(ruling_ids):
        raise HeldoutValidationError("Each held-out case must use a distinct ruling")
    overlap = searchable_ids.intersection(ruling_ids)
    if overlap:
        raise HeldoutValidationError(
            f"Held-out rulings leaked into the searchable corpus: {sorted(overlap)}"
        )

    serialized_cases = json.dumps(cases_document, sort_keys=True).upper()
    for case_id, answer in answer_ids_by_case.items():
        ruling_id = answer["ruling_id"].upper()
        expected_code = answer["expected_base_code"]
        expected_six_digit = answer["expected_six_digit_code"]
        if ruling_id in serialized_cases:
            raise HeldoutValidationError(
                f"{case_id} exposes its ruling ID in the sanitized cases"
            )
        if expected_code in serialized_cases or expected_six_digit in serialized_cases:
            raise HeldoutValidationError(
                f"{case_id} exposes its expected code in the sanitized cases"
            )
        if not FULL_CODE_PATTERN.fullmatch(expected_code):
            raise HeldoutValidationError(
                f"{case_id} has an invalid full HTSUS code: {expected_code}"
            )
        if not SIX_DIGIT_PATTERN.fullmatch(expected_six_digit):
            raise HeldoutValidationError(
                f"{case_id} has an invalid six-digit code: {expected_six_digit}"
            )
        if not expected_code.startswith(expected_six_digit):
            raise HeldoutValidationError(
                f"{case_id} full code does not match its six-digit code"
            )
        if answer["official_url"] != (
            f"https://rulings.cbp.gov/ruling/{answer['ruling_id']}"
        ):
            raise HeldoutValidationError(f"{case_id} has a noncanonical ruling URL")
        if answer["api_url"] != (
            f"https://rulings.cbp.gov/api/ruling/{answer['ruling_id']}"
        ):
            raise HeldoutValidationError(f"{case_id} has a noncanonical API URL")
        if answer["operationally_revoked"]:
            raise HeldoutValidationError(f"{case_id} uses an operationally revoked ruling")
        if answer["modified_by"] or answer["revoked_by"]:
            raise HeldoutValidationError(f"{case_id} uses a modified or revoked ruling")
        if answer["review_status"] != "source_verified":
            raise HeldoutValidationError(f"{case_id} is not source verified")

    return {
        "dataset_id": cases_document["dataset_id"],
        "version": cases_document["version"],
        "case_count": len(cases),
        "family_counts": dict(family_counts),
        "searchable_ruling_overlap": [],
        "gold_label_leaks": [],
        "broker_review_status": answer_document["broker_review_status"],
    }


def verify_official_sources(timeout_seconds: float = 15.0) -> dict[str, Any]:
    answer_document = _load_json(ANSWER_KEY_PATH)
    checked: list[str] = []

    for answer in answer_document["cases"]:
        request = Request(
            answer["api_url"],
            headers={"User-Agent": "Harbor-Crane-heldout-eval/1.0"},
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            record = json.load(response)

        case_id = answer["case_id"]
        if str(record["rulingNumber"]).upper() != answer["ruling_id"].upper():
            raise HeldoutValidationError(f"{case_id} official ruling ID changed")
        if answer["expected_base_code"] not in str(record.get("tariffs", "")):
            raise HeldoutValidationError(
                f"{case_id} expected code is absent from the official tariff field"
            )

        expected_date = date.fromisoformat(answer["ruling_date"])
        api_date = datetime.fromisoformat(record["rulingDate"]).date()
        if abs((expected_date - api_date).days) > 1:
            raise HeldoutValidationError(
                f"{case_id} official date differs by more than timezone normalization"
            )
        if bool(record.get("operationallyRevoked")):
            raise HeldoutValidationError(f"{case_id} is now operationally revoked")
        if record.get("modifiedBy") or record.get("revokedBy"):
            raise HeldoutValidationError(f"{case_id} is now modified or revoked")
        checked.append(answer["ruling_id"])

    return {"official_sources_checked": len(checked), "ruling_ids": checked}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify-live",
        action="store_true",
        help="Recheck IDs, codes, dates, and status against the official CBP API.",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    result = validate_dataset()
    if args.verify_live:
        result.update(verify_official_sources(args.timeout))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

