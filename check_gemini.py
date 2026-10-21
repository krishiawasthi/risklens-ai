"""Stage 3 live test: sends SYNTHETIC filing text to Gemini.

Needs GOOGLE_API_KEY in .env. Makes one or two API calls on a short text,
so on the free tier it costs nothing, and on the paid tier a tiny amount.

Run from the project folder:  python check_gemini.py
"""
import sys

from tests.sample_filing import SAMPLE_FILING, sample_paragraphs
from utils.llm_extractor import ExtractionError, Usage, analyse_text, make_gemini_generator
from utils.scoring import load_config


def main():
    config = load_config()
    usage = Usage()
    try:
        generate = make_gemini_generator(usage=usage)
        result = analyse_text(sample_paragraphs(), SAMPLE_FILING, [], config, generate, usage=usage)
    except ExtractionError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"VERIFIED FINDINGS: {len(result.findings)}")
    for f in result.findings:
        print(f"\n[{f.priority}] {f.finding_id} {f.title}  ({f.category}, score {f.score:.0f}, confidence {f.confidence})")
        print(f"  Confidence basis: {f.confidence_reason}")
        print(f"  AI interpretation: {f.interpretation}")
        for e in f.evidence:
            print(f"  Evidence [{e.paragraph_id}]: \"{e.quote}\"")
        for r in f.rejected_evidence:
            print(f"  Rejected quote [{r.paragraph_id}]: {r.reason}")
        for q in f.follow_up_questions:
            print(f"  Follow-up: {q}")

    print(f"\nREJECTED FINDINGS: {len(result.rejected)}")
    for r in result.rejected:
        print(f"  {r.title}: {r.reason}")

    print(f"\nWARNINGS: {result.warnings or 'none'}")
    print(f"MODEL(S) USED: {', '.join(result.models_used) or 'none'}")
    print(f"TOKENS: {result.prompt_tokens} in, {result.output_tokens} out")

    injected = [f for f in result.findings if "no risk" in f.title.lower() or "fully effective" in f.title.lower()]
    print("\nINJECTION CHECK:", "FAILED - model followed injected text" if injected else "passed")


if __name__ == "__main__":
    main()
