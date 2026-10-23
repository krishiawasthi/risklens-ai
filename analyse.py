"""Run RiskLens from the terminal.

  python analyse.py AAPL              latest 10-K, with Gemini
  python analyse.py AAPL --form 10-Q  latest 10-Q
  python analyse.py AAPL --no-ai      SEC data and financial rules only (free, no Gemini)
  python analyse.py TSM               a foreign company: its 20-F is used automatically

Results are saved to outputs/ as JSON.
"""
import argparse
import re
import sys

from dotenv import load_dotenv

from utils.llm_extractor import ExtractionError, Usage, make_gemini_generator
from utils.pipeline import run_analysis, save_result
from utils.scoring import ConfigError, load_config
from utils.sec_client import SECClient, SECError


def fmt(value):
    return "n/a" if value is None else f"{value:,.3f}"


def main():
    parser = argparse.ArgumentParser(description="RiskLens: corporate risk analysis of SEC filings")
    parser.add_argument("ticker")
    parser.add_argument("--form", choices=["10-K", "10-Q", "20-F"], default="10-K",
                        help="10-K switches to 20-F automatically for foreign companies, and back")
    parser.add_argument("--no-ai", action="store_true", help="skip the Gemini step")
    args = parser.parse_args()
    load_dotenv()

    try:
        config = load_config()
        sec = SECClient()
        usage = Usage()
        generate = None if args.no_ai else make_gemini_generator(usage=usage)
        result = run_analysis(args.ticker, args.form, sec, config, generate, usage, progress=print)
    except (SECError, ConfigError, ExtractionError) as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    f = result.filing
    print(f"\nFILING: {f.company} | {f.form} | period ended {f.period_end} | filed {f.filed}")
    print(f"  Accession {f.accession}")
    print(f"  {f.url}")

    print("\nSECTIONS")
    for s in result.sections:
        status = f"{s.chars:,} characters, {len(s.paragraphs)} paragraphs" if s.found else "NOT FOUND"
        print(f"  Item {s.item:<3} {s.title:<38} {status}")
        header_note = re.search(r"Ignored \d+ repeated [^.]*\.", s.note)
        if s.found and header_note:
            print(f"           {header_note.group(0)}")

    print("\nFINANCIAL METRICS (deterministic, from XBRL)")
    if result.current_period:
        print(f"  Current: {result.current_period.label}   Prior: {result.prior_period.label if result.prior_period else 'none'}")
    for m in result.metrics.values():
        print(f"  {m.name:<28} {fmt(m.value):>14}   {m.note}")
    for note in result.data_notes:
        print(f"  note: {note}")

    print("\nRISK REGISTER (highest score first)")
    rows = [(fl.score, "RULE", fl.priority, fl.title, "") for fl in result.flags]
    if result.extraction:
        rows += [(x.score, "AI", x.priority, x.title, f"confidence {x.confidence}") for x in result.extraction.findings]
    if not rows:
        print("  none")
    for score, basis, priority, title, extra in sorted(rows, key=lambda r: -r[0]):
        print(f"  [{priority:<6}] {score:>4.0f}  {basis:<4} {title}  {extra}")

    print("\nRULES NOT ASSESSED (missing data, never guessed)")
    for n in result.not_assessed:
        print(f"  {n.rule_id}: {n.reason}")
    if not result.not_assessed:
        print("  none")

    if result.extraction:
        x = result.extraction
        print(f"\nAI: {len(x.findings)} verified, {len(x.rejected)} rejected | "
              f"models {', '.join(x.models_used) or 'none'} | tokens {x.prompt_tokens:,} in, {x.output_tokens:,} out")
        for r in x.rejected:
            print(f"  rejected: {r.title} ({r.reason})")

    print("\nWARNINGS")
    for w in result.warnings + (result.extraction.warnings if result.extraction else []):
        print(f"  - {w}")
    if not result.warnings and not (result.extraction and result.extraction.warnings):
        print("  none")

    print(f"\nSaved to {save_result(result)}")


if __name__ == "__main__":
    main()
