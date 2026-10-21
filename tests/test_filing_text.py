from tests.sample_sec import sample_10k_html
from utils.filing_text import find_headings, html_to_lines, split_sections


def lines():
    return html_to_lines(sample_10k_html())


def sections(items=("1A", "1C", "3", "9A")):
    return {s.item: s for s in split_sections(lines(), "10-K", list(items))}


def test_hidden_xbrl_header_and_styles_removed():
    text = " ".join(lines())
    assert "HIDDEN XBRL HEADER" not in text
    assert "color:red" not in text


def test_table_cells_stay_on_one_line():
    assert "Item 1A. Risk Factors 4" in lines()  # table of contents row


def test_inline_xbrl_text_is_kept_in_its_sentence():
    assert any(l.startswith("We depend on information technology systems to process orders") for l in lines())


def test_cross_reference_is_not_a_heading():
    ls = lines()
    for idx, _ in find_headings(ls):
        assert ls[idx].lower().startswith("item")
    assert not any("Investors should read" in ls[idx] for idx, _ in find_headings(ls))


def test_real_section_chosen_over_table_of_contents():
    s = sections()["1A"]
    assert s.found
    texts = [p.text for p in s.paragraphs]
    assert texts[0].startswith("We rely on a single third-party supplier")
    assert len(texts) == 4


def test_heading_split_over_two_lines_is_found():
    # The fixture has "Item 1A." and "Risk Factors" on separate lines
    assert sections()["1A"].found


def test_heading_inside_table_row_is_found():
    s = sections()["1C"]
    assert s.found and len(s.paragraphs) == 2


def test_upper_case_heading_is_found():
    assert sections()["3"].found


def test_section_stops_at_next_item():
    texts = " ".join(p.text for p in sections()["1A"].paragraphs)
    assert "Unresolved Staff Comments" not in texts
    assert "Chief Information Security Officer" not in texts


def test_page_footer_and_short_lines_are_not_paragraphs():
    texts = [p.text for p in sections()["1A"].paragraphs]
    assert not any("Form 10-K | 5" in t for t in texts)
    assert not any(t == "Operational and supply chain risks" for t in texts)


def test_repeated_running_header_is_removed():
    from utils.filing_text import remove_boilerplate

    page = "Example Manufacturing Corp Annual Report Page {}"
    ls = [page.format(1), "Item 1A. Risk Factors", page.format(2), "A real paragraph", page.format(3)]
    assert remove_boilerplate(ls) == ["Item 1A. Risk Factors", "A real paragraph"]


def test_curly_apostrophe_kept_in_text():
    texts = [p.text for p in sections()["9A"].paragraphs]
    assert texts[1].startswith("Management’s remediation plan")


def test_paragraph_ids_use_item_prefix():
    s = sections()["9A"]
    assert [p.id for p in s.paragraphs] == ["9A-0001", "9A-0002"]
    assert s.paragraphs[0].section == "Item 9A. Controls and Procedures"


def test_missing_section_is_reported():
    s = sections(items=("7",))["7"]
    assert s.found is False and s.paragraphs == []


TEN_Q = b"""<html><body>
<div>PART I</div>
<div>Item 2. Management's Discussion and Analysis of Financial Condition</div>
<div>Revenue declined because a major customer reduced orders during the quarter significantly.</div>
<div>Item 4. Controls and Procedures</div>
<div>Our disclosure controls were not effective as of June 30 because of a material weakness in access controls.</div>
<div>PART II</div>
<div>Item 1. Legal Proceedings</div>
<div>A regulator opened an investigation into our data handling practices during the quarter under review.</div>
<div>Item 1A. Risk Factors</div>
<div>There have been no material changes to the risk factors disclosed in our most recent annual report.</div>
<div>Item 4. Mine Safety Disclosures</div>
<div>Not applicable.</div>
</body></html>"""


def test_10q_part_one_item_4_not_confused_with_part_two_item_4():
    secs = {s.item: s for s in split_sections(html_to_lines(TEN_Q), "10-Q", ["4", "1", "1A"])}
    assert secs["4"].paragraphs[0].text.startswith("Our disclosure controls were not effective")
    assert secs["1"].paragraphs[0].text.startswith("A regulator opened an investigation")
    assert secs["1A"].note  # very short section is flagged


def test_xhtml_with_xml_declaration_gives_no_warning():
    import warnings

    doc = b'<?xml version="1.0" encoding="utf-8"?><html><body><div>Item 1A. Risk Factors</div></body></html>'
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning would fail the test
        assert html_to_lines(doc) == ["Item 1A. Risk Factors"]


def test_repeated_item_page_headers_do_not_end_the_section():
    """Microsoft-style layout: every page starts with 'PART I' and 'Item 1A'."""
    ls = [
        "Item 1A. Risk Factors 14",  # table of contents
        "Item 1B. Unresolved Staff Comments 30",
        "ITEM 1A. RISK FACTORS",
        "Barriers to entry in many of our businesses are low and competition is intense.",
        "PART I",
        "Item 1A",  # page header
        "Security of our information technology could be compromised by attackers.",
        "PART I",
        "Item 1A",  # page header
        "Our global operations subject us to risks that may harm our results of operations.",
        "ITEM 1B. UNRESOLVED STAFF COMMENTS",
        "We have received no written comments regarding our periodic or current reports.",
    ]
    s = split_sections(ls, "10-K", ["1A"])[0]
    texts = [p.text for p in s.paragraphs]
    assert len(texts) == 3
    assert texts[-1].startswith("Our global operations")
    assert "2 repeated" in s.note
    assert not any("written comments" in t for t in texts)
