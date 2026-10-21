"""Deterministic risk scoring.

All weights and thresholds come from config/scoring.yaml. The config is
validated when it is loaded, so a typo fails immediately with a clear
message instead of producing a wrong register.
"""
from __future__ import annotations

import operator
from pathlib import Path
from typing import Dict, List, Literal, Tuple, Union

import yaml
from pydantic import BaseModel, ValidationError, model_validator

from utils.filing_text import SECTION_SPECS
from utils.financials import ALL_METRICS
from utils.schemas import MetricResult, NotAssessed, RiskCategory, RiskFlag

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "scoring.yaml"

ALL_CATEGORIES = (
    "business_continuity",
    "cybersecurity",
    "third_party",
    "compliance",
    "governance",
    "financial_resilience",
)

OPERATORS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


class ConfigError(Exception):
    """Raised when scoring.yaml is missing or invalid."""


class Scale(BaseModel):
    min: int
    max: int


class PriorityBand(BaseModel):
    name: str
    min_score: float


class FinancialRule(BaseModel):
    id: str
    title: str
    metric: str
    operator: Literal["<", "<=", ">", ">="]
    threshold: float
    likelihood: int
    impact: int
    category: RiskCategory = "financial_resilience"
    follow_up_questions: List[str] = []


class EvidenceSettings(BaseModel):
    min_quote_words: int = 6


class ConfidenceSettings(BaseModel):
    high_min_paragraphs: int = 3
    high_min_paragraphs_if_corroborated: int = 2
    medium_min_paragraphs: int = 2


class ExtractionSettings(BaseModel):
    max_chars_per_batch: int = 60000
    max_findings_per_batch: int = 6
    sections: Dict[str, List[str]] = {"10-K": ["1A", "1C", "3", "9A"], "10-Q": ["1A", "1", "4"]}


class ScoringConfig(BaseModel):
    likelihood_scale: Scale
    impact_scale: Scale
    category_weights: Dict[RiskCategory, float]
    priority_bands: List[PriorityBand]
    financial_rules: List[FinancialRule]
    evidence: EvidenceSettings = EvidenceSettings()
    confidence: ConfidenceSettings = ConfidenceSettings()
    extraction: ExtractionSettings = ExtractionSettings()

    @model_validator(mode="after")
    def check_consistency(self) -> "ScoringConfig":
        if self.evidence.min_quote_words < 1:
            raise ValueError("evidence.min_quote_words must be at least 1")
        c = self.confidence
        if not (c.high_min_paragraphs >= c.medium_min_paragraphs >= 2):
            raise ValueError("confidence: need high_min_paragraphs >= medium_min_paragraphs >= 2")
        if not (c.medium_min_paragraphs <= c.high_min_paragraphs_if_corroborated <= c.high_min_paragraphs):
            raise ValueError("confidence: high_min_paragraphs_if_corroborated must sit between medium and high")
        if self.extraction.max_chars_per_batch < 1000 or self.extraction.max_findings_per_batch < 1:
            raise ValueError("extraction settings are too small")
        for form, items in self.extraction.sections.items():
            if form not in SECTION_SPECS:
                raise ValueError(f"extraction.sections: unsupported form '{form}'")
            unknown = [i for i in items if i.lower() not in SECTION_SPECS[form]]
            if unknown:
                known = ", ".join(k.upper() for k in SECTION_SPECS[form])
                raise ValueError(f"extraction.sections {form}: unknown items {unknown}. Known: {known}")
            if not items:
                raise ValueError(f"extraction.sections {form}: list at least one item")

        missing = [c for c in ALL_CATEGORIES if c not in self.category_weights]
        if missing:
            raise ValueError(f"category_weights is missing: {missing}")
        for cat, weight in self.category_weights.items():
            if weight < 0:
                raise ValueError(f"Weight for {cat} must not be negative")

        mins = [b.min_score for b in self.priority_bands]
        if not mins:
            raise ValueError("priority_bands must not be empty")
        if mins != sorted(mins, reverse=True):
            raise ValueError("priority_bands must be ordered from highest min_score to lowest")
        if mins[-1] != 0:
            raise ValueError("The last priority band must have min_score 0")

        seen = set()
        for rule in self.financial_rules:
            if rule.id in seen:
                raise ValueError(f"Duplicate rule id: {rule.id}")
            seen.add(rule.id)
            if rule.metric not in ALL_METRICS:
                raise ValueError(f"Rule {rule.id} uses unknown metric '{rule.metric}'")
            if not self.likelihood_scale.min <= rule.likelihood <= self.likelihood_scale.max:
                raise ValueError(f"Rule {rule.id} likelihood is outside the scale")
            if not self.impact_scale.min <= rule.impact <= self.impact_scale.max:
                raise ValueError(f"Rule {rule.id} impact is outside the scale")
        return self


def load_config(path: Union[str, Path] = DEFAULT_CONFIG_PATH) -> ScoringConfig:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}")
    except yaml.YAMLError as e:
        raise ConfigError(f"Config file is not valid YAML: {e}")
    if not isinstance(raw, dict):
        raise ConfigError("Config file must contain a YAML mapping")
    try:
        return ScoringConfig(**raw)
    except ValidationError as e:
        raise ConfigError(f"Config file is invalid:\n{e}")


def compute_score(likelihood: int, impact: int, category: str, config: ScoringConfig) -> float:
    """likelihood x impact x category weight."""
    if not config.likelihood_scale.min <= likelihood <= config.likelihood_scale.max:
        raise ValueError(f"Likelihood {likelihood} is outside the configured scale")
    if not config.impact_scale.min <= impact <= config.impact_scale.max:
        raise ValueError(f"Impact {impact} is outside the configured scale")
    if category not in config.category_weights:
        raise ValueError(f"Unknown category: {category}")
    return likelihood * impact * config.category_weights[category]


def assign_priority(score: float, config: ScoringConfig) -> str:
    for band in config.priority_bands:
        if score >= band.min_score:
            return band.name
    # Unreachable when the last band has min_score 0 and scores are >= 0.
    return config.priority_bands[-1].name


def evaluate_financial_rules(
    metrics: Dict[str, MetricResult], period_label: str, config: ScoringConfig
) -> Tuple[List[RiskFlag], List[NotAssessed]]:
    """Check every rule. Returns (flags raised, rules that could not be checked)."""
    flags: List[RiskFlag] = []
    not_assessed: List[NotAssessed] = []

    for rule in config.financial_rules:
        metric = metrics.get(rule.metric)
        if metric is None:
            not_assessed.append(
                NotAssessed(rule_id=rule.id, metric=rule.metric, reason="Metric not calculated for this run")
            )
            continue
        if metric.value is None:
            not_assessed.append(
                NotAssessed(rule_id=rule.id, metric=rule.metric, reason=metric.note or metric.status)
            )
            continue
        if OPERATORS[rule.operator](metric.value, rule.threshold):
            score = compute_score(rule.likelihood, rule.impact, rule.category, config)
            flags.append(
                RiskFlag(
                    rule_id=rule.id,
                    title=rule.title,
                    category=rule.category,
                    metric=rule.metric,
                    observed_value=metric.value,
                    operator=rule.operator,
                    threshold=rule.threshold,
                    likelihood=rule.likelihood,
                    impact=rule.impact,
                    score=score,
                    priority=assign_priority(score, config),
                    period=period_label,
                    sources=metric.sources,
                    follow_up_questions=rule.follow_up_questions,
                )
            )
    return flags, not_assessed


def build_register(flags: List[RiskFlag]) -> List[RiskFlag]:
    """Highest score first. Ties are broken by rule id so the order is stable."""
    return sorted(flags, key=lambda f: (-f.score, f.rule_id))
