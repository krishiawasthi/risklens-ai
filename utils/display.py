"""Labels and number formats shared by the dashboard and the Word report,
so both always show the same figure the same way."""
from __future__ import annotations

import re
from typing import Optional

CATEGORY_LABELS = {
    "business_continuity": "Business continuity",
    "cybersecurity": "Cybersecurity",
    "third_party": "Third party",
    "compliance": "Compliance",
    "governance": "Governance",
    "financial_resilience": "Financial resilience",
}

# metric name -> (label, format kind)
METRIC_INFO = {
    "current_ratio": ("Current ratio", "ratio"),
    "cash_ratio": ("Cash ratio", "ratio"),
    "liabilities_to_equity": ("Liabilities to equity", "ratio"),
    "stockholders_equity": ("Stockholders' equity", "money"),
    "net_margin": ("Net margin", "pct"),
    "operating_margin": ("Operating margin", "pct"),
    "interest_coverage": ("Interest coverage", "ratio"),
    "ocf_to_current_liabilities": ("Operating cash flow to current liabilities", "ratio"),
    "revenue_growth": ("Revenue growth", "pct_change"),
    "net_income_change": ("Net income change", "pct_change"),
    "operating_cash_flow_change": ("Operating cash flow change", "pct_change"),
    "net_margin_change_pp": ("Net margin change", "pp"),
    "current_ratio_change": ("Current ratio change", "delta"),
}

CHANGE_METRICS = {k for k, (_, kind) in METRIC_INFO.items() if kind in ("pct_change", "pp", "delta")}


def money(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1e9:
        return f"{sign}${v / 1e9:,.1f}bn"
    if v >= 1e6:
        return f"{sign}${v / 1e6:,.1f}m"
    return f"{sign}${v:,.0f}"


def fmt_metric(name: str, value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    kind = METRIC_INFO.get(name, (name, "ratio"))[1]
    if kind == "ratio":
        return f"{value:.2f}x"
    if kind == "money":
        return money(value)
    if kind == "pct":
        return f"{value * 100:.1f}%"
    if kind == "pct_change":
        return f"{value * 100:+.1f}%"
    if kind == "pp":
        return f"{value:+.1f} pp"
    return f"{value:+.2f}"


def metric_label(name: str) -> str:
    return METRIC_INFO.get(name, (name, ""))[0]


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|>~<$])")


def md_escape(text: str) -> str:
    """Escape Markdown so filing text and AI text display literally.
    '$' matters most: Streamlit would otherwise render "$5 to $10" as maths."""
    return _MD_SPECIAL.sub(r"\\\1", text or "")


def ticker_from_choice(choice) -> str:
    """Company dropdown label to ticker: 'AAPL · Apple Inc.' -> 'AAPL'.
    A plain ticker (from the fallback text box) comes back unchanged."""
    return (choice or "").split(" · ")[0].strip()
