"""Data structures shared across RiskLens.

Pydantic checks types and values when an object is created, so bad data
fails loudly at the point it enters the system instead of silently later.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

# Canonical names used inside RiskLens.
# Stage 4 maps the SEC's XBRL tags onto these names.
CANONICAL_CONCEPTS = (
    "Revenue",
    "NetIncome",
    "OperatingIncome",
    "InterestExpense",
    "CurrentAssets",
    "CurrentLiabilities",
    "TotalLiabilities",
    "StockholdersEquity",
    "OperatingCashFlow",
    "Cash",
)

RiskCategory = Literal[
    "business_continuity",
    "cybersecurity",
    "third_party",
    "compliance",
    "governance",
    "financial_resilience",
]

MetricStatus = Literal["ok", "missing_input", "zero_denominator", "not_meaningful"]


class Fact(BaseModel):
    """One reported financial value and where it came from."""

    concept: str
    value: float
    unit: str = "USD"
    period_end: date
    fiscal_year: Optional[int] = None
    fiscal_period: Optional[str] = None  # e.g. "FY", "Q2"
    form: Optional[str] = None  # e.g. "10-K"
    accession: Optional[str] = None  # SEC accession number of the filing
    source_tag: Optional[str] = None  # original XBRL tag, filled in Stage 4

    @model_validator(mode="after")
    def check_concept(self) -> "Fact":
        if self.concept not in CANONICAL_CONCEPTS:
            raise ValueError(
                f"Unknown concept '{self.concept}'. Expected one of {CANONICAL_CONCEPTS}"
            )
        return self


class FinancialPeriod(BaseModel):
    """All facts for one reporting period (e.g. fiscal year 2025)."""

    label: str
    period_end: date
    facts: Dict[str, Fact] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_keys(self) -> "FinancialPeriod":
        for key, fact in self.facts.items():
            if key != fact.concept:
                raise ValueError(f"Fact stored under '{key}' has concept '{fact.concept}'")
        return self

    def value(self, concept: str) -> Optional[float]:
        """Return the reported value, or None if it was not reported."""
        fact = self.facts.get(concept)
        return fact.value if fact is not None else None

    def sources(self, concepts: List[str]) -> List[str]:
        """Accession numbers of the filings behind the given concepts."""
        found = []
        for concept in concepts:
            fact = self.facts.get(concept)
            if fact is not None and fact.accession and fact.accession not in found:
                found.append(fact.accession)
        return found


class MetricResult(BaseModel):
    """A calculated ratio or change, with its inputs and status.

    value is None whenever the metric could not be calculated honestly.
    status and note explain why.
    """

    name: str
    value: Optional[float]
    formula: str
    inputs: Dict[str, Optional[float]]
    status: MetricStatus
    note: str = ""
    sources: List[str] = Field(default_factory=list)


class RiskFlag(BaseModel):
    """A risk raised by a deterministic rule. This is an observed fact,
    not an AI interpretation."""

    rule_id: str
    title: str
    category: RiskCategory
    metric: str
    observed_value: float
    operator: str
    threshold: float
    likelihood: int
    impact: int
    score: float
    priority: str
    period: str
    sources: List[str] = Field(default_factory=list)
    follow_up_questions: List[str] = Field(default_factory=list)
    basis: Literal["deterministic_rule"] = "deterministic_rule"


class NotAssessed(BaseModel):
    """A rule that could not be checked, and why."""

    rule_id: str
    metric: str
    reason: str


# ---------------------------------------------------------------------------
# Stage 3: filing text, AI output and validated findings
# ---------------------------------------------------------------------------

ConfidenceLevel = Literal["High", "Medium", "Low"]


class FilingRef(BaseModel):
    """Which SEC filing a piece of evidence came from."""

    company: str
    cik: str
    form: str  # "10-K" or "10-Q"
    accession: str
    filed: Optional[date] = None
    period_end: Optional[date] = None  # "reportDate" in SEC data
    url: Optional[str] = None
    sic: Optional[str] = None  # industry code, used to warn about banks and insurers
    sic_description: Optional[str] = None


class Paragraph(BaseModel):
    """One paragraph of filing text with a stable ID the AI must cite."""

    id: str  # e.g. "1A-0007"
    section: str  # e.g. "Item 1A. Risk Factors"
    text: str


# --- What Gemini must return. Kept deliberately simple so the schema can be
# --- sent to the API. Everything here is AI output and is NOT trusted yet.

class EvidenceQuote(BaseModel):
    paragraph_id: str = Field(description="The ID shown in square brackets before the paragraph, e.g. 1A-0007")
    quote: str = Field(
        description="One continuous passage copied word for word from that paragraph. No ellipses, no paraphrasing."
    )


class CandidateRisk(BaseModel):
    title: str = Field(description="Short name for the risk, under 12 words")
    category: RiskCategory
    interpretation: str = Field(
        description="Two or three sentences on why this matters for operational risk, "
        "reasoning only from the filing text. No outside facts, figures or trends."
    )
    evidence: List[EvidenceQuote] = Field(min_length=1, max_length=4)
    likelihood: int = Field(
        ge=1,
        le=5,
        description="1 = remote, 2 = unlikely, 3 = possible, 4 = likely in the next year, "
        "5 = the filing says this is already happening or has happened",
    )
    impact: int = Field(
        ge=1,
        le=5,
        description="1 = minor, 2 = moderate, 3 = significant, 4 = major, "
        "5 = could threaten the company's ability to operate",
    )
    rationale: str = Field(description="One or two sentences justifying the likelihood and impact")
    follow_up_questions: List[str] = Field(
        min_length=1, max_length=3, description="Questions a risk consultant should ask management"
    )
    limitations: List[str] = Field(max_length=3, description="What this evidence cannot tell us")


class ExtractionResponse(BaseModel):
    risks: List[CandidateRisk]


# --- After Python has checked the AI output against the filing text.

class VerifiedQuote(BaseModel):
    """A quote confirmed to appear verbatim in the cited paragraph. Observed fact."""

    paragraph_id: str
    section: str
    quote: str
    filing: FilingRef


class RejectedQuote(BaseModel):
    paragraph_id: str
    quote: str
    reason: str


class RiskFinding(BaseModel):
    """An AI-proposed risk that survived evidence validation.

    evidence      -> observed (verified quotes from the filing)
    interpretation, rationale, likelihood, impact, follow_up_questions
                  -> AI judgement, shown as such
    confidence    -> computed by rules from the evidence, not by the AI
    """

    finding_id: str
    title: str
    category: RiskCategory
    basis: Literal["ai_extraction"] = "ai_extraction"
    evidence: List[VerifiedQuote]
    rejected_evidence: List[RejectedQuote] = Field(default_factory=list)
    interpretation: str
    likelihood: int
    impact: int
    rationale: str
    score: float
    priority: str
    confidence: ConfidenceLevel
    confidence_reason: str
    corroborated_by: List[str] = Field(default_factory=list)
    follow_up_questions: List[str]
    limitations: List[str]


class RejectedFinding(BaseModel):
    """An AI-proposed risk with no verifiable evidence. Kept for transparency."""

    title: str
    category: str
    reason: str
    rejected_evidence: List[RejectedQuote] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    findings: List[RiskFinding] = Field(default_factory=list)
    rejected: List[RejectedFinding] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    prompt_tokens: int = 0
    output_tokens: int = 0
    models_used: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 4: filing sections and the full analysis result
# ---------------------------------------------------------------------------

class FilingSection(BaseModel):
    """One Item of a 10-K or 10-Q, located by the section splitter."""

    item: str  # e.g. "1A"
    title: str  # e.g. "Risk Factors"
    found: bool
    chars: int = 0
    paragraphs: List[Paragraph] = Field(default_factory=list)
    note: str = ""


class AnalysisResult(BaseModel):
    """Everything one run produces. Saved as JSON so a run can be reloaded."""

    ticker: str
    filing: FilingRef
    generated_at: str
    current_period: Optional[FinancialPeriod] = None
    prior_period: Optional[FinancialPeriod] = None
    metrics: Dict[str, MetricResult] = Field(default_factory=dict)
    flags: List[RiskFlag] = Field(default_factory=list)
    not_assessed: List[NotAssessed] = Field(default_factory=list)
    sections: List[FilingSection] = Field(default_factory=list)
    extraction: Optional[ExtractionResult] = None
    data_notes: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
