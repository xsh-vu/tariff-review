from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


OUTCOME_RECOMMENDATIONS = {
    "potential_overpayment": {
        "label": "Potential overpayment",
        "action": (
            "Validate the evidence and recovery eligibility. A correction draft may "
            "then be prepared for broker approval."
        ),
    },
    "potential_underpayment": {
        "label": "Potential underpayment",
        "action": "Escalate for compliance or legal review; do not treat it as savings.",
    },
    "needs_info": {
        "label": "Needs more information",
        "action": "Obtain the missing product evidence before making a classification.",
    },
    "confirmed": {
        "label": "Classification confirmed",
        "action": "Retain the declared classification; no correction is indicated.",
    },
}


def summarize_recommendations(
    findings: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Group reviewed SKUs into stable, reviewer-friendly next actions."""
    grouped = {outcome: [] for outcome in OUTCOME_RECOMMENDATIONS}
    for finding in findings:
        outcome = finding.get("outcome")
        sku_id = finding.get("sku_id")
        if outcome in grouped and isinstance(sku_id, str) and sku_id:
            grouped[outcome].append(sku_id)

    summary: list[dict[str, Any]] = []
    for outcome, recommendation in OUTCOME_RECOMMENDATIONS.items():
        sku_ids = grouped[outcome]
        if not sku_ids:
            continue
        summary.append(
            {
                "outcome": outcome,
                "label": recommendation["label"],
                "sku_ids": sku_ids,
                "count": len(sku_ids),
                "action": recommendation["action"],
            }
        )
    return summary
