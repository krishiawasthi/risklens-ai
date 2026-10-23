import pytest
import requests

from tests.sample_sec import (
    ACC_10K,
    CIK,
    FOREIGN_SUBMISSIONS,
    FakeSession,
    doc_url_10k,
    standard_routes,
    submissions_url,
    tickers_url,
)
from utils.sec_client import SECClient, SECError, SECNotFound, normalize_ticker

UA = "Test Person test@example.com"


def client(routes=None, tmp_path=None, **kw):
    session = FakeSession(routes if routes is not None else standard_routes())
    c = SECClient(
        user_agent=UA,
        session=session,
        cache_dir=str(tmp_path) if tmp_path else None,
        sleep=lambda s: None,
        **kw,
    )
    return c, session


@pytest.mark.parametrize("ua", ["", "nobody", "test@example.com"])
def test_user_agent_must_have_name_and_email(ua, monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(SECError, match="SEC_USER_AGENT"):
        SECClient(user_agent=ua, session=FakeSession())


def test_user_agent_header_is_sent():
    c, session = client()
    assert session.headers["User-Agent"] == UA


def test_ticker_normalisation():
    assert normalize_ticker(" brk.b ") == "BRK-B"
    with pytest.raises(SECError):
        normalize_ticker("not a ticker!")


def test_lookup_ticker():
    c, _ = client()
    assert c.lookup_ticker("exmc") == (CIK, "Example Manufacturing Corp")
    assert c.lookup_ticker("BRK.B")[0] == "0000888888"


def test_unknown_ticker():
    c, _ = client()
    with pytest.raises(SECNotFound, match="not in SEC's ticker list"):
        c.lookup_ticker("ZZZZ")


def test_latest_10k_skips_amendment_and_builds_url():
    c, _ = client()
    f = c.latest_filing(CIK, "10-K")
    assert f.accession == ACC_10K  # the 10-K/A filed later is ignored
    assert str(f.period_end) == "2025-12-31"
    assert f.url == doc_url_10k()
    assert f.sic == "3829"


def test_latest_10q():
    c, _ = client()
    assert c.latest_filing(CIK, "10-Q").form == "10-Q"


def test_foreign_filer_gets_clear_message():
    routes = {submissions_url("0000777777"): [(200, FOREIGN_SUBMISSIONS)]}
    c, _ = client(routes)
    with pytest.raises(SECNotFound, match="20-F"):
        c.latest_filing("0000777777", "10-K")


def test_403_explains_user_agent():
    c, _ = client({tickers_url(): [(403, b"")]})
    with pytest.raises(SECError, match="SEC_USER_AGENT"):
        c.lookup_ticker("EXMC")


def test_503_is_retried_then_succeeds():
    routes = standard_routes()
    routes[tickers_url()] = [(503, b""), routes[tickers_url()][0]]
    c, session = client(routes)
    assert c.lookup_ticker("EXMC")[0] == CIK
    assert session.calls.count(tickers_url()) == 2


def test_gives_up_after_retries():
    c, session = client({tickers_url(): [(503, b"")]})
    with pytest.raises(SECError, match="after 3 attempts"):
        c.lookup_ticker("EXMC")


def test_cache_avoids_second_request(tmp_path):
    c, session = client(tmp_path=tmp_path)
    c.lookup_ticker("EXMC")
    c.lookup_ticker("EXMC")
    assert session.calls.count(tickers_url()) == 1


def test_stale_cache_used_when_sec_unreachable(tmp_path):
    c, _ = client(tmp_path=tmp_path)
    c.lookup_ticker("EXMC")  # fills the cache

    offline = {tickers_url(): [requests.ConnectionError("no network")]}
    c2, _ = client(offline, tmp_path=tmp_path)
    c2.clock = lambda: 10**12  # far in the future, so the cache is "expired"
    assert c2.lookup_ticker("EXMC")[0] == CIK
    assert any("Used the copy saved" in w for w in c2.warnings)


def test_rate_limit_spaces_requests():
    waits = []
    now = [100.0]
    session = FakeSession(standard_routes())
    c = SECClient(user_agent=UA, session=session, cache_dir=None, sleep=waits.append, clock=lambda: now[0])
    c.lookup_ticker("EXMC")
    c.latest_filing(CIK, "10-K")  # second request at the same clock time
    assert waits and waits[0] == pytest.approx(0.12)


def test_list_companies_sorted_and_unique():
    c, _ = client()
    companies = c.list_companies()
    assert companies == sorted(companies)
    assert ("EXMC", "Example Manufacturing Corp") in companies
    assert len({t for t, _ in companies}) == len(companies)
