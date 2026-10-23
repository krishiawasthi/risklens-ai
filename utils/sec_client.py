"""SEC EDGAR client.

Uses four free SEC endpoints. No API key is needed, but SEC requires a
User-Agent header with your name and email, and allows at most 10
requests per second.

  company_tickers.json  ticker -> CIK (company ID) and name
  submissions           list of the company's filings
  Archives              the filing document itself
  companyfacts          XBRL financial data tagged in the company's filings

Responses are cached on disk in .cache/sec/. Filing documents never change,
so they are cached permanently. Other responses are refreshed after a day.
If SEC cannot be reached and a cached copy exists, the cached copy is used
and a warning is recorded, which keeps a demo working offline.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import requests

from utils.schemas import FilingRef

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{doc}"

SUPPORTED_FORMS = ("10-K", "10-Q", "20-F")
ONE_DAY = 24 * 60 * 60
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class SECError(Exception):
    """SEC could not be reached, refused the request, or sent unexpected data."""


class SECNotFound(SECError):
    """The ticker, company or filing does not exist."""


class FormNotFiled(SECNotFound):
    """The company does not file the requested form. `alternative` names the
    form it files instead when RiskLens can analyse that one (10-K or 20-F)."""

    def __init__(self, message: str, alternative: Optional[str] = None):
        super().__init__(message)
        self.alternative = alternative


def normalize_ticker(ticker: str) -> str:
    """'brk.b ' -> 'BRK-B'. SEC's ticker list uses hyphens for share classes."""
    t = (ticker or "").strip().upper().replace(".", "-")
    if not re.fullmatch(r"[A-Z0-9-]{1,10}", t):
        raise SECError(f"'{ticker}' is not a valid ticker symbol")
    return t


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


class SECClient:
    def __init__(
        self,
        user_agent: Optional[str] = None,
        session: Optional[requests.Session] = None,
        cache_dir: Optional[str] = ".cache/sec",
        min_interval: float = 0.12,
        retry_waits: Tuple[float, ...] = (2, 5),
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ):
        ua = (user_agent or os.getenv("SEC_USER_AGENT") or "").strip()
        if "@" not in ua or len(ua.split()) < 2:
            raise SECError(
                "SEC_USER_AGENT is missing or incomplete. SEC requires your name and email. "
                "Add a line like this to .env:  SEC_USER_AGENT=Your Name your.email@example.com"
            )
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.min_interval = min_interval  # 0.12s keeps us under SEC's 10 requests per second
        self.retry_waits = retry_waits
        self.sleep = sleep
        self.clock = clock
        self._last_request = 0.0
        self.warnings: List[str] = []

    # ------------------------------------------------------------------ HTTP

    def _wait_turn(self) -> None:
        gap = self.clock() - self._last_request
        if gap < self.min_interval:
            self.sleep(self.min_interval - gap)
        self._last_request = self.clock()

    def _fetch(self, url: str) -> bytes:
        last_problem = ""
        for attempt in range(len(self.retry_waits) + 1):
            self._wait_turn()
            try:
                response = self.session.get(url, timeout=30)
            except requests.RequestException as e:
                last_problem = f"network error: {e}"
            else:
                status = response.status_code
                if status == 200:
                    return response.content
                if status == 404:
                    raise SECNotFound(f"SEC has no data at {url} (404)")
                if status == 403:
                    raise SECError(
                        "SEC refused the request (403). Check that SEC_USER_AGENT in .env contains "
                        "your real name and email. SEC also blocks clients that send more than "
                        "10 requests per second."
                    )
                if status not in RETRYABLE_STATUS:
                    raise SECError(f"SEC returned HTTP {status} for {url}")
                last_problem = f"HTTP {status}"
            if attempt < len(self.retry_waits):
                self.sleep(self.retry_waits[attempt])
        raise SECError(f"Could not get {url} from SEC after {len(self.retry_waits) + 1} attempts ({last_problem})")

    def _cache_path(self, url: str) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        return self.cache_dir / hashlib.sha256(url.encode()).hexdigest()

    def get(self, url: str, max_age: Optional[float]) -> bytes:
        """Fetch a URL, using the disk cache. max_age=None means the cached
        copy never expires (used for filing documents, which never change)."""
        path = self._cache_path(url)
        if path is not None and path.exists():
            age = self.clock() - path.stat().st_mtime
            if max_age is None or age < max_age:
                return path.read_bytes()
        try:
            data = self._fetch(url)
        except SECNotFound:
            raise
        except SECError as e:
            if path is not None and path.exists():
                saved = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                self.warnings.append(f"SEC could not be reached ({e}). Used the copy saved on {saved}.")
                return path.read_bytes()
            raise
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return data

    def get_json(self, url: str, max_age: Optional[float]) -> dict:
        try:
            return json.loads(self.get(url, max_age))
        except json.JSONDecodeError:
            raise SECError(f"SEC sent a response that is not valid JSON for {url}")

    # ------------------------------------------------------------------ API

    def lookup_ticker(self, ticker: str) -> Tuple[str, str]:
        """Return (10-digit CIK, company name)."""
        wanted = normalize_ticker(ticker)
        data = self.get_json(TICKERS_URL, max_age=ONE_DAY)
        for entry in data.values():
            if str(entry.get("ticker", "")).upper() == wanted:
                return f"{int(entry['cik_str']):010d}", str(entry.get("title", wanted))
        raise SECNotFound(
            f"Ticker {wanted} is not in SEC's ticker list. Check the spelling. "
            "Only companies registered with the SEC are listed."
        )

    def list_companies(self) -> List[Tuple[str, str]]:
        """Every (ticker, company name) in SEC's ticker list, sorted by ticker.
        A company with several share classes appears once per ticker."""
        data = self.get_json(TICKERS_URL, max_age=ONE_DAY)
        companies = {}
        for entry in data.values():
            ticker = str(entry.get("ticker", "")).upper().strip()
            if ticker and ticker not in companies:
                companies[ticker] = str(entry.get("title", ticker)).strip()
        return sorted(companies.items())

    def latest_filing(self, cik: str, form: str, company: str = "") -> FilingRef:
        """Most recent original filing of this form. Amendments such as
        10-K/A or 20-F/A are excluded because they often contain only part of
        a report. Raises FormNotFiled when the company files a different form."""
        if form not in SUPPORTED_FORMS:
            raise ValueError(f"Form must be one of {SUPPORTED_FORMS}")
        sub = self.get_json(SUBMISSIONS_URL.format(cik=cik), max_age=ONE_DAY)
        try:
            recent = sub["filings"]["recent"]
            forms = recent["form"]
            accessions = recent["accessionNumber"]
            filed = recent["filingDate"]
            report_dates = recent["reportDate"]
            documents = recent["primaryDocument"]
        except KeyError as e:
            raise SECError(f"SEC submissions data is missing an expected field: {e}")

        matches = [i for i, f in enumerate(forms) if f == form]
        if not matches:
            name = company or cik
            present = set(forms)
            if form == "10-K" and "20-F" in present:
                raise FormNotFiled(f"{name} files annual reports on Form 20-F, not 10-K.", alternative="20-F")
            if form == "20-F" and "10-K" in present:
                raise FormNotFiled(f"{name} files annual reports on Form 10-K, not 20-F.", alternative="10-K")
            if form == "10-Q" and "20-F" in present:
                raise FormNotFiled(f"{name} is a foreign issuer that files Form 20-F once a year and no 10-Q "
                                   "quarterly reports. Choose 20-F to analyse its annual report.")
            if "40-F" in present:
                raise FormNotFiled(f"{name} files Form 40-F as a Canadian issuer. RiskLens supports "
                                   "10-K, 10-Q and 20-F filers.")
            raise FormNotFiled(f"No {form} was found among the recent filings of {name}.")

        i = max(matches, key=lambda k: filed[k])
        doc = documents[i]
        if not doc:
            raise SECError(f"Filing {accessions[i]} has no primary document listed")
        url = ARCHIVE_URL.format(cik_int=int(cik), acc_nodash=accessions[i].replace("-", ""), doc=doc)
        return FilingRef(
            company=sub.get("name") or company or cik,
            cik=cik,
            form=form,
            accession=accessions[i],
            filed=_parse_date(filed[i]),
            period_end=_parse_date(report_dates[i]),
            url=url,
            sic=str(sub.get("sic") or "") or None,
            sic_description=sub.get("sicDescription") or None,
        )

    def download_document(self, filing: FilingRef) -> bytes:
        if not filing.url:
            raise SECError("Filing has no document URL")
        return self.get(filing.url, max_age=None)

    def company_facts(self, cik: str) -> dict:
        return self.get_json(COMPANYFACTS_URL.format(cik=cik), max_age=ONE_DAY)
