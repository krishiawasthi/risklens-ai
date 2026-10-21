"""Turn a filing's HTML into numbered paragraphs, split by Item.

How sections are found:
  1. Every short line that starts with "Item <number>" is a heading candidate.
     Cross-references inside sentences ("see Item 1A") are not, because they
     do not start a line.
  2. A candidate must contain the section's title keyword in its own line or
     the next line. This tells Part I Item 4 (Controls and Procedures) apart
     from Part II Item 4 (Mine Safety) in a 10-Q.
  3. The table of contents also matches, so for each Item the candidate
     followed by the MOST text is chosen.
  4. A section ends at the next heading for a DIFFERENT Item. Some filings
     (Microsoft's, for example) repeat "Item 1A" as a page header on every
     page, and those repeats must not end the section.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, NamedTuple, Tuple, Union

from utils.evidence import paragraphs_from_text
from utils.schemas import FilingSection, Paragraph


class SectionSpec(NamedTuple):
    title: str
    keyword: str  # must appear in the heading line or the line after it


# Items RiskLens knows how to find. Keys are lower case.
SECTION_SPECS: Dict[str, Dict[str, SectionSpec]] = {
    "10-K": {
        "1": SectionSpec("Business", "business"),
        "1a": SectionSpec("Risk Factors", "risk factors"),
        "1c": SectionSpec("Cybersecurity", "cybersecurity"),
        "3": SectionSpec("Legal Proceedings", "legal proceedings"),
        "7": SectionSpec("Management's Discussion and Analysis", "discussion and analysis"),
        "9a": SectionSpec("Controls and Procedures", "controls and procedures"),
    },
    "10-Q": {
        "1": SectionSpec("Legal Proceedings", "legal proceedings"),
        "1a": SectionSpec("Risk Factors", "risk factors"),
        "2": SectionSpec("Management's Discussion and Analysis", "discussion and analysis"),
        "4": SectionSpec("Controls and Procedures", "controls and procedures"),
    },
}

HEADING_RE = re.compile(r"^item\s+(\d{1,2}[a-c]?)(?![0-9a-z])", re.IGNORECASE)
MAX_HEADING_CHARS = 150
SHORT_SECTION_CHARS = 500

BLOCK_TAGS = [
    "p", "div", "br", "tr", "li", "table", "section", "article", "blockquote",
    "pre", "ul", "ol", "center", "dd", "dt", "h1", "h2", "h3", "h4", "h5", "h6",
]


def html_to_lines(html: Union[str, bytes]) -> List[str]:
    """One line per block of text, with hidden content removed."""
    import warnings

    from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

    # Inline XBRL filings are XHTML and start with an XML declaration. Reading
    # them as HTML is intended (it tolerates markup errors), so this warning
    # is silenced for this call only.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:  # lxml not installed
            soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "head", "noscript", "ix:header"]):
        tag.decompose()
    # Hidden blocks, including the inline XBRL header that holds machine-readable data
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.IGNORECASE)):
        if not getattr(tag, "decomposed", False):
            tag.decompose()
    for cell in soup.find_all(["td", "th"]):
        cell.append(" ")  # keep table cells on one line, separated by a space
    for tag in soup.find_all(BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")

    lines = (re.sub(r"\s+", " ", line).strip() for line in soup.get_text().split("\n"))
    return remove_boilerplate([line for line in lines if line])


BOILERPLATE_MAX_CHARS = 120
FOOTER_RE = re.compile(r"form\s+10-[kq]\b", re.IGNORECASE)


def remove_boilerplate(lines: List[str]) -> List[str]:
    """Drop page footers and running headers so they never become evidence.

    A short line is dropped if it looks like a page footer ("Company | 2025
    Form 10-K | 17") or if it repeats 3 or more times once page numbers are
    ignored. Item headings are always kept, because the splitter needs them.
    """
    def key(line: str) -> str:
        return re.sub(r"\d+", "#", line.lower())

    counts = Counter(key(l) for l in lines if len(l) < BOILERPLATE_MAX_CHARS)
    kept = []
    for line in lines:
        if len(line) < BOILERPLATE_MAX_CHARS and not HEADING_RE.match(line):
            footer = FOOTER_RE.search(line) and ("|" in line or re.search(r"\d+\s*$", line))
            if footer or counts[key(line)] >= 3:
                continue
        kept.append(line)
    return kept


def _heading_text(lines: List[str], idx: int) -> str:
    text = lines[idx] + " " + (lines[idx + 1] if idx + 1 < len(lines) else "")
    return text.lower().replace("’", "'")


def find_headings(lines: List[str]) -> List[Tuple[int, str]]:
    found = []
    for i, line in enumerate(lines):
        if len(line) <= MAX_HEADING_CHARS:
            m = HEADING_RE.match(line)
            if m:
                found.append((i, m.group(1).lower()))
    return found


def split_sections(lines: List[str], form: str, items: List[str]) -> List[FilingSection]:
    specs = SECTION_SPECS[form]
    headings = find_headings(lines)
    sections: List[FilingSection] = []

    for item in items:
        key = item.lower()
        spec = specs[key]
        best = None  # (chars, start, end, repeated headers skipped)
        for k, (idx, heading_id) in enumerate(headings):
            if heading_id != key or spec.keyword not in _heading_text(lines, idx):
                continue
            end, skipped = len(lines), 0
            for next_idx, next_id in headings[k + 1:]:
                if next_id != key:
                    end = next_idx
                    break
                skipped += 1
            chars = sum(len(line) for line in lines[idx + 1:end])
            if best is None or chars > best[0]:
                best = (chars, idx + 1, end, skipped)

        label = item.upper()
        if best is None:
            sections.append(
                FilingSection(item=label, title=spec.title, found=False, note="Heading not found in the document")
            )
            continue

        chars, start, end, skipped = best
        paragraphs = paragraphs_from_text(
            "\n\n".join(lines[start:end]), section=f"Item {label}. {spec.title}", id_prefix=label
        )
        notes = []
        if chars < SHORT_SECTION_CHARS:
            notes.append("Very short section. It may say 'Not applicable' or refer to another document.")
        if skipped:
            notes.append(f"Ignored {skipped} repeated 'Item {label}' page header(s) inside the section.")
        note = " ".join(notes)
        sections.append(
            FilingSection(item=label, title=spec.title, found=True, chars=chars, paragraphs=paragraphs, note=note)
        )
    return sections


def all_paragraphs(sections: List[FilingSection]) -> List[Paragraph]:
    return [p for s in sections for p in s.paragraphs]
