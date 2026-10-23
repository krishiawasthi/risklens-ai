"""RiskLens AI dashboard.

Run from the project folder:  python -m streamlit run app.py

All controls sit on the main page (no sidebar), so the app works on phones.
Results are saved to outputs/ after every run and can be reopened from the
"Open a saved run" box, so a demo does not depend on SEC or Gemini being available. Runs
placed in demo_runs/ are always listed and cost nothing to open.

When RISKLENS_ACCESS_CODE is set (recommended for a public deployment), new
runs with AI extraction need that code, so visitors cannot use up your Gemini
quota. Runs without AI (SEC data and financial rules only) stay open to all.
"""
from __future__ import annotations

import hmac
import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from utils import pipeline
from utils.display import (CHANGE_METRICS, category_label, currency_of, fmt_metric, md_escape, metric_label, money,
                           ticker_from_choice)
from utils.financials import compute_metrics
from utils.llm_extractor import ExtractionError, Usage, make_gemini_generator
from utils.register import build_register, matrix_cells, priority_counts
from utils.report import build_report, report_filename
from utils.scoring import ConfigError, load_config
from utils.sec_client import SECClient, SECError

load_dotenv()


def load_hosted_secrets() -> None:
    """On Streamlit Community Cloud, keys are stored as app secrets instead of
    a .env file. Copy them into environment variables so the rest of RiskLens
    reads them the same way it does locally. Does nothing when run locally
    without a secrets file."""
    try:
        for key, value in st.secrets.items():
            if isinstance(value, str) and key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass


load_hosted_secrets()
OUTPUTS = Path(os.getenv("RISKLENS_OUTPUTS", "outputs"))
DEMO_RUNS = Path(os.getenv("RISKLENS_DEMO_RUNS", str(Path(__file__).parent / "demo_runs")))
ACCESS_CODE = os.getenv("RISKLENS_ACCESS_CODE", "")

# Chart colours. Priority uses one teal ramp (always shown with a text label),
# checked with the data-viz palette validator for each theme: every step is
# distinguishable and clears 2:1 contrast against the background. On the dark
# theme the brightest teal marks the highest priority.
PRIORITY_COLOURS_LIGHT = {"High": "#134e4a", "Medium": "#0f766e", "Low": "#14b8a6"}
PRIORITY_COLOURS_DARK = {"High": "#5eead4", "Medium": "#14b8a6", "Low": "#0f766e"}
SEQUENTIAL = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]  # one hue, light to dark
NEUTRAL = "#898781"  # empty matrix cells, drawn semi-transparent so they suit light and dark themes


def priority_colours() -> dict:
    return PRIORITY_COLOURS_DARK if page_surface() == "#0e1117" else PRIORITY_COLOURS_LIGHT


def page_surface() -> str:
    """Background colour of the current Streamlit theme, used for the thin gaps
    between stacked bar segments. Streamlit may report the theme late on first load."""
    try:
        return "#0e1117" if st.context.theme.type == "dark" else "#ffffff"
    except Exception:
        return "#ffffff"

st.set_page_config(page_title="RiskLens AI", page_icon=":material/shield:", layout="wide",
                   initial_sidebar_state="collapsed")


# ---------------------------------------------------------------- controls

def saved_runs():
    """Demo runs first, then this server's own saved runs (newest first)."""
    demo = sorted(DEMO_RUNS.glob("*.json")) if DEMO_RUNS.exists() else []
    own = sorted(OUTPUTS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if OUTPUTS.exists() else []
    demo_names = {p.name for p in demo}
    return demo + [p for p in own if p.name not in demo_names]


def run_label(path: Path) -> str:
    prefix = "Demo: " if path.parent.resolve() == DEMO_RUNS.resolve() else ""
    return prefix + path.stem.replace("_", " ")


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def _load_company_options() -> list:
    return [f"{ticker} · {name}" for ticker, name in SECClient().list_companies()]


def company_options() -> list:
    """'AAPL · Apple Inc.' for every company in SEC's ticker list, or an empty
    list if SEC cannot be reached. Failures are not cached, so the dropdown
    returns on the next page load once SEC is reachable again."""
    try:
        return _load_company_options()
    except SECError:
        return []


def ai_allowed(code_entered: str) -> bool:
    """True when no access code is configured, or the right code was entered.
    compare_digest avoids leaking the code through response timing."""
    return not ACCESS_CODE or hmac.compare_digest(code_entered.encode(), ACCESS_CODE.encode())


def run_new_analysis(ticker: str, form: str, use_ai: bool) -> None:
    try:
        config = load_config()
        with st.status(f"Analysing {ticker.upper()} {form}...", expanded=True) as status:
            sec = SECClient()
            usage = Usage()
            generate = make_gemini_generator(usage=usage, on_retry=status.write) if use_ai else None
            result = pipeline.run_analysis(ticker, form, sec, config, generate, usage, progress=status.write)
            pipeline.save_result(result, OUTPUTS)
            status.update(label="Analysis complete", state="complete", expanded=False)
        st.session_state["result"] = result
    except (SECError, ConfigError, ExtractionError, ValueError) as e:
        st.session_state.pop("result", None)
        st.error(str(e))


def control_panel() -> None:
    """Company, filing and AI choices, then saved runs. Shown on the main page
    so they are visible on a phone. Columns stack automatically on narrow
    screens. Widget keys keep the choices when the panel moves into the
    collapsed "Analyse another company" box after a run."""
    options = company_options()
    c1, c2 = st.columns([3, 2])
    with c1:
        if options:
            default = next((i for i, o in enumerate(options) if o.startswith("AAPL · ")), 0)
            choice = st.selectbox(
                "Company", options, index=default, filter_mode="contains", key="company",
                help="Type a company name or ticker to search every company in SEC's ticker list.",
            )
            ticker = ticker_from_choice(choice)
        else:
            ticker = st.text_input("Company ticker", value="AAPL", max_chars=10, key="ticker")
    with c2:
        form = st.segmented_control("Filing", ["10-K", "10-Q", "20-F"], default="10-K", required=True, key="form",
                                    help="10-K: US annual report. 10-Q: US quarterly report. 20-F: annual report "
                                         "of a foreign company. Choosing 10-K for a foreign company uses its 20-F "
                                         "automatically.")
    use_ai = st.toggle("AI risk extraction (Gemini)", value=not ACCESS_CODE, key="use_ai",
                       help="Off: SEC retrieval and financial rules only. Free and needs no Gemini key.")
    code = ""
    if use_ai and ACCESS_CODE:
        code = st.text_input("Access code for AI analysis", type="password", key="code",
                             help="AI runs use the owner's Gemini quota. Switch AI off for a free run, "
                                  "or open a demo run below.")
    if st.button("Run analysis", type="primary", width="stretch"):
        if not ticker.strip():
            st.warning("Enter a ticker first.")
        elif use_ai and not ai_allowed(code):
            st.warning("AI analysis needs the access code. Switch AI off to run the free SEC and "
                       "financial analysis, or open a demo run below.")
        else:
            run_new_analysis(ticker.strip(), form, use_ai)
            if "result" in st.session_state:
                st.rerun()  # redraw with the panel collapsed above the results

    runs = saved_runs()
    if runs:
        st.markdown("**Or open a saved run** (demo runs are free and instant)")
        r1, r2 = st.columns([3, 1], vertical_alignment="bottom")
        choice = r1.selectbox("Saved run", runs, format_func=run_label, label_visibility="collapsed")
        if r2.button("Open saved run", width="stretch"):
            try:
                st.session_state["result"] = pipeline.load_result(choice)
                st.rerun()
            except Exception as e:  # corrupted or outdated file
                st.error(f"Could not open {choice.name}: {e}")


# ---------------------------------------------------------------- charts

def risk_matrix_chart(cells):
    df = pd.DataFrame(cells)
    df["label"] = df["count"].where(df["count"] > 0, "").astype(str)
    gaps = alt.Scale(paddingInner=0.08)  # gaps between cells without a background-coloured outline
    base = alt.Chart(df).encode(
        x=alt.X("impact:O", title="Impact", axis=alt.Axis(labelAngle=0), scale=gaps),
        y=alt.Y("likelihood:O", title="Likelihood", sort="descending", scale=gaps),
        tooltip=[
            alt.Tooltip("likelihood:O", title="Likelihood"),
            alt.Tooltip("impact:O", title="Impact"),
            alt.Tooltip("count:Q", title="Risks"),
            alt.Tooltip("refs:N", title="Refs"),
            alt.Tooltip("band:N", title="Band (L x I)"),
        ],
    )
    max_count = max(int(df["count"].max()), 1)
    occupied = base.transform_filter("datum.count > 0").mark_rect(cornerRadius=4).encode(
        color=alt.Color("count:Q", title="Risks", scale=alt.Scale(domain=[1, max_count], range=SEQUENTIAL[1:]),
                        legend=alt.Legend(format="d", tickMinStep=1)),
    )
    empty = base.transform_filter("datum.count == 0").mark_rect(cornerRadius=4, color=NEUTRAL, opacity=0.18)
    text = base.mark_text(fontSize=13, fontWeight="bold").encode(
        text="label:N",
        color=alt.condition(f"datum.count >= {max(2, max_count / 2)}", alt.value("#ffffff"), alt.value("#0b0b0b")),
    )
    return (empty + occupied + text).properties(height=300)


def category_chart(rows, config):
    order = [b.name for b in config.priority_bands]
    df = pd.DataFrame([{"Category": category_label(r.category), "Priority": r.priority, "Ref": r.ref,
                        "Title": r.title} for r in rows])
    counts = df.groupby(["Category", "Priority"]).agg(Risks=("Ref", "count"), Refs=("Ref", ", ".join)).reset_index()
    counts["order"] = counts["Priority"].map({n: i for i, n in enumerate(order)})
    return alt.Chart(counts).mark_bar(size=20, stroke=page_surface(), strokeWidth=2).encode(
        y=alt.Y("Category:N", title=None, sort="-x"),
        x=alt.X("sum(Risks):Q", title="Number of risks", axis=alt.Axis(tickMinStep=1, format="d")),
        color=alt.Color("Priority:N", scale=alt.Scale(domain=order, range=[priority_colours().get(n, "#898781") for n in order]),
                        legend=alt.Legend(orient="bottom", title="Priority")),
        order=alt.Order("order:Q"),
        tooltip=["Category", "Priority", "Risks", "Refs"],
    ).properties(height=300)


# ---------------------------------------------------------------- views

def header(result):
    f = result.filing
    st.title(f.company)
    st.caption(f"{f.form} for the period ended {f.period_end} · filed {f.filed} · accession {f.accession}")
    if f.url:
        st.link_button("Open filing on SEC", f.url)
    if result.figures_note:
        st.warning(md_escape(result.figures_note), icon=":material/history:")
    all_warnings = result.warnings + (result.extraction.warnings if result.extraction else [])
    if all_warnings:
        with st.expander(f"{len(all_warnings)} warning(s) for this run", icon=":material/warning:"):
            for w in all_warnings:
                st.markdown(f"- {md_escape(w)}")


CARD_WIDTH = 150  # pixels; two cards fit side by side on a 390px phone screen


def kpis(rows, result, config):
    """Summary cards in a row that wraps (two or three per line on a phone)
    instead of stacking six full-width cards."""
    counts = priority_counts(rows, config)
    x = result.extraction
    with st.container(horizontal=True, gap="small"):
        for name, n in counts.items():
            st.metric(f"{name} priority", n, border=True, width=CARD_WIDTH)
        st.metric("AI verified", len(x.findings) if x else "not run", border=True, width=CARD_WIDTH)
        st.metric("AI rejected", len(x.rejected) if x else "not run", border=True, width=CARD_WIDTH,
                  help="AI findings rejected because no quotation could be verified against the filing.")
        st.metric("Not assessed", len(result.not_assessed), border=True, width=CARD_WIDTH,
                  help="Financial rules not assessed because required figures were not reported. Nothing is estimated.")


def register_tab(rows, config, result):
    if not rows:
        if result.extraction is None:
            st.info("No financial rules were triggered, and AI extraction was not run for this analysis, "
                    "so the filing's risk disclosures have not been reviewed. Run it again with AI switched "
                    "on to extract operational risks from the text.")
        else:
            st.info("No financial rules were triggered and no AI finding passed the evidence check.")
        return
    c1, c2 = st.columns(2)
    categories = sorted({category_label(r.category) for r in rows})
    chosen_cats = c1.multiselect("Category", categories, default=categories)
    chosen_basis = c2.multiselect("Basis", ["Rule", "AI"], default=["Rule", "AI"],
                                  help="Rule: calculated from reported figures. AI: AI judgement supported by verified quotations.")
    shown = [r for r in rows if category_label(r.category) in chosen_cats and r.basis in chosen_basis]
    df = pd.DataFrame([{
        "Ref": r.ref, "Risk": r.title, "Category": category_label(r.category), "Basis": r.basis,
        "Likelihood": r.likelihood, "Impact": r.impact, "Score": r.score, "Priority": r.priority,
        "Confidence": r.confidence,
    } for r in shown])
    st.dataframe(
        df, hide_index=True, width="stretch",
        column_config={
            "Ref": st.column_config.TextColumn("Ref", width=64),
            "Risk": st.column_config.TextColumn("Risk", width=300),
            "Category": st.column_config.TextColumn("Category", width=150),
            "Basis": st.column_config.TextColumn("Basis", width=60, help="Rule: calculated from reported figures. AI: AI judgement with verified quotations."),
            "Likelihood": st.column_config.NumberColumn("L", help="Likelihood, 1 to 5", width=44),
            "Impact": st.column_config.NumberColumn("I", help="Impact, 1 to 5", width=44),
            "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=25, format="%.0f", width=120),
            "Priority": st.column_config.TextColumn("Priority", width=84),
            "Confidence": st.column_config.TextColumn("Confidence", width=120),
        },
    )
    if not shown:
        return
    left, right = st.columns(2)
    with left:
        st.subheader("Risk matrix")
        st.altair_chart(risk_matrix_chart(matrix_cells(shown, config)), width="stretch")
        st.caption("Count of risks per likelihood and impact. Hover a cell to see which risks it holds.")
    with right:
        st.subheader("Risks by category")
        st.altair_chart(category_chart(shown, config), width="stretch")


def evidence_tab(rows, currency="USD"):
    if not rows:
        st.info("No findings to show.")
        return
    for r in rows:
        label = f"{r.ref} · {r.title} · {r.priority} ({r.score:.0f})"
        with st.expander(label):
            st.caption(f"{category_label(r.category)} · {'Financial rule' if r.basis == 'Rule' else 'AI finding'} · confidence: {r.confidence}")
            if r.flag:
                f = r.flag
                st.markdown("**Observed (deterministic rule)**")
                st.markdown(md_escape(
                    f"{metric_label(f.metric)} was {fmt_metric(f.metric, f.observed_value, currency)} "
                    f"(rule fires when {f.operator} {fmt_metric(f.metric, f.threshold, currency)}). Period: {f.period}. "
                    f"Source: XBRL, accession {', '.join(f.sources)}."))
                st.markdown(f"**Rating:** likelihood {f.likelihood}, impact {f.impact} (fixed in config/scoring.yaml)")
                if f.follow_up_questions:
                    st.markdown("**Follow-up questions (fixed for this rule)**")
                    for q in f.follow_up_questions:
                        st.markdown(f"- {md_escape(q)}")
            else:
                x = r.finding
                st.markdown("**Observed evidence** · verified word for word against the filing")
                for e in x.evidence:
                    st.markdown(f"> {md_escape(e.quote)}")
                    st.caption(f"{e.section} · paragraph {e.paragraph_id}")
                if x.evidence and x.evidence[0].filing.url:
                    st.link_button("Open filing", x.evidence[0].filing.url)
                st.markdown("**AI interpretation** · not verified")
                st.markdown(md_escape(x.interpretation))
                st.markdown(f"**AI rating:** likelihood {x.likelihood}, impact {x.impact}. {md_escape(x.rationale)}")
                reason = x.confidence_reason + (f" Related rule(s): {', '.join(x.corroborated_by)}." if x.corroborated_by else "")
                st.markdown(f"**Confidence {x.confidence}** · computed from verified evidence. {md_escape(reason)}")
                st.markdown("**Follow-up questions** · AI-suggested")
                for q in x.follow_up_questions:
                    st.markdown(f"- {md_escape(q)}")
                st.markdown("**Limitations**")
                for lim in x.limitations:
                    st.markdown(f"- {md_escape(lim)}")
                if x.rejected_evidence:
                    st.markdown("**Quotations removed by the evidence check**")
                    for q in x.rejected_evidence:
                        st.markdown(f"- {md_escape(q.reason)}: {md_escape(q.quote[:200])}")


def financials_tab(result):
    if result.current_period is None:
        st.info("No XBRL financial data was available for this filing.")
        return
    if result.figures_note:
        st.warning(md_escape(result.figures_note), icon=":material/history:")
    cur, pri = result.current_period, result.prior_period
    ccy = cur.currency
    prior_metrics = compute_metrics(pri) if pri else {}
    levels, changes = [], []
    for name, m in result.metrics.items():
        if name in CHANGE_METRICS:
            changes.append({"Change": metric_label(name), "Value": fmt_metric(name, m.value, ccy), "Note": m.note, "Formula": m.formula})
        else:
            p = prior_metrics.get(name)
            levels.append({"Indicator": metric_label(name), cur.label: fmt_metric(name, m.value, ccy),
                           (pri.label if pri else "Prior"): fmt_metric(name, p.value if p else None, ccy),
                           "Note": m.note, "Formula": m.formula})
    st.subheader("Indicators")
    st.dataframe(pd.DataFrame(levels), hide_index=True, width="stretch")
    st.subheader("Change versus prior period")
    st.dataframe(pd.DataFrame(changes), hide_index=True, width="stretch")
    st.subheader("XBRL source values")
    facts = []
    for concept, fact in cur.facts.items():
        p = pri.facts.get(concept) if pri else None
        facts.append({"Concept": concept, "XBRL tag": f"{cur.taxonomy}:{fact.source_tag}", "Current": money(fact.value, ccy),
                      "Prior": money(p.value, ccy) if p else "n/a", "Accession": fact.accession})
    st.dataframe(pd.DataFrame(facts), hide_index=True, width="stretch")
    for note in result.data_notes:
        st.caption(md_escape(note))


def coverage_tab(result, config):
    st.subheader("Sections analysed")
    st.dataframe(pd.DataFrame([{
        "Item": s.item, "Title": s.title, "Found": "Yes" if s.found else "No",
        "Characters": s.chars, "Paragraphs": len(s.paragraphs), "Note": s.note,
    } for s in result.sections]), hide_index=True, width="stretch")

    st.subheader("Rules not assessed")
    if result.not_assessed:
        st.dataframe(pd.DataFrame([n.model_dump() for n in result.not_assessed]), hide_index=True, width="stretch")
    else:
        st.caption("Every rule could be assessed.")

    x = result.extraction
    st.subheader("AI findings rejected by the evidence check")
    if x and x.rejected:
        for r in x.rejected:
            st.markdown(f"- **{md_escape(r.title)}**: {md_escape(r.reason)}")
    else:
        st.caption("None." if x else "AI extraction was not run.")
    if x:
        st.caption(f"Model(s): {', '.join(x.models_used) or 'n/a'} · tokens: {x.prompt_tokens:,} in, {x.output_tokens:,} out")

    st.subheader("Scoring assumptions")
    bands = ", ".join(f"{b.name} ≥ {b.min_score:g}" for b in config.priority_bands)
    st.markdown(md_escape(f"Score = likelihood x impact x category weight. Bands: {bands}. "
                          "All thresholds and weights are prototype assumptions in config/scoring.yaml."))


def report_tab(result, config):
    st.markdown("A consulting-style Word report built from this run. No extra AI call is made.")
    try:
        data = build_report(result, config)
    except Exception as e:
        st.error(f"Could not build the report: {e}")
        return
    st.download_button("Download Word report", data, file_name=report_filename(result),
                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", type="primary")


# ---------------------------------------------------------------- main

result = st.session_state.get("result")
if result is None:
    st.title("RiskLens AI")
    st.markdown(
        "Corporate risk intelligence from SEC filings. Choose a company and select **Run analysis**. "
        "RiskLens fetches the latest 10-K, 10-Q or 20-F from SEC EDGAR, calculates financial indicators from "
        "its XBRL data, extracts operational risk disclosures with Gemini, and keeps only findings whose "
        "quotations match the filing word for word."
    )
    with st.container(border=True):
        control_panel()
    st.caption("Prototype. Observed facts and AI judgements are labelled separately throughout.")
else:
    # Label names the run on show, so it starts collapsed again after each new run.
    with st.expander(f"Analyse another company (showing {result.ticker} {result.filing.form})",
                     icon=":material/search:"):
        control_panel()
    config = load_config()
    rows = build_register(result)
    header(result)
    kpis(rows, result, config)
    tabs = st.tabs(["Risk register", "Evidence", "Financials", "Coverage and limitations", "Report"])
    with tabs[0]:
        register_tab(rows, config, result)
    with tabs[1]:
        evidence_tab(rows, currency_of(result))
    with tabs[2]:
        financials_tab(result)
    with tabs[3]:
        coverage_tab(result, config)
    with tabs[4]:
        report_tab(result, config)
