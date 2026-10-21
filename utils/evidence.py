"""Evidence validation.

The AI proposes quotes. This module checks each one against the actual
filing text. A quote only counts if it appears, word for word, in the
paragraph the AI cited. This is what stops fabricated evidence reaching
the risk register.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Tuple

from utils.schemas import EvidenceQuote, Paragraph

# Typographic characters that commonly differ between the filing and the
# AI's copy of it. Mapping them is not paraphrase tolerance: the words and
# their order must still match exactly.
_CHAR_MAP = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        " ": " ",
    }
)


def normalize(text: str) -> str:
    """Lower-case, unify quotes and dashes, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text).translate(_CHAR_MAP)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def _strip_wrapping_quotes(text: str) -> str:
    return text.strip().strip("\"'“”‘’").strip()


def verify_quote(
    quote: EvidenceQuote, paragraphs: Dict[str, Paragraph], min_words: int
) -> Tuple[bool, str]:
    """Return (True, "") if the quote is valid evidence, else (False, reason)."""
    text = _strip_wrapping_quotes(quote.quote)

    if "..." in text or "…" in text:
        return False, "Quote contains an ellipsis; only continuous verbatim text is accepted"
    if len(text.split()) < min_words:
        return False, f"Quote is shorter than {min_words} words"

    cited = paragraphs.get(quote.paragraph_id)
    if cited is None:
        return False, f"Paragraph ID {quote.paragraph_id} does not exist"

    needle = normalize(text)
    if needle in normalize(cited.text):
        return True, ""

    other = find_paragraph_containing(needle, paragraphs)
    if other is not None:
        return False, f"Quote appears in paragraph {other}, not in the cited paragraph {quote.paragraph_id}"
    return False, "Quote does not appear in the filing text"


def find_paragraph_containing(normalized_needle: str, paragraphs: Dict[str, Paragraph]) -> Optional[str]:
    for pid, para in paragraphs.items():
        if normalized_needle in normalize(para.text):
            return pid
    return None


def assign_confidence(
    distinct_paragraphs: int,
    corroborated: bool,
    high_min: int,
    high_min_if_corroborated: int,
    medium_min: int,
) -> Tuple[Optional[str], str]:
    """Rule-based confidence. Returns (level or None if rejected, reason)."""
    n = distinct_paragraphs
    plural = "paragraph" if n == 1 else "paragraphs"
    if n == 0:
        return None, "No verified evidence"
    if n >= high_min:
        return "High", f"Verified quotes from {n} different {plural}"
    if corroborated and n >= high_min_if_corroborated:
        return "High", f"Verified quotes from {n} {plural}, supported by a deterministic financial rule"
    if n >= medium_min:
        return "Medium", f"Verified quotes from {n} different {plural}"
    reason = f"Verified quote from only {n} {plural}"
    if corroborated:
        reason += " (a deterministic rule in this category also fired)"
    return "Low", reason


def paragraphs_from_text(text: str, section: str, id_prefix: str, min_chars: int = 40) -> List[Paragraph]:
    """Split plain text on blank lines into numbered paragraphs.

    Very short lines (headings, page numbers) are skipped because they are
    not useful evidence.
    """
    blocks = [re.sub(r"\s+", " ", b).strip() for b in re.split(r"\n\s*\n", text)]
    paragraphs = []
    for block in blocks:
        if len(block) < min_chars:
            continue
        paragraphs.append(
            Paragraph(id=f"{id_prefix}-{len(paragraphs) + 1:04d}", section=section, text=block)
        )
    return paragraphs
