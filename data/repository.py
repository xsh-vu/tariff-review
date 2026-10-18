from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "data" / "source_data"


class DataError(ValueError):
    """Raised when a requested fixture or evidence record is invalid."""


def _load_json(name: str) -> Any:
    with (SOURCE_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


class Repository:
    """Read-only access to the synthetic client and verified public-source cache."""

    def __init__(self) -> None:
        self._products: list[dict[str, Any]] = _load_json("products.json")
        self._entries: list[dict[str, Any]] = _load_json("entries.json")
        self._rulings: list[dict[str, Any]] = _load_json("rulings.json")
        self._rate_document: dict[str, Any] = _load_json("hts_rates.json")

    @property
    def source_revision(self) -> str:
        return str(self._rate_document["revision"])

    @property
    def rates(self) -> list[dict[str, Any]]:
        return deepcopy(self._rate_document["rates"])

    @property
    def ruling_ids(self) -> set[str]:
        return {str(item["ruling_id"]) for item in self._rulings}

    @property
    def hts_codes(self) -> set[str]:
        return {str(item["code"]) for item in self._rate_document["rates"]}

    def get_catalog(
        self, client_id: str, sku_ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        if client_id != "northfield-home-goods":
            raise DataError(f"Unknown client_id: {client_id}")
        selected = [p for p in self._products if p["client_id"] == client_id]
        if sku_ids is not None:
            requested = set(sku_ids)
            known = {p["sku_id"] for p in selected}
            missing = requested - known
            if missing:
                raise DataError(f"Unknown sku_ids: {sorted(missing)}")
            selected = [p for p in selected if p["sku_id"] in requested]
        return deepcopy(selected)

    def get_product(self, client_id: str, sku_id: str) -> dict[str, Any]:
        products = self.get_catalog(client_id, [sku_id])
        return products[0]

    def get_entries(self, client_id: str, sku_id: str) -> list[dict[str, Any]]:
        self.get_product(client_id, sku_id)
        return deepcopy(
            [
                entry
                for entry in self._entries
                if entry["client_id"] == client_id and entry["sku_id"] == sku_id
            ]
        )

    def search_hts(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        normalized = query.strip().lower()
        if not normalized:
            raise DataError("query must not be empty")
        if not 1 <= limit <= 20:
            raise DataError("limit must be between 1 and 20")
        matches = [
            item
            for item in self._rate_document["rates"]
            if normalized in item["code"].lower()
            or normalized in item["description"].lower()
        ]
        return deepcopy(matches[:limit])

    def search_rulings(
        self, query: str, family: str | None = None, limit: int = 8
    ) -> list[dict[str, Any]]:
        normalized = query.strip().lower()
        if not normalized:
            raise DataError("query must not be empty")
        if not 1 <= limit <= 20:
            raise DataError("limit must be between 1 and 20")
        matches = []
        for ruling in self._rulings:
            haystack = " ".join(
                [
                    ruling["ruling_id"],
                    ruling["family"],
                    ruling["code"],
                    ruling["summary"],
                ]
            ).lower()
            if normalized in haystack and (family is None or ruling["family"] == family):
                matches.append(ruling)
        return deepcopy(matches[:limit])

    def get_ruling(self, ruling_id: str) -> dict[str, Any]:
        for ruling in self._rulings:
            if ruling["ruling_id"].upper() == ruling_id.upper():
                return deepcopy(ruling)
        raise DataError(f"Unknown ruling_id: {ruling_id}")

    def get_rate(self, code: str) -> dict[str, Any]:
        for rate in self._rate_document["rates"]:
            if rate["code"] == code:
                return deepcopy(rate)
        raise DataError(f"Unsupported HTS code: {code}")

