import pytest

from data.repository import DataError
from server import tools


def test_get_catalog_applies_review_only_description_override() -> None:
    original = tools.get_catalog("northfield-home-goods", ["NF-DW-003"])[0]
    edited = tools.get_catalog(
        "northfield-home-goods",
        ["NF-DW-003"],
        {"NF-DW-003": "Laboratory-confirmed vacuum flask."},
    )[0]

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
