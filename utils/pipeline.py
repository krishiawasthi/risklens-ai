"""The full RiskLens run, from ticker to scored findings.

  ticker -> SEC lookup -> latest filing -> XBRL figures -> ratios and rule flags
         -> filing text -> sections -> Gemini extraction -> evidence checks

Each step reports what it could not do instead of stopping the whole run,
except when there is no filing at all. If Gemini fails, the deterministic
results are still returned with a warning.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Union

from utils.filing_text import all_paragraphs, html_to_lines, split_sections
from utils.financials import compute_all
from utils.llm_extractor import ExtractionError, Generator, Usage, analyse_text
from utils.schemas import AnalysisResult, NotAssessed
from utils.scoring import ScoringConfig, evaluate_financial_rules
from utils.sec_client import SECClient, SECNotFound, normalize_ticker
from utils.xbrl import select_periods


def _is_financial_company(sic: Optional[str]) -> bool:
    """SIC codes 6000-6799 are banks, insurers and other financial firms."""
    return bool(sic) and sic.isdigit() and 6000 <= int(sic) <= 6799


def run_analysis(
    ticker: str,
    form: str,
    sec: SECClient,
    config: ScoringConfig,
    generate: Optional[Generator] = None,
    usage: Optional[Usage] = None,
    progress: Callable[[str], None] = lambda msg: None,
) -> AnalysisResult:
    symbol = normalize_ticker(ticker)
    warnings, notes = [], []

    progress(f"Looking up {symbol} at SEC")
    cik, name = sec.lookup_ticker(symbol)
    progress(f"Finding the latest {form} for {name}")
    filing = sec.latest_filing(cik, form, company=name)

    # --- Financial figures (deterministic) ---------------------------------
    progress("Reading XBRL financial data")
    current = prior = None
    if filing.period_end is None:
        notes.append("SEC did not give a period end date for this filing, so financial figures were not matched")
    else:
        try:
            facts = sec.company_facts(cik)
            current, prior, notes = select_periods(facts, filing.accession, filing.period_end, form)
        except SECNotFound:
            notes.append("SEC has no XBRL financial data for this company")

    metrics, flags, not_assessed = {}, [], []
    if current is not None:
        metrics = compute_all(current, prior)
        flags, not_assessed = evaluate_financial_rules(metrics, current.label, config)
    else:
        not_assessed = [
            NotAssessed(rule_id=r.id, metric=r.metric, reason="No financial data available")
            for r in config.financial_rules
        ]
    if _is_financial_company(filing.sic):
        warnings.append(
            f"This company's industry code is {filing.sic} ({filing.sic_description}), a financial firm. "
            "The ratio thresholds in config/scoring.yaml are designed for non-financial companies and "
            "may not be meaningful here."
        )

    # --- Filing text ---------------------------------------------------------
    progress("Downloading the filing document")
    lines = html_to_lines(sec.download_document(filing))
    items = config.extraction.sections[form]
    sections = split_sections(lines, form, items)
    for s in sections:
        if not s.found:
            warnings.append(f"Item {s.item} ({s.title}) was not found in the document, so it was not analysed")
        elif "Very short" in s.note:
            warnings.append(f"Item {s.item} ({s.title}): very short section. It may say 'Not applicable' "
                            "or refer to another document.")
    paragraphs = all_paragraphs(sections)

    # --- AI-assisted extraction ---------------------------------------------
    extraction = None
    if generate is None:
        warnings.append("AI extraction was not run (switched off)")
    elif not paragraphs:
        warnings.append("No section text was found, so AI extraction was skipped")
    else:
        progress(f"Analysing {len(paragraphs)} paragraphs with Gemini")
        try:
            extraction = analyse_text(paragraphs, filing, flags, config, generate, usage=usage)
        except ExtractionError as e:
            warnings.append(f"AI extraction failed: {e}. The financial results below are unaffected.")

    warnings.extend(sec.warnings)
    return AnalysisResult(
        ticker=symbol,
        filing=filing,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        current_period=current,
        prior_period=prior,
        metrics=metrics,
        flags=flags,
        not_assessed=not_assessed,
        sections=sections,
        extraction=extraction,
        data_notes=notes,
        warnings=warnings,
    )


def save_result(result: AnalysisResult, out_dir: Union[str, Path] = "outputs") -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{result.ticker}_{result.filing.form}_{result.filing.accession}.json"
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_result(path: Union[str, Path]) -> AnalysisResult:
    return AnalysisResult.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
