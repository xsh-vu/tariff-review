from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from data.duty import DutyCalculator
from data.repository import DataError, PROJECT_ROOT, Repository
from server.approval import ApprovalStore


repository = Repository()
calculator = DutyCalculator(repository)
approval_store = ApprovalStore(
    Path(os.getenv("APPROVAL_STORE_PATH", PROJECT_ROOT / "runs" / "approvals.json"))
)


def get_catalog(
    client_id: str,
    sku_ids: list[str] | None = None,
    description_overrides: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return synthetic product records, applying explicit review-only descriptions."""
    products = repository.get_catalog(client_id, sku_ids)
    overrides = description_overrides or {}
    returned_skus = {product["sku_id"] for product in products}
    unknown = set(overrides) - returned_skus
    if unknown:
        raise DataError(
            f"description_overrides contains unrequested or unknown SKUs: {sorted(unknown)}"
        )
    for sku_id, description in overrides.items():
        if not isinstance(description, str) or not description.strip():
            raise DataError(f"Description override for {sku_id} must not be empty")
        if len(description) > 2000:
            raise DataError(f"Description override for {sku_id} exceeds 2000 characters")
        product = next(item for item in products if item["sku_id"] == sku_id)
        product["description"] = description.strip()
        product["description_source"] = "review_override"
    return products


def get_entries(client_id: str, sku_id: str) -> list[dict[str, Any]]:
    """Return the synthetic entry records for one known SKU."""
    return repository.get_entries(client_id, sku_id)


def search_hts(query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Search the small, versioned HTS evidence cache."""
    return repository.search_hts(query, limit)


def search_rulings(
    query: str, family: str | None = None, limit: int = 8
) -> list[dict[str, Any]]:
    """Search verified CBP CROSS ruling summaries and source URLs."""
    return repository.search_rulings(query, family, limit)


def get_ruling(ruling_id: str) -> dict[str, Any]:
    """Return one verified ruling summary with its official source URL."""
    return repository.get_ruling(ruling_id)


def compute_duty_delta(
    client_id: str, sku_id: str, declared_code: str, proposed_code: str
) -> dict[str, Any]:
    """Compute deterministic Column 1 General base-duty differences."""
    return calculator.compute_duty_delta(
        client_id, sku_id, declared_code, proposed_code
    )


def draft_correction(
    client_id: str,
    sku_id: str,
    declared_code: str,
    proposed_code: str,
    evidence_ids: list[str],
    rationale: str,
    route: str,
    approval_token: str,
) -> dict[str, Any]:
    """Create a local draft after exact, single-use broker authorization."""
    product = repository.get_product(client_id, sku_id)
    if product["declared_code"] != declared_code:
        raise DataError("Draft declared code does not match the product record")
    if proposed_code not in repository.hts_codes:
        raise DataError(f"Unsupported proposed code: {proposed_code}")
    unknown_evidence = set(evidence_ids) - repository.ruling_ids
    if unknown_evidence:
        raise DataError(f"Unknown evidence IDs: {sorted(unknown_evidence)}")
    if route != "broker":
        raise DataError("The demo draft workflow is restricted to the broker route")
    if not evidence_ids:
        raise DataError("At least one verified ruling is required for a draft")
    calculation = calculator.compute_duty_delta(
        client_id, sku_id, declared_code, proposed_code
    )
    if calculation["direction"] != "potential_overpayment":
        raise DataError("Only a potential overpayment may enter the demo draft flow")

    arguments = {
        "client_id": client_id,
        "sku_id": sku_id,
        "declared_code": declared_code,
        "proposed_code": proposed_code,
        "evidence_ids": evidence_ids,
        "rationale": rationale,
        "route": route,
        "approval_token": approval_token,
    }
    approval_store.consume(approval_token, arguments)

    draft_id = f"DRAFT-{uuid.uuid4().hex[:10].upper()}"
    destination = PROJECT_ROOT / "drafts" / f"{draft_id}.json"
    stored_arguments = {key: value for key, value in arguments.items() if key != "approval_token"}
    payload = {
        "draft_id": draft_id,
        "status": "draft_only",
        "not_filed": True,
        "approval_token_sha256": hashlib.sha256(approval_token.encode()).hexdigest(),
        "calculation": calculation,
        **stored_arguments,
    }
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return payload

