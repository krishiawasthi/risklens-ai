"""Pick financial figures for one filing out of SEC's XBRL company facts.

Company facts holds every value a company has tagged across all its
filings. For each canonical concept, this module:
  1. tries the XBRL tags in CONCEPT_TAGS in order,
  2. takes the value reported IN THIS FILING for the period the filing covers,
  3. takes the comparative value from about one year earlier, preferring the
     figure as presented in this same filing.

If a value cannot be matched exactly, it is left out and a note explains
why. Nothing is estimated, averaged or derived from other values.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from utils.schemas import Fact, FinancialPeriod

# First tag that has a value wins. Companies use different tags for the same
# line item, and some changed tags over time.
CONCEPT_TAGS: Dict[str, List[str]] = {
    "Revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "NetIncome": ["NetIncomeLoss", "ProfitLoss"],
    "OperatingIncome": ["OperatingIncomeLoss"],
    "InterestExpense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestAndDebtExpense"],
    "CurrentAssets": ["AssetsCurrent"],
    "CurrentLiabilities": ["LiabilitiesCurrent"],
    "TotalLiabilities": ["Liabilities"],
    "StockholdersEquity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "OperatingCashFlow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "Cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
}

# Income statement and cash flow items cover a period (they have a start date).
# Balance sheet items are a snapshot at one date.
DURATION_CONCEPTS = {"Revenue", "NetIncome", "OperatingIncome", "InterestExpense", "OperatingCashFlow"}

TARGET_DAYS = {"10-K": 365, "10-Q": 91}
DURATION_TOLERANCE = 20  # days; covers 52/53-week fiscal years
PRIOR_TOLERANCE = 15  # days around "one year earlier"


def _d(value: str) -> date:
    return date.fromisoformat(value)


def _usd_facts(companyfacts: dict, tag: str) -> List[dict]:
    entries = companyfacts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD", [])
    return [e for e in entries if "end" in e and "val" in e and "accn" in e]


def _days(entry: dict) -> Optional[int]:
    if "start" not in entry:
        return None
    return (_d(entry["end"]) - _d(entry["start"])).days


def _single_value(candidates: List[dict]) -> Tuple[Optional[dict], str]:
    """The same fact often appears more than once. Accept it only if every
    copy has the same value."""
    if not candidates:
        return None, ""
    values = {float(c["val"]) for c in candidates}
    if len(values) > 1:
        return None, f"conflicting values {sorted(values)}"
    return candidates[0], ""


def _pick_current(entries, concept, accession, period_end, form) -> Tuple[Optional[dict], str, bool]:
    """Returns (entry, problem, is_year_to_date)."""
    same = [e for e in entries if e["accn"] == accession and _d(e["end"]) == period_end]
    if concept not in DURATION_CONCEPTS:
        chosen, problem = _single_value([e for e in same if "start" not in e])
        return chosen, problem, False

    target = TARGET_DAYS[form]
    durations = [e for e in same if _days(e) is not None]
    exact = [e for e in durations if abs(_days(e) - target) <= DURATION_TOLERANCE]
    if exact:
        chosen, problem = _single_value(exact)
        return chosen, problem, False
    if form == "10-Q" and durations:
        # Cash flow statements in a 10-Q are usually year-to-date only.
        longest = max(_days(e) for e in durations)
        chosen, problem = _single_value([e for e in durations if _days(e) == longest])
        return chosen, problem, True
    return None, "", False


def _pick_prior(entries, current: dict, accession: str) -> Optional[dict]:
    cur_end = _d(current["end"])
    target_end = cur_end - timedelta(days=365)
    cur_days = _days(current)

    def matches(e):
        if abs((_d(e["end"]) - target_end).days) > PRIOR_TOLERANCE:
            return False
        if cur_days is None:
            return "start" not in e
        return _days(e) is not None and abs(_days(e) - cur_days) <= PRIOR_TOLERANCE

    candidates = [e for e in entries if matches(e)]
    in_same_filing = [e for e in candidates if e["accn"] == accession]
    if in_same_filing:
        chosen, _ = _single_value(in_same_filing)
        return chosen
    if candidates:
        # Not shown in this filing (common for 10-Q balance sheets). Use the
        # most recently filed figure for that date.
        return max(candidates, key=lambda e: e.get("filed", ""))
    return None


def _fact(concept: str, tag: str, entry: dict, ytd: bool) -> Fact:
    return Fact(
        concept=concept,
        value=float(entry["val"]),
        period_end=_d(entry["end"]),
        fiscal_year=entry.get("fy"),
        fiscal_period=entry.get("fp"),
        form=entry.get("form"),
        accession=entry["accn"],
        source_tag=tag + (" (year-to-date)" if ytd else ""),
    )


def select_periods(
    companyfacts: dict, accession: str, period_end: date, form: str
) -> Tuple[Optional[FinancialPeriod], Optional[FinancialPeriod], List[str]]:
    """Returns (current period, prior period or None, notes on anything missing)."""
    if form not in TARGET_DAYS:
        raise ValueError(f"Unsupported form {form}")
    current_facts: Dict[str, Fact] = {}
    prior_facts: Dict[str, Fact] = {}
    notes: List[str] = []

    for concept, tags in CONCEPT_TAGS.items():
        chosen_tag, current, ytd, problems = None, None, False, []
        for tag in tags:
            entries = _usd_facts(companyfacts, tag)
            entry, problem, is_ytd = _pick_current(entries, concept, accession, period_end, form)
            if problem:
                problems.append(f"{tag}: {problem}")
            if entry is not None:
                chosen_tag, current, ytd = tag, entry, is_ytd
                break
        if current is None:
            detail = f" ({'; '.join(problems)})" if problems else ""
            notes.append(
                f"{concept}: no USD value found in filing {accession} for the period ending {period_end}{detail}"
            )
            continue

        current_facts[concept] = _fact(concept, chosen_tag, current, ytd)
        if ytd:
            notes.append(f"{concept}: this 10-Q reports it year-to-date only, so the year-to-date figure is used")
        prior = _pick_prior(_usd_facts(companyfacts, chosen_tag), current, accession)
        if prior is None:
            notes.append(f"{concept}: no comparable figure found for about one year earlier")
        else:
            prior_facts[concept] = _fact(concept, chosen_tag, prior, ytd)

    if not current_facts:
        return None, None, notes

    noun = "Year" if form == "10-K" else "Quarter"
    current = FinancialPeriod(label=f"{noun} ended {period_end}", period_end=period_end, facts=current_facts)
    prior = None
    if prior_facts:
        prior_end = Counter(f.period_end for f in prior_facts.values()).most_common(1)[0][0]
        prior = FinancialPeriod(label=f"{noun} ended {prior_end}", period_end=prior_end, facts=prior_facts)
    return current, prior, notes
