from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from data.repository import DataError, Repository


CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _decimal_string(value: Decimal) -> str:
    return format(_money(value), ".2f")


class DutyCalculator:
    """Calculates only validated ad-valorem Column 1 General base duties."""

    def __init__(self, repository: Repository | None = None) -> None:
        self.repository = repository or Repository()

    def _rate_for(self, code: str, entry_date: str) -> dict[str, Any]:
        rate = self.repository.get_rate(code)
        requested = date.fromisoformat(entry_date)
        start = date.fromisoformat(rate["effective_from"])
        end = date.fromisoformat(rate["effective_to"]) if rate["effective_to"] else None
        if requested < start or (end is not None and requested > end):
            raise DataError(
                f"No validated {self.repository.source_revision} rate for {code} "
                f"on {entry_date}"
            )
        if rate["rate_type"] != "ad_valorem":
            raise DataError(f"Unsupported rate type for {code}: {rate['rate_type']}")
        return rate

    def compute_duty_delta(
        self,
        client_id: str,
        sku_id: str,
        declared_code: str,
        proposed_code: str,
    ) -> dict[str, Any]:
        product = self.repository.get_product(client_id, sku_id)
        if product["declared_code"] != declared_code:
            raise DataError(
                f"Declared code mismatch for {sku_id}: expected {product['declared_code']}"
            )
        entries = self.repository.get_entries(client_id, sku_id)
        if not entries:
            raise DataError(f"No entries found for {sku_id}")

        line_results: list[dict[str, Any]] = []
        total_declared = Decimal("0")
        total_proposed = Decimal("0")
        for entry in entries:
            if entry["declared_code"] != declared_code:
                raise DataError(f"Entry {entry['entry_id']} has an inconsistent declared code")
            declared_rate = self._rate_for(declared_code, entry["entry_date"])
            proposed_rate = self._rate_for(proposed_code, entry["entry_date"])
            value = Decimal(entry["entered_value"])
            declared_duty = _money(value * Decimal(declared_rate["general_rate"]))
            proposed_duty = _money(value * Decimal(proposed_rate["general_rate"]))
            difference = _money(declared_duty - proposed_duty)
            total_declared += declared_duty
            total_proposed += proposed_duty
            line_results.append(
                {
                    "entry_id": entry["entry_id"],
                    "entry_date": entry["entry_date"],
                    "entered_value": entry["entered_value"],
                    "declared_rate": declared_rate["general_rate"],
                    "proposed_rate": proposed_rate["general_rate"],
                    "declared_duty": _decimal_string(declared_duty),
                    "proposed_duty": _decimal_string(proposed_duty),
                    "potential_base_duty_difference": _decimal_string(difference),
                }
            )

        total_difference = _money(total_declared - total_proposed)
        return {
            "client_id": client_id,
            "sku_id": sku_id,
            "declared_code": declared_code,
            "proposed_code": proposed_code,
            "source_revision": self.repository.source_revision,
            "scope": "Column 1 General base duty only",
            "entries": line_results,
            "declared_duty": _decimal_string(total_declared),
            "proposed_duty": _decimal_string(total_proposed),
            "potential_base_duty_difference": _decimal_string(total_difference),
            "direction": (
                "potential_overpayment"
                if total_difference > 0
                else "potential_underpayment"
                if total_difference < 0
                else "no_difference"
            ),
            "disclaimer": "Potential base-duty difference only; not a guaranteed refund or complete duty liability.",
        }

