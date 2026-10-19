from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "data" / "source_data"


class DataError(ValueError):
    """Raised when a requested fixture or evidence record is invalid."""


_SEARCH_STOP_WORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def _search_terms(value: str) -> list[str]:
    return [
        term
        for term in re.findall(r"[a-z0-9]+", value.lower())
        if term not in _SEARCH_STOP_WORDS
    ]


def _search_score(query: str, haystack: str) -> int:
    """Score a tiny verified index without introducing fuzzy external evidence."""
    query_terms = _search_terms(query)
    haystack_terms = set(_search_terms(haystack))
    if not query_terms:
        return 0
    normalized_query = " ".join(query_terms)
    normalized_haystack = " ".join(_search_terms(haystack))
    compact_query = "".join(query_terms)
    compact_haystack = "".join(_search_terms(haystack))
    if normalized_query in normalized_haystack or compact_query in compact_haystack:
        return 1000 + len(query_terms)
    overlap = sum(1 for term in set(query_terms) if term in haystack_terms)
    minimum_overlap = 1 if len(set(query_terms)) == 1 else 2
    return overlap if overlap >= minimum_overlap else 0


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
            products_by_sku = {p["sku_id"]: p for p in selected}
            selected = [products_by_sku[sku_id] for sku_id in sku_ids]
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
        scored = []
        for index, item in enumerate(self._rate_document["rates"]):
            score = _search_score(
                normalized, f"{item['code']} {item['description']}"
            )
            if score:
                scored.append((score, index, item))
        scored.sort(key=lambda match: (-match[0], match[1]))
        return deepcopy([item for _, _, item in scored[:limit]])

    def search_rulings(
        self, query: str, family: str | None = None, limit: int = 8
    ) -> list[dict[str, Any]]:
        normalized = query.strip().lower()
        if not normalized:
            raise DataError("query must not be empty")
        if not 1 <= limit <= 20:
            raise DataError("limit must be between 1 and 20")
        matches = []
        for index, ruling in enumerate(self._rulings):
            haystack = " ".join(
                [
                    ruling["ruling_id"],
                    ruling["family"],
                    ruling["code"],
                    ruling["summary"],
                ]
            ).lower()
            score = _search_score(normalized, haystack)
            if score and (family is None or ruling["family"] == family):
                matches.append((score, index, ruling))
        matches.sort(key=lambda match: (-match[0], match[1]))
        return deepcopy([ruling for _, _, ruling in matches[:limit]])

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


class HistoricalEvidenceRepository:
    """Date-bounded HTS evidence used only by the held-out evaluation runner."""

    def __init__(self) -> None:
        self._document: dict[str, Any] = _load_json("historical_hts.json")

    @property
    def dataset_id(self) -> str:
        return str(self._document["dataset_id"])

    @property
    def version(self) -> int:
        return int(self._document["version"])

    def snapshot_for(self, as_of_date: str) -> dict[str, Any]:
        try:
            requested = date.fromisoformat(as_of_date)
        except (TypeError, ValueError) as exc:
            raise DataError("as_of_date must be an ISO date") from exc

        matches = []
        for snapshot in self._document["snapshots"]:
            valid_from = date.fromisoformat(snapshot["valid_from"])
            valid_through = date.fromisoformat(snapshot["valid_through"])
            if valid_from <= requested <= valid_through:
                matches.append(snapshot)
        if len(matches) != 1:
            raise DataError(
                f"No unique verified historical HTS snapshot for {as_of_date}"
            )
        snapshot = matches[0]
        if date.fromisoformat(snapshot["published_on"]) > requested:
            raise DataError(
                f"Historical HTS snapshot for {as_of_date} was published later"
            )
        return deepcopy(snapshot)

    def search_hts(
        self, as_of_date: str, query: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        snapshot = self.snapshot_for(as_of_date)
        normalized = query.strip().lower()
        if not normalized:
            raise DataError("query must not be empty")
        if not 1 <= limit <= 20:
            raise DataError("limit must be between 1 and 20")
        requested = date.fromisoformat(as_of_date)
        scored = []
        for index, item in enumerate(self._document["provisions"]):
            available_from = date.fromisoformat(item["available_from"])
            available_through = (
                date.fromisoformat(item["available_through"])
                if item["available_through"]
                else None
            )
            if requested < available_from or (
                available_through is not None and requested > available_through
            ):
                continue
            score = _search_score(
                normalized,
                " ".join(
                    [
                        item["code"],
                        item["description"],
                        item["search_terms"],
                    ]
                ),
            )
            if score:
                record = {
                    key: deepcopy(value)
                    for key, value in item.items()
                    if key not in {"available_from", "available_through", "search_terms"}
                }
                record.update(
                    {
                        "as_of_date": as_of_date,
                        "revision_id": snapshot["revision_id"],
                        "revision_published_on": snapshot["published_on"],
                        "source_url": snapshot["source_url"],
                        "verification_method": snapshot["verification_method"],
                    }
                )
                scored.append((score, index, record))
        scored.sort(key=lambda match: (-match[0], match[1]))
        return [record for _, _, record in scored[:limit]]

