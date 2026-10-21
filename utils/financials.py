"""Deterministic financial calculations.

Every function here is pure: same input, same output, no API calls.
If an input is missing or a ratio is not meaningful, the result's value
is None and its status explains why. Nothing is estimated or filled in.
"""
from __future__ import annotations

from typing import Dict, Optional

from utils.schemas import FinancialPeriod, MetricResult

# Names of every metric this module can produce. The config validator
# uses this list to catch typos in scoring.yaml.
LEVEL_METRICS = (
    "current_ratio",
    "cash_ratio",
    "liabilities_to_equity",
    "stockholders_equity",
    "net_margin",
    "operating_margin",
    "interest_coverage",
    "ocf_to_current_liabilities",
)
CHANGE_METRICS = (
    "revenue_growth",
    "net_income_change",
    "operating_cash_flow_change",
    "net_margin_change_pp",
    "current_ratio_change",
)
ALL_METRICS = LEVEL_METRICS + CHANGE_METRICS


def _missing(inputs: Dict[str, Optional[float]]) -> list:
    return [name for name, value in inputs.items() if value is None]


def _ratio(name: str, period: FinancialPeriod, numerator: str, denominator: str) -> MetricResult:
    """numerator / denominator, with honest handling of gaps."""
    num = period.value(numerator)
    den = period.value(denominator)
    inputs = {numerator: num, denominator: den}
    common = dict(
        name=name,
        formula=f"{numerator} / {denominator}",
        inputs=inputs,
        sources=period.sources([numerator, denominator]),
    )

    missing = _missing(inputs)
    if missing:
        return MetricResult(
            value=None, status="missing_input", note="Not reported: " + ", ".join(missing), **common
        )
    if den == 0:
        return MetricResult(
            value=None, status="zero_denominator", note=f"{denominator} is zero", **common
        )
    return MetricResult(value=num / den, status="ok", **common)


def _liabilities_to_equity(period: FinancialPeriod) -> MetricResult:
    result = _ratio("liabilities_to_equity", period, "TotalLiabilities", "StockholdersEquity")
    equity = period.value("StockholdersEquity")
    if result.status == "ok" and equity is not None and equity < 0:
        # A ratio against negative equity flips sign and misleads.
        # The negative_equity rule covers this case instead.
        return result.model_copy(
            update={
                "value": None,
                "status": "not_meaningful",
                "note": "Equity is negative, so the ratio is not meaningful",
            }
        )
    return result


def _passthrough(name: str, period: FinancialPeriod, concept: str) -> MetricResult:
    value = period.value(concept)
    return MetricResult(
        name=name,
        value=value,
        formula=concept,
        inputs={concept: value},
        status="ok" if value is not None else "missing_input",
        note="" if value is not None else f"Not reported: {concept}",
        sources=period.sources([concept]),
    )


def compute_metrics(period: FinancialPeriod) -> Dict[str, MetricResult]:
    """All single-period metrics for one reporting period."""
    metrics = [
        _ratio("current_ratio", period, "CurrentAssets", "CurrentLiabilities"),
        _ratio("cash_ratio", period, "Cash", "CurrentLiabilities"),
        _liabilities_to_equity(period),
        _passthrough("stockholders_equity", period, "StockholdersEquity"),
        _ratio("net_margin", period, "NetIncome", "Revenue"),
        _ratio("operating_margin", period, "OperatingIncome", "Revenue"),
        _ratio("interest_coverage", period, "OperatingIncome", "InterestExpense"),
        _ratio("ocf_to_current_liabilities", period, "OperatingCashFlow", "CurrentLiabilities"),
    ]
    return {m.name: m for m in metrics}


def _pct_change(name: str, current: FinancialPeriod, prior: FinancialPeriod, concept: str) -> MetricResult:
    """(current - prior) / |prior|, as a fraction (0.05 means +5%)."""
    cur = current.value(concept)
    pri = prior.value(concept)
    inputs = {f"{concept} ({current.label})": cur, f"{concept} ({prior.label})": pri}
    common = dict(
        name=name,
        formula=f"({concept} current - {concept} prior) / |{concept} prior|",
        inputs=inputs,
        sources=current.sources([concept]) + [
            s for s in prior.sources([concept]) if s not in current.sources([concept])
        ],
    )
    missing = _missing(inputs)
    if missing:
        return MetricResult(
            value=None, status="missing_input", note="Not reported: " + ", ".join(missing), **common
        )
    if pri == 0:
        return MetricResult(
            value=None, status="zero_denominator", note=f"Prior {concept} is zero", **common
        )
    return MetricResult(value=(cur - pri) / abs(pri), status="ok", **common)


def _difference(
    name: str,
    formula: str,
    current_metric: MetricResult,
    prior_metric: MetricResult,
    scale: float = 1.0,
) -> MetricResult:
    """Change in an already-calculated metric between two periods."""
    inputs = {"current": current_metric.value, "prior": prior_metric.value}
    sources = list(dict.fromkeys(current_metric.sources + prior_metric.sources))
    if current_metric.value is None or prior_metric.value is None:
        return MetricResult(
            name=name,
            value=None,
            formula=formula,
            inputs=inputs,
            status="missing_input",
            note=f"{current_metric.name} unavailable in one or both periods",
            sources=sources,
        )
    return MetricResult(
        name=name,
        value=(current_metric.value - prior_metric.value) * scale,
        formula=formula,
        inputs=inputs,
        status="ok",
        sources=sources,
    )


def compute_changes(current: FinancialPeriod, prior: FinancialPeriod) -> Dict[str, MetricResult]:
    """Period-over-period changes. current must end after prior."""
    if current.period_end <= prior.period_end:
        raise ValueError(
            f"Current period ({current.period_end}) must end after prior period ({prior.period_end})"
        )
    cur_m = compute_metrics(current)
    pri_m = compute_metrics(prior)
    changes = [
        _pct_change("revenue_growth", current, prior, "Revenue"),
        _pct_change("net_income_change", current, prior, "NetIncome"),
        _pct_change("operating_cash_flow_change", current, prior, "OperatingCashFlow"),
        _difference(
            "net_margin_change_pp",
            "(net_margin current - net_margin prior) x 100",
            cur_m["net_margin"],
            pri_m["net_margin"],
            scale=100.0,
        ),
        _difference(
            "current_ratio_change",
            "current_ratio current - current_ratio prior",
            cur_m["current_ratio"],
            pri_m["current_ratio"],
        ),
    ]
    return {m.name: m for m in changes}


def compute_all(current: FinancialPeriod, prior: Optional[FinancialPeriod] = None) -> Dict[str, MetricResult]:
    """Current-period metrics plus changes when a prior period is given."""
    results = compute_metrics(current)
    if prior is not None:
        results.update(compute_changes(current, prior))
    return results
