"""SYNTHETIC SEC responses for tests. Field names follow SEC's real formats
(columnar submissions arrays; companyfacts -> us-gaap -> tag -> units -> USD).
All companies, numbers and accession numbers are invented."""
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
CIK = "0000999999"
ACC_10K = "0000999999-26-000010"
ACC_10K_PRIOR = "0000999999-25-000010"
ACC_10Q = "0000999999-26-000030"
ACC_10Q_PRIOR_YEAR = "0000999999-25-000030"

TICKERS = {
    "0": {"cik_str": 999999, "ticker": "EXMC", "title": "Example Manufacturing Corp"},
    "1": {"cik_str": 888888, "ticker": "BRK-B", "title": "Example Holdings Class B"},
}

SUBMISSIONS = {
    "cik": "999999",
    "name": "Example Manufacturing Corp",
    "sic": "3829",
    "sicDescription": "Measuring & Controlling Devices",
    "filings": {
        "recent": {
            # newest first, as SEC lists them
            "accessionNumber": ["0000999999-26-000040", ACC_10Q, "0000999999-26-000020", ACC_10K, ACC_10K_PRIOR],
            "filingDate": ["2026-08-15", "2026-08-01", "2026-03-30", "2026-02-20", "2025-02-21"],
            "reportDate": ["2026-08-14", "2026-06-30", "2025-12-31", "2025-12-31", "2024-12-31"],
            "form": ["8-K", "10-Q", "10-K/A", "10-K", "10-K"],
            "primaryDocument": ["ex8k.htm", "exmc-20260630.htm", "exmc-10ka.htm", "exmc-20251231.htm", "exmc-20241231.htm"],
        }
    },
}

def fact(start, end, val, accn, form="10-K", fy=2025, fp="FY", filed="2026-02-20"):
    f = {"end": end, "val": val, "accn": accn, "fy": fy, "fp": fp, "form": form, "filed": filed}
    if start:
        f["start"] = start
    return f


def usd(*facts):
    return {"units": {"USD": list(facts)}}


# FY2025 10-K shows FY2025 and FY2024 (comparative) values.
# Synthetic "stressed" company: illiquid, loss-making, shrinking.
COMPANYFACTS = {
    "cik": 999999,
    "entityName": "Example Manufacturing Corp",
    "facts": {
        "us-gaap": {
            # Revenues is absent, so the second tag in CONCEPT_TAGS must be used
            "RevenueFromContractWithCustomerExcludingAssessedTax": usd(
                fact("2025-01-01", "2025-12-31", 700_000_000, ACC_10K),
                fact("2024-01-01", "2024-12-31", 1_000_000_000, ACC_10K),
                fact("2025-10-01", "2025-12-31", 160_000_000, ACC_10K),  # a quarter inside the 10-K: must be ignored
                fact("2024-01-01", "2024-12-31", 1_000_000_000, ACC_10K_PRIOR, filed="2025-02-21"),
            ),
            "NetIncomeLoss": usd(
                fact("2025-01-01", "2025-12-31", -50_000_000, ACC_10K),
                fact("2024-01-01", "2024-12-31", 30_000_000, ACC_10K),
            ),
            "OperatingIncomeLoss": usd(
                fact("2025-01-01", "2025-12-31", 20_000_000, ACC_10K),
                fact("2024-01-01", "2024-12-31", 90_000_000, ACC_10K),
            ),
            "InterestExpense": usd(
                fact("2025-01-01", "2025-12-31", 15_000_000, ACC_10K),
                fact("2024-01-01", "2024-12-31", 15_000_000, ACC_10K),
            ),
            "AssetsCurrent": usd(
                fact(None, "2025-12-31", 200_000_000, ACC_10K),
                fact(None, "2024-12-31", 300_000_000, ACC_10K),
            ),
            "LiabilitiesCurrent": usd(
                fact(None, "2025-12-31", 300_000_000, ACC_10K),
                fact(None, "2024-12-31", 280_000_000, ACC_10K),
            ),
            # "Liabilities" deliberately missing: leverage must be "not assessed"
            "StockholdersEquity": usd(
                fact(None, "2025-12-31", 200_000_000, ACC_10K),
                fact(None, "2024-12-31", 250_000_000, ACC_10K),
            ),
            "NetCashProvidedByUsedInOperatingActivities": usd(
                fact("2025-01-01", "2025-12-31", -30_000_000, ACC_10K),
                fact("2024-01-01", "2024-12-31", 60_000_000, ACC_10K),
                # 10-Q: cash flow is year-to-date (6 months) only
                fact("2026-01-01", "2026-06-30", -12_000_000, ACC_10Q, form="10-Q", fy=2026, fp="Q2", filed="2026-08-01"),
                fact("2025-01-01", "2025-06-30", 25_000_000, ACC_10Q, form="10-Q", fy=2026, fp="Q2", filed="2026-08-01"),
            ),
            "CashAndCashEquivalentsAtCarryingValue": usd(
                fact(None, "2025-12-31", 40_000_000, ACC_10K),
                fact(None, "2024-12-31", 70_000_000, ACC_10K),
                fact(None, "2026-06-30", 35_000_000, ACC_10Q, form="10-Q", fy=2026, fp="Q2", filed="2026-08-01"),
                # 10-Q balance sheet compares with year end, so the year-earlier
                # figure comes from last year's 10-Q
                fact(None, "2025-06-30", 55_000_000, ACC_10Q_PRIOR_YEAR, form="10-Q", fy=2025, fp="Q2", filed="2025-08-01"),
            ),
        }
    },
}


def tickers_url():
    return "https://www.sec.gov/files/company_tickers.json"


def submissions_url(cik=CIK):
    return f"https://data.sec.gov/submissions/CIK{cik}.json"


def facts_url(cik=CIK):
    return f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


def doc_url_10k():
    return f"https://www.sec.gov/Archives/edgar/data/999999/{ACC_10K.replace('-', '')}/exmc-20251231.htm"


def sample_10k_html() -> bytes:
    return (FIXTURES / "sample_10k.html").read_bytes()


class FakeResponse:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content


class FakeSession:
    """Stands in for requests.Session. routes: url -> list of (status, body)
    returned in order (the last one repeats)."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        if url not in self.routes:
            return FakeResponse(404)
        queue = self.routes[url]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        status, body = item
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        return FakeResponse(status, body)


def standard_routes():
    return {
        tickers_url(): [(200, TICKERS)],
        submissions_url(): [(200, SUBMISSIONS)],
        facts_url(): [(200, COMPANYFACTS)],
        doc_url_10k(): [(200, sample_10k_html())],
    }


# ---------------------------------------------------------------------------
# SYNTHETIC foreign private issuer filing a 20-F under IFRS, in euros
# ---------------------------------------------------------------------------

FOREIGN_CIK = "0000777777"
ACC_20F = "0000777777-26-000005"
ACC_20F_PRIOR = "0000777777-25-000005"

TICKERS["2"] = {"cik_str": 777777, "ticker": "EXOV", "title": "Example Overseas Plc"}
TICKERS["3"] = {"cik_str": 666666, "ticker": "EXCA", "title": "Example Canada Corp"}

FOREIGN_SUBMISSIONS = {
    "name": "Example Overseas Plc",
    "sic": "3674",
    "sicDescription": "Semiconductors & Related Devices",
    "filings": {
        "recent": {
            "accessionNumber": ["0000777777-26-000009", "0000777777-26-000007", ACC_20F, ACC_20F_PRIOR],
            "filingDate": ["2026-07-15", "2026-05-02", "2026-04-10", "2025-04-11"],
            "reportDate": ["2026-07-15", "2025-12-31", "2025-12-31", "2024-12-31"],
            "form": ["6-K", "20-F/A", "20-F", "20-F"],
            "primaryDocument": ["ex6k.htm", "exov-20fa.htm", "exov-20251231.htm", "exov-20241231.htm"],
        }
    },
}

CANADIAN_SUBMISSIONS = {
    "name": "Example Canada Corp",
    "filings": {
        "recent": {
            "accessionNumber": ["0000666666-26-000001"],
            "filingDate": ["2026-03-20"],
            "reportDate": ["2025-12-31"],
            "form": ["40-F"],
            "primaryDocument": ["annual40f.htm"],
        }
    },
}


def eur(*facts):
    return {"units": {"EUR": list(facts)}}


def ffact(start, end, val, accn=ACC_20F, filed="2026-04-10"):
    return fact(start, end, val, accn, form="20-F", fy=2025, fp="FY", filed=filed)


IFRS_COMPANYFACTS = {
    "cik": 777777,
    "entityName": "Example Overseas Plc",
    "facts": {
        "ifrs-full": {
            "Revenue": eur(ffact("2025-01-01", "2025-12-31", 5_000_000_000), ffact("2024-01-01", "2024-12-31", 4_500_000_000)),
            "ProfitLoss": eur(ffact("2025-01-01", "2025-12-31", 400_000_000), ffact("2024-01-01", "2024-12-31", 380_000_000)),
            "ProfitLossFromOperatingActivities": eur(
                ffact("2025-01-01", "2025-12-31", 600_000_000), ffact("2024-01-01", "2024-12-31", 550_000_000)),
            # No InterestExpense tag: FinanceCosts must be used and flagged
            "FinanceCosts": eur(ffact("2025-01-01", "2025-12-31", 100_000_000), ffact("2024-01-01", "2024-12-31", 90_000_000)),
            "CurrentAssets": eur(ffact(None, "2025-12-31", 2_000_000_000), ffact(None, "2024-12-31", 2_200_000_000)),
            "CurrentLiabilities": eur(ffact(None, "2025-12-31", 2_500_000_000), ffact(None, "2024-12-31", 2_000_000_000)),
            # No total Liabilities tag: leverage must be "not assessed"
            "Equity": eur(ffact(None, "2025-12-31", 3_000_000_000), ffact(None, "2024-12-31", 2_800_000_000)),
            "CashFlowsFromUsedInOperatingActivities": eur(
                ffact("2025-01-01", "2025-12-31", 700_000_000), ffact("2024-01-01", "2024-12-31", 650_000_000)),
            "CashAndCashEquivalents": eur(ffact(None, "2025-12-31", 500_000_000), ffact(None, "2024-12-31", 450_000_000)),
        },
        # A stray US GAAP value must not make the filing look like a US GAAP filer
        "us-gaap": {"Revenues": usd(fact("2025-01-01", "2025-12-31", 1, ACC_20F))},
    },
}


def doc_url_20f():
    return f"https://www.sec.gov/Archives/edgar/data/777777/{ACC_20F.replace('-', '')}/exov-20251231.htm"


def sample_20f_html() -> bytes:
    return (FIXTURES / "sample_20f.html").read_bytes()


def foreign_routes():
    routes = standard_routes()
    routes.update({
        submissions_url(FOREIGN_CIK): [(200, FOREIGN_SUBMISSIONS)],
        facts_url(FOREIGN_CIK): [(200, IFRS_COMPANYFACTS)],
        doc_url_20f(): [(200, sample_20f_html())],
        submissions_url("0000666666"): [(200, CANADIAN_SUBMISSIONS)],
    })
    return routes
