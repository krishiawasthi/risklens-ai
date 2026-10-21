from datetime import date

import pytest

from tests.sample_data import healthy_current, healthy_prior, make_period
from utils.financials import compute_all, compute_changes, compute_metrics
from utils.schemas import Fact


def test_ratios_match_hand_calculation():
    m = compute_metrics(healthy_current())
    assert m["current_ratio"].value == pytest.approx(2.0)  # 500 / 250
    assert m["cash_ratio"].value == pytest.approx(0.48)  # 120 / 250
    assert m["liabilities_to_equity"].value == pytest.approx(1.5)  # 600 / 400
    assert m["net_margin"].value == pytest.approx(0.10)  # 100 / 1000
    assert m["operating_margin"].value == pytest.approx(0.15)  # 150 / 1000
    assert m["interest_coverage"].value == pytest.approx(15.0)  # 150 / 10
    assert m["ocf_to_current_liabilities"].value == pytest.approx(0.72)  # 180 / 250
    assert all(r.status == "ok" for r in m.values())


def test_missing_input_gives_none_not_a_guess():
    period = make_period("FY2025", date(2025, 12, 31), CurrentAssets=500.0)
    result = compute_metrics(period)["current_ratio"]
    assert result.value is None
    assert result.status == "missing_input"
    assert "CurrentLiabilities" in result.note


def test_zero_denominator():
    period = make_period(
        "FY2025", date(2025, 12, 31), OperatingIncome=100.0, InterestExpense=0.0
    )
    result = compute_metrics(period)["interest_coverage"]
    assert result.value is None
    assert result.status == "zero_denominator"


def test_negative_equity_makes_leverage_not_meaningful():
    period = make_period(
        "FY2025", date(2025, 12, 31), TotalLiabilities=500.0, StockholdersEquity=-100.0
    )
    m = compute_metrics(period)
    assert m["liabilities_to_equity"].value is None
    assert m["liabilities_to_equity"].status == "not_meaningful"
    assert m["stockholders_equity"].value == -100.0


def test_period_over_period_changes():
    c = compute_changes(healthy_current(), healthy_prior())
    assert c["revenue_growth"].value == pytest.approx(0.25)  # (1000 - 800) / 800
    assert c["net_income_change"].value == pytest.approx(100 / 60 - 1)
    assert c["net_margin_change_pp"].value == pytest.approx(10.0 - 7.5)  # 10% vs 7.5%
    assert c["current_ratio_change"].value == pytest.approx(2.0 - 1.5)


def test_change_from_negative_prior_uses_absolute_value():
    cur = make_period("FY2025", date(2025, 12, 31), NetIncome=50.0)
    pri = make_period("FY2024", date(2024, 12, 31), NetIncome=-100.0)
    result = compute_changes(cur, pri)["net_income_change"]
    assert result.value == pytest.approx(1.5)  # improved by 150 on a base of 100


def test_change_with_missing_prior_value():
    cur = make_period("FY2025", date(2025, 12, 31), Revenue=100.0)
    pri = make_period("FY2024", date(2024, 12, 31))
    result = compute_changes(cur, pri)["revenue_growth"]
    assert result.value is None
    assert result.status == "missing_input"


def test_periods_in_wrong_order_raise():
    with pytest.raises(ValueError):
        compute_changes(healthy_prior(), healthy_current())


def test_sources_are_carried_through():
    m = compute_metrics(healthy_current())
    assert m["current_ratio"].sources == ["0000000000-26-000001"]
    c = compute_changes(healthy_current(), healthy_prior())
    assert set(c["revenue_growth"].sources) == {"0000000000-26-000001", "0000000000-25-000001"}


def test_compute_all_without_prior_has_no_changes():
    results = compute_all(healthy_current())
    assert "revenue_growth" not in results
    assert "current_ratio" in results


def test_unknown_concept_rejected():
    with pytest.raises(ValueError):
        Fact(concept="MadeUpConcept", value=1.0, period_end=date(2025, 12, 31))
