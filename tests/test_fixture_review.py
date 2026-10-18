from agent.fixture_review import FixtureReviewer


def test_required_demo_outcomes_and_totals() -> None:
    result = FixtureReviewer().review(
        ["NF-DW-001", "NF-DW-002", "NF-DW-003", "NF-DW-004"]
    )
    outcomes = {
        finding["sku_id"]: finding["outcome"]
        for finding in result["proposal"]["findings"]
    }
    assert outcomes == {
        "NF-DW-001": "potential_overpayment",
        "NF-DW-002": "potential_underpayment",
        "NF-DW-003": "needs_info",
        "NF-DW-004": "confirmed",
    }
    assert result["potential_overpayment_total"] == "12480.00"
    assert result["potential_underpayment_total"] == "6240.00"


def test_all_twelve_fixture_totals() -> None:
    reviewer = FixtureReviewer()
    result = reviewer.review(
        [product["sku_id"] for product in reviewer.repository.get_catalog("northfield-home-goods")]
    )
    assert result["potential_overpayment_total"] == "20570.00"
    assert result["potential_underpayment_total"] == "14860.00"


def test_ambiguous_product_does_not_guess() -> None:
    finding = FixtureReviewer().review(["NF-CE-003"])["proposal"]["findings"][0]
    assert finding["outcome"] == "needs_info"
    assert finding["proposed_code"] is None
    assert finding["missing_fact"]
