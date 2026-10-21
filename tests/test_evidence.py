import pytest

from tests.sample_filing import sample_paragraphs
from utils.evidence import assign_confidence, normalize, paragraphs_from_text, verify_quote
from utils.schemas import EvidenceQuote


@pytest.fixture
def paras():
    return {p.id: p for p in sample_paragraphs()}


def test_paragraph_splitting_skips_headings(paras):
    # The "Item 1A. Risk Factors" heading is too short to be a paragraph
    assert "1A-0001" in paras
    assert paras["1A-0001"].text.startswith("We rely on a single third-party supplier")
    assert len(paras) == 6


def test_exact_quote_passes(paras):
    q = EvidenceQuote(paragraph_id="1A-0001", quote="We rely on a single third-party supplier")
    assert verify_quote(q, paras, min_words=6) == (True, "")


def test_curly_quotes_case_and_spacing_are_tolerated(paras):
    q = EvidenceQuote(
        paragraph_id="1A-0003",
        quote="“we   experienced a RANSOMWARE incident that encrypted systems”",
    )
    assert verify_quote(q, paras, min_words=6)[0] is True


def test_paraphrase_is_rejected(paras):
    q = EvidenceQuote(paragraph_id="1A-0001", quote="The company depends on one outside chip vendor")
    ok, reason = verify_quote(q, paras, min_words=6)
    assert not ok
    assert "does not appear" in reason


def test_wrong_paragraph_is_rejected_with_location(paras):
    q = EvidenceQuote(paragraph_id="1A-0001", quote="we have not completed a tested disaster recovery plan")
    ok, reason = verify_quote(q, paras, min_words=6)
    assert not ok
    assert "1A-0002" in reason


def test_unknown_paragraph_is_rejected(paras):
    q = EvidenceQuote(paragraph_id="1A-9999", quote="We rely on a single third-party supplier")
    ok, reason = verify_quote(q, paras, min_words=6)
    assert not ok
    assert "does not exist" in reason


def test_short_quote_is_rejected(paras):
    q = EvidenceQuote(paragraph_id="1A-0003", quote="ransomware incident")
    assert verify_quote(q, paras, min_words=6)[0] is False


def test_ellipsis_is_rejected(paras):
    q = EvidenceQuote(paragraph_id="1A-0003", quote="we experienced a ransomware incident ... for nine days")
    ok, reason = verify_quote(q, paras, min_words=6)
    assert not ok
    assert "ellipsis" in reason


def test_quote_stitched_across_paragraphs_is_rejected(paras):
    q = EvidenceQuote(
        paragraph_id="1A-0001",
        quote="halt our production for several months. Our primary manufacturing facility",
    )
    assert verify_quote(q, paras, min_words=6)[0] is False


def test_normalize():
    assert normalize("  It’s   a\n\ttest — ok ") == "it's a test - ok"


@pytest.mark.parametrize(
    "n, corroborated, expected",
    [
        (0, False, None),
        (0, True, None),
        (1, False, "Low"),
        (1, True, "Low"),
        (2, False, "Medium"),
        (2, True, "High"),
        (3, False, "High"),
    ],
)
def test_confidence_rules(n, corroborated, expected):
    level, _ = assign_confidence(n, corroborated, high_min=3, high_min_if_corroborated=2, medium_min=2)
    assert level == expected


def test_paragraphs_from_text_numbering():
    text = "First paragraph that is long enough to keep.\n\nShort\n\nSecond paragraph that is also long enough."
    paras = paragraphs_from_text(text, section="S", id_prefix="7")
    assert [p.id for p in paras] == ["7-0001", "7-0002"]
