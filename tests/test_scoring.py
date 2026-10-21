import copy

import pytest
import yaml

from tests.sample_data import healthy_current, healthy_prior, stressed_current, stressed_prior
from utils.financials import compute_all
from utils.scoring import (
    DEFAULT_CONFIG_PATH,
    ConfigError,
    ScoringConfig,
    assign_priority,
    build_register,
    compute_score,
    evaluate_financial_rules,
    load_config,
)


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def raw_config():
    return yaml.safe_load(DEFAULT_CONFIG_PATH.read_text())


def test_default_config_loads(config):
    assert len(config.financial_rules) > 0


def test_score_is_likelihood_times_impact_times_weight(config):
    assert compute_score(3, 4, "financial_resilience", config) == 12


def test_category_weight_changes_score(raw_config):
    raw = copy.deepcopy(raw_config)
    raw["category_weights"]["cybersecurity"] = 1.5
    cfg = ScoringConfig(**raw)
    assert compute_score(2, 4, "cybersecurity", cfg) == 12


def test_score_outside_scale_raises(config):
    with pytest.raises(ValueError):
        compute_score(6, 3, "financial_resilience", config)


def test_priority_band_boundaries(config):
    assert assign_priority(15, config) == "High"
    assert assign_priority(14.9, config) == "Medium"
    assert assign_priority(8, config) == "Medium"
    assert assign_priority(7.9, config) == "Low"
    assert assign_priority(0, config) == "Low"


def test_healthy_company_raises_no_flags(config):
    metrics = compute_all(healthy_current(), healthy_prior())
    flags, not_assessed = evaluate_financial_rules(metrics, "FY2025", config)
    assert flags == []
    assert not_assessed == []


def test_stressed_company_raises_expected_flags(config):
    metrics = compute_all(stressed_current(), stressed_prior())
    flags, _ = evaluate_financial_rules(metrics, "FY2025", config)
    fired = {f.rule_id for f in flags}
    assert fired == {
        "current_ratio_low",  # 200 / 300 = 0.67
        "high_leverage",  # 900 / 200 = 4.5
        "weak_interest_coverage",  # 20 / 15 = 1.33
        "loss_making",  # -50 / 700
        "negative_operating_cash_flow",  # -30 / 300
        "revenue_decline",  # (700 - 1000) / 1000 = -30%
    }
    for f in flags:
        assert f.basis == "deterministic_rule"
        assert f.sources  # every flag points to a filing


def test_missing_data_is_reported_not_flagged(config):
    metrics = compute_all(healthy_current())  # no prior period
    flags, not_assessed = evaluate_financial_rules(metrics, "FY2025", config)
    assert "revenue_decline" in {n.rule_id for n in not_assessed}
    assert "revenue_decline" not in {f.rule_id for f in flags}


def test_register_sorted_by_score_then_id(config):
    metrics = compute_all(stressed_current(), stressed_prior())
    flags, _ = evaluate_financial_rules(metrics, "FY2025", config)
    register = build_register(flags)
    scores = [f.score for f in register]
    assert scores == sorted(scores, reverse=True)
    assert register[0].rule_id == "negative_operating_cash_flow"  # 4 x 4 = 16, the highest


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r["financial_rules"][0].update({"likelihood": 9}),
        lambda r: r["financial_rules"][0].update({"metric": "made_up_metric"}),
        lambda r: r["financial_rules"][0].update({"operator": "=="}),
        lambda r: r["category_weights"].pop("cybersecurity"),
        lambda r: r["priority_bands"].reverse(),
        lambda r: r["financial_rules"].append(dict(r["financial_rules"][0])),
    ],
    ids=["likelihood_out_of_scale", "unknown_metric", "bad_operator",
         "missing_category", "bands_out_of_order", "duplicate_rule_id"],
)
def test_invalid_config_is_rejected(raw_config, change, tmp_path):
    raw = copy.deepcopy(raw_config)
    change(raw)
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError):
        load_config(path)


def test_missing_config_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "does_not_exist.yaml")
