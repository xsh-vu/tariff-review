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


def test_get_catalog_preserves_requested_sku_order() -> None:
    requested = ["NF-CE-002", "NF-DW-001", "NF-PL-003"]

    records = tools.get_catalog("northfield-home-goods", requested)["records"]

    assert [record["sku_id"] for record in records] == requested


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


def test_search_hts_batch_keeps_matches_grouped_by_query() -> None:
    result = tools.search_hts_batch(["9617.00.1000", "7323.93.0080"])

    assert [group["query"] for group in result["results"]] == [
        "9617.00.1000",
        "7323.93.0080",
    ]
    assert result["results"][0]["matches"][0]["code"] == "9617.00.1000"
    assert result["results"][1]["matches"][0]["code"] == "7323.93.0080"


def test_search_rulings_batch_returns_full_citation_records() -> None:
    result = tools.search_rulings_batch(["N321134", "N224817"])
    matches = [
        match for group in result["results"] for match in group["matches"]
    ]

    assert {match["ruling_id"] for match in matches} == {"N321134", "N224817"}
    assert all(match["source_url"].startswith("https://rulings.cbp.gov/") for match in matches)


def test_search_batches_reject_duplicate_queries() -> None:
    with pytest.raises(DataError, match="duplicates"):
        tools.search_hts_batch(["vacuum", "vacuum"])
    with pytest.raises(DataError, match="duplicates"):
        tools.search_rulings_batch(["N321134", "N321134"])


def test_batch_searches_handle_model_style_natural_language_queries() -> None:
    hts = tools.search_hts_batch(
        ["stainless steel drinking tumbler double wall no vacuum table kitchen household articles 7323"]
    )
    rulings = tools.search_rulings_batch(["double-wall no vacuum"])

    assert hts["results"][0]["matches"][0]["code"] == "7323.93.0080"
    assert {record["ruling_id"] for record in rulings["results"][0]["matches"]} >= {
        "N241154",
        "N321134",
    }
