# RiskLens AI: Corporate Risk Intelligence Agent

RiskLens takes a company ticker, retrieves the latest 10-K, 10-Q or 20-F from SEC EDGAR, and produces a prioritised operational risk register with evidence, a dashboard and a Word report.

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
  -> SEC ticker list (CIK) -> submissions (latest 10-K/10-Q/20-F, amendments excluded)
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
python analyse.py TSM --form 20-F --no-ai   # foreign company (annual report)
```

## API keys and costs

- **SEC EDGAR:** free, no key. SEC requires a User-Agent with your name and email and allows up to 10 requests per second. RiskLens sends about four requests per analysis and caches responses in `.cache/`.
- **Gemini:** needs a Google AI Studio key. The free tier is rate-limited and enough for prototyping. Google may use free-tier prompts to improve its products, so use only public data on the free tier. On the paid tier, cost is tokens used multiplied by Google's current price for the model. One full Apple 10-K run used about 17,000 input and 4,300 output tokens, and every run reports its token count. Check Google's pricing page for current rates.
- **Without Gemini:** switch AI extraction off in the main page (or use `--no-ai`). SEC retrieval, ratios and rules still run, at no cost.

## Publishing on Streamlit Community Cloud

Hosting the app uses no Gemini tokens. Tokens are used only when someone runs a new analysis with AI switched on, and they come from your key. On a free-tier key that can use up your daily quota; with billing enabled it costs money. RiskLens protects against this:

- Set `RISKLENS_ACCESS_CODE`. New AI runs then need the code. Without it, visitors can still run the free SEC and financial analysis.
- Put finished runs in `demo_runs/`. They are always listed in the main page as "Demo:" and cost nothing to open.

Steps:

1. Copy your best runs into `demo_runs/`, e.g. `mkdir demo_runs && cp outputs/AAPL_10-K_*.json demo_runs/`.
2. Push the project to a GitHub repository. Check with `git status` that `.env` is **not** included; `.gitignore` excludes it. If a key was ever committed, create a new key in Google AI Studio.
3. On share.streamlit.io, create an app from the repository with `app.py` as the main file. Under Advanced settings choose Python 3.12 (tested).
4. In the app's Secrets settings, paste:

```toml
GOOGLE_API_KEY = "your_key"
GEMINI_MODELS = "gemini-3.6-flash,gemini-3.5-flash,gemini-3.1-flash-lite"
SEC_USER_AGENT = "Your Name your.email@example.com"
RISKLENS_ACCESS_CODE = "choose-a-code"
```

Notes: runs saved on the hosted app are visible to every visitor and are deleted when the app restarts; demo runs in the repository are permanent.

## Scope and limitations

- Forms 10-K, 10-Q and 20-F. If you ask for a 10-K from a company that files 20-F (or the other way round), RiskLens analyses the form the company actually files and says so in a warning.
- 20-F sections read: Item 3.D Risk Factors, Item 15 Controls and Procedures, Item 16K Cybersecurity.
- Many 20-F filers report under IFRS in their own currency (for example TWD or EUR). Figures are shown in that currency and are not converted. Some IFRS concepts differ from US GAAP: FinanceCosts is used when InterestExpense is not tagged (it can include more than interest), and total liabilities is often not tagged, so leverage is then "not assessed".
- SEC sometimes publishes a filing's structured financial figures later than the filing itself (seen with TSMC's 2025 20-F). RiskLens then uses the company's previous filing of the same form for the figures and rules, and says so in a warning at the top of the page and in the report. The risk text always comes from the latest filing. `python check_facts.py TICKER FORM` shows what SEC holds for a filing.
- Foreign companies filing 6-K instead of 10-Q have no quarterly analysis. Canadian 40-F filers are not supported.
- Public disclosures only. Internal control data, incident logs and testing evidence are out of scope.
- Ratio thresholds suit non-financial companies. The app warns when the industry code indicates a bank, insurer or other financial firm.
- Section detection relies on Item headings. A section that cannot be found is reported, not skipped silently.
- AI interpretations and ratings are not verified by code and need human review.
