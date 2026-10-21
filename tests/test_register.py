from tests.sample_result import sample_result
from utils.display import fmt_metric, md_escape, money
from utils.register import build_register, matrix_cells, priority_counts
from utils.scoring import load_config


def test_register_combines_rules_and_ai_sorted_by_score():
    rows = build_register(sample_result())
    assert {r.basis for r in rows} == {"Rule", "AI"}
    scores = [r.score for r in rows]
    assert scores == sorted(scores, reverse=True)
    assert rows[0].ref == "R-01"  # negative operating cash flow, score 16


def test_ties_put_rules_before_ai():
    rows = build_register(sample_result())
    for a, b in zip(rows, rows[1:]):
        if a.score == b.score and a.basis != b.basis:
            assert a.basis == "Rule"


def test_rejected_ai_finding_is_not_in_register():
    titles = [r.title for r in build_register(sample_result())]
    assert "Fabricated finding" not in titles


def test_register_without_ai():
    rows = build_register(sample_result(with_ai=False))
    assert rows and all(r.basis == "Rule" for r in rows)


def test_counts_and_matrix():
    config = load_config()
    rows = build_register(sample_result())
    counts = priority_counts(rows, config)
    assert sum(counts.values()) == len(rows)
    cells = matrix_cells(rows, config)
    assert len(cells) == 25
    assert sum(c["count"] for c in cells) == len(rows)
    top = next(c for c in cells if c["likelihood"] == 5 and c["impact"] == 5)
    assert top["band"] == "High"


def test_number_formats():
    assert fmt_metric("current_ratio", 0.8933) == "0.89x"
    assert fmt_metric("net_margin", 0.2692) == "26.9%"
    assert fmt_metric("revenue_growth", -0.3) == "-30.0%"
    assert fmt_metric("net_margin_change_pp", 2.944) == "+2.9 pp"
    assert fmt_metric("current_ratio", None) == "n/a"
    assert money(73_733_000_000) == "$73.7bn"
    assert money(-30_000_000) == "-$30.0m"


def test_markdown_escape_stops_dollar_signs_becoming_maths():
    assert md_escape("costs rose from $5 to $10") == "costs rose from \\$5 to \\$10"
    assert md_escape("[click](http://x)") == "\\[click\\]\\(http://x\\)"
