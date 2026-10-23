"""Dashboard tests using Streamlit's AppTest, which runs app.py without a
browser. SEC and Gemini are never called."""
import pytest
from streamlit.testing.v1 import AppTest

from tests.sample_result import sample_result
from utils import pipeline

APP = "../app.py"  # relative to this test file


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("RISKLENS_OUTPUTS", str(tmp_path / "outputs"))
    monkeypatch.setenv("RISKLENS_DEMO_RUNS", str(tmp_path / "demo_runs"))
    monkeypatch.delenv("RISKLENS_ACCESS_CODE", raising=False)
    (tmp_path / "outputs").mkdir()
    return tmp_path / "outputs"


@pytest.fixture(autouse=True)
def no_company_download(monkeypatch):
    """By default the company list is unavailable, so the app shows the plain
    ticker box and tests never call SEC. Tests that need the list patch it."""
    import streamlit as st
    from utils.sec_client import SECError

    def unavailable(self):
        raise SECError("not in tests")

    monkeypatch.setattr("utils.sec_client.SECClient.list_companies", unavailable)
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def button(at, label):
    return next(b for b in at.button if b.label == label)


def test_start_page_without_results(outputs):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.title[0].value == "RiskLens AI"
    assert button(at, "Run analysis")


def test_open_saved_run_renders_every_tab(outputs):
    path = pipeline.save_result(sample_result(), outputs)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.selectbox[0].set_value(path)
    button(at, "Open saved run").click().run()
    assert not at.exception
    assert at.title[0].value == "Example Manufacturing Corp"
    assert [t.label for t in at.tabs] == ["Risk register", "Evidence", "Financials", "Coverage and limitations", "Report"]
    labels = [m.label for m in at.metric]
    assert "High priority" in labels and "AI rejected" in labels
    assert len(at.expander) >= len(sample_result().flags)


def test_run_button_calls_pipeline_and_saves(outputs, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test Person test@example.com")
    calls = []

    def fake_run(ticker, form, sec, config, generate, usage, progress):
        calls.append((ticker, form, generate))
        progress("fake step")
        return sample_result()

    monkeypatch.setattr(pipeline, "run_analysis", fake_run)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input[0].set_value("exmc")
    at.toggle[0].set_value(False)  # AI off, so no Gemini key is needed
    button(at, "Run analysis").click().run()
    assert not at.exception
    assert calls == [("exmc", "10-K", None)]
    assert at.title[0].value == "Example Manufacturing Corp"
    assert list(outputs.glob("*.json"))


def test_sec_error_is_shown_not_raised(outputs, monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)  # SECClient will refuse to start
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.toggle[0].set_value(False)
    button(at, "Run analysis").click().run()
    assert not at.exception
    assert "SEC_USER_AGENT" in at.error[0].value


def test_theme_sets_teal_accent_for_light_and_dark():
    import tomllib
    from pathlib import Path

    config = tomllib.loads((Path(__file__).parent.parent / ".streamlit" / "config.toml").read_text())
    assert config["theme"]["light"]["primaryColor"] == "#0f766e"
    assert config["theme"]["dark"]["primaryColor"] == "#0d9488"


@pytest.fixture
def fake_pipeline(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test Person test@example.com")
    calls = []

    def fake_run(ticker, form, sec, config, generate, usage, progress):
        calls.append(generate is not None)
        return sample_result()

    monkeypatch.setattr(pipeline, "run_analysis", fake_run)
    monkeypatch.setattr("utils.llm_extractor.make_gemini_generator", lambda **kw: (lambda s, p: "{}"))
    return calls


def test_access_code_blocks_ai_run_without_code(outputs, monkeypatch, fake_pipeline):
    monkeypatch.setenv("RISKLENS_ACCESS_CODE", "secret-123")
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.toggle[0].set_value(True).run()
    at.text_input[1].set_value("wrong")
    button(at, "Run analysis").click().run()
    assert not at.exception
    assert fake_pipeline == []  # nothing ran
    assert "access code" in at.warning[0].value


def test_access_code_allows_ai_run_with_code(outputs, monkeypatch, fake_pipeline):
    monkeypatch.setenv("RISKLENS_ACCESS_CODE", "secret-123")
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.toggle[0].set_value(True).run()
    at.text_input[1].set_value("secret-123")
    button(at, "Run analysis").click().run()
    assert not at.exception
    assert fake_pipeline == [True]


def test_access_code_does_not_block_free_run(outputs, monkeypatch, fake_pipeline):
    monkeypatch.setenv("RISKLENS_ACCESS_CODE", "secret-123")
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert at.toggle[0].value is False  # AI is off by default when a code is set
    button(at, "Run analysis").click().run()
    assert not at.exception
    assert fake_pipeline == [False]


def test_demo_runs_are_listed_first(outputs, tmp_path):
    demo_dir = tmp_path / "demo_runs"
    demo_dir.mkdir()
    pipeline.save_result(sample_result(), demo_dir)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.selectbox[0].options[0].startswith("Demo: EXMC")


def test_hosted_secrets_become_environment_variables(outputs, monkeypatch):
    import os

    monkeypatch.delenv("RISKLENS_TEST_SECRET", raising=False)
    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["RISKLENS_TEST_SECRET"] = "from-cloud"
    at.run()
    assert not at.exception
    assert os.environ.get("RISKLENS_TEST_SECRET") == "from-cloud"
    monkeypatch.delenv("RISKLENS_TEST_SECRET")


def test_empty_register_explains_when_ai_was_not_run(outputs):
    result = sample_result(with_ai=False).model_copy(update={"flags": []})
    path = pipeline.save_result(result, outputs)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.selectbox[0].set_value(path)
    button(at, "Open saved run").click().run()
    assert not at.exception
    assert "AI extraction was not run" in at.info[0].value


def test_company_dropdown_lists_sec_companies_and_runs_choice(outputs, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test Person test@example.com")
    monkeypatch.setattr("utils.sec_client.SECClient.list_companies",
                        lambda self: [("AAPL", "Apple Inc."), ("MSFT", "MICROSOFT CORP")])
    tickers = []

    def fake_run(ticker, form, sec, config, generate, usage, progress):
        tickers.append(ticker)
        return sample_result()

    monkeypatch.setattr(pipeline, "run_analysis", fake_run)
    at = AppTest.from_file(APP, default_timeout=60).run()
    company = at.selectbox[0]
    assert company.label == "Company"
    assert company.value == "AAPL · Apple Inc."
    company.set_value("MSFT · MICROSOFT CORP")
    at.toggle[0].set_value(False)
    button(at, "Run analysis").click().run()
    assert not at.exception
    assert tickers == ["MSFT"]


def test_ticker_box_shown_when_company_list_unavailable(outputs):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert at.text_input[0].label == "Company ticker"
