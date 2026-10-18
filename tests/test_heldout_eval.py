from evals.heldout.validate import validate_dataset


def test_heldout_dataset_is_complete_and_isolated() -> None:
    result = validate_dataset()

    assert result["case_count"] == 20
    assert result["family_counts"] == {
        "stainless_drinkware": 7,
        "plastic_housewares": 7,
        "ceramic_drinkware": 6,
    }
    assert result["searchable_ruling_overlap"] == []
    assert result["gold_label_leaks"] == []


def test_heldout_dataset_does_not_claim_broker_review() -> None:
    result = validate_dataset()

    assert result["broker_review_status"] == "pending"
