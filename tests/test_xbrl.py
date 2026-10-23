from datetime import date

import pytest

from tests.sample_sec import ACC_10K, ACC_10Q, ACC_10Q_PRIOR_YEAR, COMPANYFACTS, fact, usd
from utils.financials import compute_all
from utils.xbrl import select_periods


def tenk():
    return select_periods(COMPANYFACTS, ACC_10K, date(2025, 12, 31), "10-K")


def test_current_and_prior_values_from_the_filing():
    current, prior, _ = tenk()
    assert current.value("Revenue") == 700_000_000
    assert prior.value("Revenue") == 1_000_000_000
    assert current.value("CurrentAssets") == 200_000_000
    assert prior.value("CurrentAssets") == 300_000_000
    assert prior.period_end == date(2024, 12, 31)


def test_quarter_inside_10k_is_ignored():
    current, _, _ = tenk()
    assert current.value("Revenue") != 160_000_000


def test_tag_fallback_is_recorded():
    current, _, _ = tenk()
    assert current.facts["Revenue"].source_tag == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_prior_value_comes_from_same_filing_when_available():
    _, prior, _ = tenk()
    assert prior.facts["Revenue"].accession == ACC_10K


def test_missing_concept_is_noted_not_invented():
    current, _, notes = tenk()
    assert current.value("TotalLiabilities") is None
    assert any(n.startswith("TotalLiabilities") for n in notes)


def test_metrics_and_flags_work_on_selected_periods():
    current, prior, _ = tenk()
    m = compute_all(current, prior)
    assert m["current_ratio"].value == pytest.approx(200 / 300)
    assert m["revenue_growth"].value == pytest.approx(-0.30)
    assert m["liabilities_to_equity"].status == "missing_input"
    assert m["current_ratio"].sources == [ACC_10K]


def test_conflicting_duplicates_are_rejected():
    facts = {
        "facts": {
            "us-gaap": {
                "AssetsCurrent": usd(
                    fact(None, "2025-12-31", 100, ACC_10K),
                    fact(None, "2025-12-31", 999, ACC_10K),
                )
            }
        }
    }
    current, _, notes = select_periods(facts, ACC_10K, date(2025, 12, 31), "10-K")
    assert current is None
    assert any("conflicting values" in n for n in notes)


def test_10q_cash_flow_uses_year_to_date_and_says_so():
    current, prior, notes = select_periods(COMPANYFACTS, ACC_10Q, date(2026, 6, 30), "10-Q")
    ocf = current.facts["OperatingCashFlow"]
    assert ocf.value == -12_000_000
    assert "(year-to-date)" in ocf.source_tag
    assert prior.value("OperatingCashFlow") == 25_000_000
    assert any("year-to-date" in n for n in notes)


def test_10q_balance_sheet_prior_comes_from_last_years_10q():
    current, prior, _ = select_periods(COMPANYFACTS, ACC_10Q, date(2026, 6, 30), "10-Q")
    assert current.value("Cash") == 35_000_000
    assert prior.facts["Cash"].accession == ACC_10Q_PRIOR_YEAR


def test_no_data_at_all():
    current, prior, notes = select_periods({"facts": {}}, ACC_10K, date(2025, 12, 31), "10-K")
    assert current is None and prior is None
    assert len(notes) == 1
    assert f"has no financial figures for filing {ACC_10K}" in notes[0]
