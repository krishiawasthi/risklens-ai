"""End-to-end run with fake SEC responses and a fake Gemini. No network."""
import json

from tests.sample_sec import ACC_10K, FakeSession, facts_url, standard_routes
from tests.test_llm_extractor import FakeGenerator, risk
from utils.llm_extractor import ExtractionError
from utils.pipeline import load_result, run_analysis, save_result
from utils.scoring import load_config
from utils.sec_client import SECClient

UA = "Test Person test@example.com"


def sec(routes=None):
    return SECClient(user_agent=UA, session=FakeSession(routes or standard_routes()), cache_dir=None, sleep=lambda s: None)


AI_RESPONSE = json.dumps(
    {
        "risks": [
            risk(
                "Single-source semiconductor supplier",
                "third_party",
                [("1A-0001", "We rely on a single third-party supplier for the semiconductor components")],
            ),
            risk(
                "Material weakness in access controls not yet remediated",
                "governance",
                [
                    ("9A-0001", "Management identified a material weakness in internal control over financial reporting"),
                    ("9A-0002", "which had not been tested for operating effectiveness as of year end"),
                ],
            ),
            risk(
                "Fabricated finding",
                "compliance",
                [("3-0001", "The company paid a 20 million dollar settlement last year")],
            ),
        ]
    }
)


def test_full_run():
    gen = FakeGenerator(AI_RESPONSE)
    result = run_analysis("exmc", "10-K", sec(), load_config(), gen)

    assert result.ticker == "EXMC"
    assert result.filing.accession == ACC_10K
    assert {s.item for s in result.sections if s.found} == {"1A", "1C", "3", "9A"}

    fired = {f.rule_id for f in result.flags}
    assert {"current_ratio_low", "loss_making", "revenue_decline"} <= fired
    assert "high_leverage" in {n.rule_id for n in result.not_assessed}  # Liabilities not tagged

    titles = [f.title for f in result.extraction.findings]
    assert "Material weakness in access controls not yet remediated" in titles
    assert [r.title for r in result.extraction.rejected] == ["Fabricated finding"]
    assert result.extraction.findings[0].evidence[0].filing.url.endswith("exmc-20251231.htm")

    # Only section text reaches the model, never the table of contents or other Items
    prompt = gen.calls[0][1]
    assert "[1A-0001]" in prompt and "[9A-0002]" in prompt
    assert "Unresolved Staff Comments" not in prompt
    assert "We own our headquarters" not in prompt


def test_run_without_ai():
    result = run_analysis("EXMC", "10-K", sec(), load_config(), generate=None)
    assert result.extraction is None
    assert result.flags
    assert any("not run" in w for w in result.warnings)


def test_gemini_failure_keeps_deterministic_results():
    def broken(system, prompt):
        raise ExtractionError("No configured Gemini model is available right now")

    result = run_analysis("EXMC", "10-K", sec(), load_config(), broken)
    assert result.extraction is None
    assert result.flags
    assert any("AI extraction failed" in w for w in result.warnings)


def test_no_xbrl_data():
    routes = standard_routes()
    del routes[facts_url()]  # FakeSession returns 404
    result = run_analysis("EXMC", "10-K", sec(routes), load_config(), generate=None)
    assert result.metrics == {} and result.flags == []
    assert len(result.not_assessed) == len(load_config().financial_rules)
    assert any("no XBRL" in n for n in result.data_notes)


def test_save_and_reload(tmp_path):
    result = run_analysis("EXMC", "10-K", sec(), load_config(), FakeGenerator(AI_RESPONSE))
    path = save_result(result, tmp_path)
    assert path.name == f"EXMC_10-K_{ACC_10K}.json"
    again = load_result(path)
    assert again == result
