---
title: RiskLens AI
emoji: 🛡️
colorFrom: blue
colorTo: red
sdk: streamlit
app_file: app.py
pinned: false
short_description: Operational risk screening of SEC 10-K and 10-Q filings
---

# RiskLens AI: Corporate Risk Intelligence Agent

RiskLens takes a US company ticker, retrieves the latest 10-K or 10-Q from SEC EDGAR, and produces a prioritised operational risk register with evidence, a dashboard and a Word report.

It is a prototype screening tool. Its outputs are a starting point for a risk professional, not conclusions.

## Design principles

1. **Python owns every number.** Financial figures come from SEC's XBRL data, and ratios, changes, scores and confidence levels are calculated in tested Python code.
2. **The AI only reads text.** Gemini proposes candidate risks from selected filing sections and must quote the filing word for word. It has no tools and cannot take actions.
3. **Nothing unverified reaches the register.** Every AI quotation is checked against the paragraph it cites. Findings with no verified quotation are rejected and listed separately.
4. **Facts and judgements are labelled separately.** Verified quotations and XBRL figures are shown as observed. Interpretations, likelihood and impact ratings, and AI-suggested questions are labelled as AI judgement.
5. **Missing data is reported, never estimated.** A rule whose inputs are not reported is shown as "not assessed" with the reason.
6. **Assumptions are explicit.** Every threshold, weight and band lives in `config/scoring.yaml` and is validated when loaded.
7. **Filing text is untrusted data.** It sits between random boundary markers, the model is told never to follow instructions inside it, and a test covers a prompt-injection paragraph.

## Pipeline

```
ticker
  -> SEC ticker list (CIK) -> submissions (latest 10-K/10-Q, amendments excluded)
  -> XBRL company facts -> figures for this filing and the prior period
       -> ratios and changes -> deterministic rules -> rule flags
  -> filing HTML -> text -> Items (1A, 1C, 3, 9A for a 10-K)
       -> Gemini (JSON schema) -> quotation check -> confidence by rule
  -> combined register -> dashboard, Word report, saved JSON
```

## Project structure

```
app.py                  Streamlit dashboard
analyse.py              Command-line runner
check_gemini.py         Live Gemini test on synthetic text
ping_gemini.py          Shows which Gemini models respond to your key
config/scoring.yaml     All scoring assumptions
utils/
  sec_client.py         SEC EDGAR access, rate limiting, retries, disk cache
  filing_text.py        HTML to text, footer removal, section splitting
  xbrl.py               Picks figures for the filing from XBRL company facts
  financials.py         Ratios and period-over-period changes
  scoring.py            Config validation, scores, priorities, rule evaluation
  llm_extractor.py      Gemini calls, model fallback, schema validation
  evidence.py           Quotation verification and confidence rules
  pipeline.py           Runs the whole workflow, saves and loads results
  register.py           Combined risk register and risk matrix
  report.py             Word report
  display.py            Shared labels and number formats
  schemas.py            Pydantic data models
tests/                  Test suite with synthetic data (no network calls)
```

## Setup (macOS)

Requires Python 3.10 or newer. Tested on Python 3.12 and 3.15.

```bash
cd risklens
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then edit `.env`:

```
GOOGLE_API_KEY=your_key
GEMINI_MODELS=gemini-3.6-flash,gemini-3.5-flash,gemini-3.1-flash-lite
SEC_USER_AGENT=Your Name your.email@example.com
```

## Run

```bash
python -m pytest -q                      # test suite, no network needed
python -m streamlit run app.py           # dashboard
python analyse.py AAPL                   # terminal version
python analyse.py AAPL --form 10-Q --no-ai
```

## API keys and costs

- **SEC EDGAR:** free, no key. SEC requires a User-Agent with your name and email and allows up to 10 requests per second. RiskLens sends about four requests per analysis and caches responses in `.cache/`.
- **Gemini:** needs a Google AI Studio key. The free tier is rate-limited and enough for prototyping. Google may use free-tier prompts to improve its products, so use only public data on the free tier. On the paid tier, cost is tokens used multiplied by Google's current price for the model. One full Apple 10-K run used about 17,000 input and 4,300 output tokens, and every run reports its token count. Check Google's pricing page for current rates.
- **Without Gemini:** switch AI extraction off in the sidebar (or use `--no-ai`). SEC retrieval, ratios and rules still run, at no cost.

## Scope and limitations

- US SEC filers using Forms 10-K and 10-Q only. Foreign private issuers filing 20-F or 40-F are not supported.
- Public disclosures only. Internal control data, incident logs and testing evidence are out of scope.
- Ratio thresholds suit non-financial companies. The app warns when the industry code indicates a bank, insurer or other financial firm.
- Section detection relies on Item headings. A section that cannot be found is reported, not skipped silently.
- AI interpretations and ratings are not verified by code and need human review.
