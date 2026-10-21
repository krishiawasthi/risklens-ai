"""SYNTHETIC test data. These numbers are invented for testing only.
They do not describe any real company."""
from datetime import date

from utils.schemas import Fact, FinancialPeriod


def make_period(label, period_end, accession="0000000000-00-000001", **values):
    facts = {
        concept: Fact(
            concept=concept,
            value=value,
            period_end=period_end,
            form="10-K",
            accession=accession,
        )
        for concept, value in values.items()
    }
    return FinancialPeriod(label=label, period_end=period_end, facts=facts)


def healthy_current():
    return make_period(
        "FY2025",
        date(2025, 12, 31),
        accession="0000000000-26-000001",
        Revenue=1000.0,
        NetIncome=100.0,
        OperatingIncome=150.0,
        InterestExpense=10.0,
        CurrentAssets=500.0,
        CurrentLiabilities=250.0,
        TotalLiabilities=600.0,
        StockholdersEquity=400.0,
        OperatingCashFlow=180.0,
        Cash=120.0,
    )


def healthy_prior():
    return make_period(
        "FY2024",
        date(2024, 12, 31),
        accession="0000000000-25-000001",
        Revenue=800.0,
        NetIncome=60.0,
        OperatingIncome=110.0,
        InterestExpense=10.0,
        CurrentAssets=450.0,
        CurrentLiabilities=300.0,
        TotalLiabilities=550.0,
        StockholdersEquity=350.0,
        OperatingCashFlow=140.0,
        Cash=100.0,
    )


def stressed_current():
    """Loss-making, illiquid, highly leveraged, shrinking."""
    return make_period(
        "FY2025",
        date(2025, 12, 31),
        accession="0000000000-26-000002",
        Revenue=700.0,
        NetIncome=-50.0,
        OperatingIncome=20.0,
        InterestExpense=15.0,
        CurrentAssets=200.0,
        CurrentLiabilities=300.0,
        TotalLiabilities=900.0,
        StockholdersEquity=200.0,
        OperatingCashFlow=-30.0,
        Cash=40.0,
    )


def stressed_prior():
    return make_period(
        "FY2024",
        date(2024, 12, 31),
        accession="0000000000-25-000002",
        Revenue=1000.0,
        NetIncome=30.0,
        OperatingIncome=90.0,
        InterestExpense=15.0,
        CurrentAssets=300.0,
        CurrentLiabilities=280.0,
        TotalLiabilities=850.0,
        StockholdersEquity=250.0,
        OperatingCashFlow=60.0,
        Cash=70.0,
    )
