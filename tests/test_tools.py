import pytest

from data.repository import DataError
from server import tools


def test_get_catalog_applies_review_only_description_override() -> None:
    original = tools.get_catalog("northfield-home-goods", ["NF-DW-003"])[
        "records"
    ][0]
    edited = tools.get_catalog(
        "northfield-home-goods",
        ["NF-DW-003"],
        {"NF-DW-003": "Laboratory-confirmed vacuum flask."},
    )["records"][0]

    assert edited["description"] == "Laboratory-confirmed vacuum flask."
    assert edited["description_source"] == "review_override"
    assert original["description"] != edited["description"]


def test_get_catalog_rejects_override_for_unrequested_sku() -> None:
    with pytest.raises(DataError, match="unrequested or unknown"):
        tools.get_catalog(
            "northfield-home-goods",
            ["NF-DW-003"],
            {"NF-DW-004": "Different SKU."},
        )


def test_get_entries_returns_selected_skus_in_one_batch() -> None:
    entries = tools.get_entries(
        "northfield-home-goods", ["NF-DW-001", "NF-DW-002"]
    )["entries"]

    assert {entry["sku_id"] for entry in entries} == {"NF-DW-001", "NF-DW-002"}


def test_batch_tools_reject_duplicate_skus() -> None:
    with pytest.raises(DataError, match="duplicates"):
        tools.get_catalog(
            "northfield-home-goods", ["NF-DW-001", "NF-DW-001"]
        )
    with pytest.raises(DataError, match="duplicates"):
        tools.get_entries(
            "northfield-home-goods", ["NF-DW-001", "NF-DW-001"]
        )
