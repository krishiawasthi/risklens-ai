"""One prioritised register combining rule flags and verified AI findings."""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

from utils.schemas import AnalysisResult, RiskFinding, RiskFlag
from utils.scoring import ScoringConfig, assign_priority


class RegisterRow(BaseModel):
    ref: str  # R-01 for rules, AI-01 for AI findings
    title: str
    category: str
    basis: Literal["Rule", "AI"]
    likelihood: int
    impact: int
    score: float
    priority: str
    confidence: str  # "Observed data" for rules; High/Medium/Low for AI
    flag: Optional[RiskFlag] = None
    finding: Optional[RiskFinding] = None


def build_register(result: AnalysisResult) -> List[RegisterRow]:
    rows: List[RegisterRow] = []
    flags = sorted(result.flags, key=lambda f: (-f.score, f.rule_id))
    for i, f in enumerate(flags, start=1):
        rows.append(
            RegisterRow(
                ref=f"R-{i:02d}",
                title=f.title,
                category=f.category,
                basis="Rule",
                likelihood=f.likelihood,
                impact=f.impact,
                score=f.score,
                priority=f.priority,
                confidence="Observed data",
                flag=f,
            )
        )
    if result.extraction:
        for x in result.extraction.findings:
            rows.append(
                RegisterRow(
                    ref=x.finding_id,
                    title=x.title,
                    category=x.category,
                    basis="AI",
                    likelihood=x.likelihood,
                    impact=x.impact,
                    score=x.score,
                    priority=x.priority,
                    confidence=x.confidence,
                    finding=x,
                )
            )
    # Highest score first; on a tie, rules (observed data) before AI findings
    return sorted(rows, key=lambda r: (-r.score, r.basis != "Rule", r.ref))


def priority_counts(rows: List[RegisterRow], config: ScoringConfig) -> Dict[str, int]:
    counts = {band.name: 0 for band in config.priority_bands}
    for r in rows:
        counts[r.priority] = counts.get(r.priority, 0) + 1
    return counts


def matrix_cells(rows: List[RegisterRow], config: ScoringConfig) -> List[dict]:
    """Every likelihood x impact cell, with the risks in it. The cell band uses
    likelihood x impact with a category weight of 1.0."""
    lo_l, hi_l = config.likelihood_scale.min, config.likelihood_scale.max
    lo_i, hi_i = config.impact_scale.min, config.impact_scale.max
    cells = []
    for lik in range(lo_l, hi_l + 1):
        for imp in range(lo_i, hi_i + 1):
            refs = [r.ref for r in rows if r.likelihood == lik and r.impact == imp]
            cells.append(
                {
                    "likelihood": lik,
                    "impact": imp,
                    "count": len(refs),
                    "refs": ", ".join(refs),
                    "band": assign_priority(lik * imp, config),
                }
            )
    return cells
