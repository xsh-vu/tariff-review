from data.duty import DutyCalculator


def test_known_overpayment_is_deterministic() -> None:
    result = DutyCalculator().compute_duty_delta(
        "northfield-home-goods", "NF-DW-001", "9617.00.1000", "7323.93.0080"
    )
    assert result["declared_duty"] == "17280.00"
    assert result["proposed_duty"] == "4800.00"
    assert result["potential_base_duty_difference"] == "12480.00"
    assert result["direction"] == "potential_overpayment"


def test_known_underpayment_stays_negative() -> None:
    result = DutyCalculator().compute_duty_delta(
        "northfield-home-goods", "NF-DW-002", "7323.93.0080", "9617.00.1000"
    )
    assert result["potential_base_duty_difference"] == "-6240.00"
    assert result["direction"] == "potential_underpayment"
