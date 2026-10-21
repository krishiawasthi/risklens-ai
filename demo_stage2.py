"""Stage 2 demo: run the deterministic engine on SYNTHETIC data.

Run from the project folder:  python demo_stage2.py
"""
from tests.sample_data import stressed_current, stressed_prior
from utils.financials import compute_all
from utils.scoring import build_register, evaluate_financial_rules, load_config


def main():
    config = load_config()
    current, prior = stressed_current(), stressed_prior()
    metrics = compute_all(current, prior)

    print("METRICS (synthetic data)")
    for m in metrics.values():
        shown = f"{m.value:.3f}" if m.value is not None else f"n/a ({m.status})"
        print(f"  {m.name:<28} {shown:<22} {m.formula}")

    flags, not_assessed = evaluate_financial_rules(metrics, current.label, config)

    print("\nRISK REGISTER (deterministic rules)")
    for f in build_register(flags):
        print(
            f"  [{f.priority:<6}] score {f.score:>4.0f}  {f.title}"
            f"  ({f.metric} = {f.observed_value:.3f}, rule {f.operator} {f.threshold})"
        )

    print("\nNOT ASSESSED")
    if not not_assessed:
        print("  none")
    for n in not_assessed:
        print(f"  {n.rule_id}: {n.reason}")


if __name__ == "__main__":
    main()
