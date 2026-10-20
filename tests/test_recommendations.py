from agent.fixture_review import FixtureReviewer
from app.recommendations import summarize_recommendations


def test_summary_groups_all_demo_outcomes_in_review_order() -> None:
    review = FixtureReviewer().review(
        ["NF-DW-001", "NF-DW-002", "NF-DW-003", "NF-DW-004"]
    )

    summary = summarize_recommendations(review["proposal"]["findings"])

    assert [item["outcome"] for item in summary] == [
        "potential_overpayment",
        "potential_underpayment",
        "needs_info",
        "confirmed",
    ]
    assert [item["sku_ids"] for item in summary] == [
        ["NF-DW-001"],
        ["NF-DW-002"],
        ["NF-DW-003"],
        ["NF-DW-004"],
    ]
    assert all(item["count"] == 1 for item in summary)


def test_summary_only_shows_outcomes_present_in_partial_review() -> None:
    review = FixtureReviewer().review(["NF-DW-001", "NF-DW-004"])

    summary = summarize_recommendations(review["proposal"]["findings"])

    assert [item["outcome"] for item in summary] == [
        "potential_overpayment",
        "confirmed",
    ]
    assert "approval" in summary[0]["action"].lower()
    assert "no correction" in summary[1]["action"].lower()


def test_summary_ignores_malformed_or_unknown_findings() -> None:
    summary = summarize_recommendations(
        [
            {"sku_id": "NF-DW-001", "outcome": "potential_overpayment"},
            {"sku_id": "", "outcome": "confirmed"},
            {"sku_id": "NF-UNKNOWN", "outcome": "unexpected"},
        ]
    )

    assert len(summary) == 1
    assert summary[0]["sku_ids"] == ["NF-DW-001"]
