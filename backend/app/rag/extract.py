"""Turn FIA regulation PDFs into citable chunks.

Chunking follows the document's own article structure rather than a fixed
character window. That matters for this corpus specifically: an answer about
"the minimum car weight" is worthless without "per Article 4.1", and a chunk
that straddles two articles cannot be cited at all.

Extraction quirks this handles, all observed in the real 2026 PDFs:

- Article IDs appear with a section prefix in the sporting regulations
  ("B1.3.6") and without one in the technical regulations ("3.5.1").
- Appendices use uppercase headings ("APPENDIX B56:") with no dotted number.
  Without treating those as boundaries, every appendix accumulates into the
  last numbered article -- which produced a single 22,000-character chunk.
- Page furniture repeats on all ~200 pages, and in the technical regulations
  the page number is *inside* that line, so identical-line detection misses
  it. Digits are masked before counting.
- pypdf maps some ligatures in FIA's fonts to stray glyphs, so "Officials"
  extracts as "O=icials".
"""

import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from pypdf import PdfReader

logger = logging.getLogger(__name__)

# "1.3.6" (technical) or "B1.3.6" (sporting)
ARTICLE_RE = re.compile(r"^([A-Z]?\d+(?:\.\d+)+)\s+(.*)$")
# Structural headings with no dotted number: "ARTICLE B9: ..." / "APPENDIX B56: ..."
HEADING_RE = re.compile(r"^((?:ARTICLE|APPENDIX)\s+[A-Z]?\d+[A-Z]?)\s*:\s*(.*)$", re.I)
# A table-of-contents entry ends with the page number it points at.
TOC_TAIL_RE = re.compile(r"\s\d{1,3}$")
ISSUE_RE = re.compile(r"Issue\s+(\d+)", re.I)

# Long articles are split further so a single chunk stays embeddable.
MAX_CHUNK_CHARS = 1500
CHUNK_OVERLAP_CHARS = 150
# Bare section titles ("Insurance") carry no answerable content on their own;
# they are kept as the `title` on following chunks instead.
MIN_CHUNK_CHARS = 40

# Repair for ligatures pypdf cannot map: the "ff" ligature in FIA's fonts
# extracts as "=", so "Officials" arrives as "O=icials". Deliberately narrow --
# it requires a letter immediately before and a lowercase letter immediately
# after, so equations in the technical regulations ("XF = 630", "a=1") are
# untouched.
LIGATURE_FIXES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"(?<=[A-Za-z])=(?=[a-z])"), "ff"),
)

# Frequency-based furniture detection is meaningless on a handful of pages: on
# a single page every line occurs on 100% of pages. Below this, assume there is
# no repeated furniture to strip.
MIN_PAGES_FOR_BOILERPLATE = 3


@dataclass
class Chunk:
    """One citable passage of a regulation document."""

    doc_id: str
    doc_title: str
    issue: str
    article: str
    title: str
    text: str
    page: int
    part: int = 1
    total_parts: int = 1

    @property
    def citation(self) -> str:
        base = f"{self.doc_title}, Issue {self.issue}, Article {self.article}"
        if self.total_parts > 1:
            return f"{base} (part {self.part} of {self.total_parts})"
        return base

    @property
    def embed_text(self) -> str:
        """Text sent to the embedding model.

        The article number and section title are prepended so that lexically
        distinctive identifiers are part of the vector, and so a query naming a
        section ("insurance requirements") matches even when the body text
        never repeats the heading.
        """
        header = f"{self.article} {self.title}".strip()
        return f"{header}\n{self.text}" if header else self.text

    @property
    def chunk_id(self) -> str:
        return f"{self.doc_id}:{self.article}:{self.part}"


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for pattern, replacement in LIGATURE_FIXES:
        text = pattern.sub(replacement, text)
    return text


def _mask_digits(line: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", line)).strip()


def _is_structural(line: str) -> bool:
    """True when a line opens an article or a heading.

    Such lines are never page furniture, however often their text repeats.
    This matters because digit masking collapses distinct articles that share a
    title -- "4.1.1 Bodywork" and "4.2.1 Bodywork" both mask to
    "#.#.# Bodywork" -- and without this exemption a title reused across the
    document would take every one of its articles with it.
    """
    return bool(ARTICLE_RE.match(line) or HEADING_RE.match(line))


def _find_boilerplate(pages: list[list[str]], threshold: float = 0.5) -> set[str]:
    """Digit-masked lines appearing on at least `threshold` of pages."""
    if len(pages) < MIN_PAGES_FOR_BOILERPLATE:
        return set()

    counts: Counter[str] = Counter()
    for lines in pages:
        masked_lines = {
            _mask_digits(line)
            for line in lines
            if line.strip() and not _is_structural(line)
        }
        for masked in masked_lines:
            counts[masked] += 1

    cutoff = max(MIN_PAGES_FOR_BOILERPLATE, len(pages) * threshold)
    return {masked for masked, count in counts.items() if count >= cutoff}


def _is_toc_page(lines: list[str]) -> bool:
    """True when every article-like line on the page points at a page number."""
    article_lines = [line for line in lines if ARTICLE_RE.match(line)]
    if len(article_lines) < 3:
        return False
    return all(TOC_TAIL_RE.search(line) for line in article_lines)


def _split_long(text: str) -> list[str]:
    """Split at sentence boundaries, with overlap, when over MAX_CHUNK_CHARS."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]

    sentences = re.split(r"(?<=[.;:])\s+", text)
    parts: list[str] = []
    current = ""

    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > MAX_CHUNK_CHARS:
            parts.append(current.strip())
            tail = current[-CHUNK_OVERLAP_CHARS:]
            current = f"{tail} {sentence}"
        else:
            current = f"{current} {sentence}".strip()

    if current.strip():
        parts.append(current.strip())

    # A single sentence longer than the limit still needs hard splitting.
    result: list[str] = []
    for part in parts:
        while len(part) > MAX_CHUNK_CHARS:
            result.append(part[:MAX_CHUNK_CHARS])
            part = part[MAX_CHUNK_CHARS - CHUNK_OVERLAP_CHARS :]
        if part:
            result.append(part)
    return result


@dataclass
class _Section:
    article: str
    title: str
    page: int
    lines: list[str] = field(default_factory=list)

    @property
    def body(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.lines)).strip()


def read_pages(pdf_path: str) -> list[list[str]]:
    """Extract and clean each page of a PDF into a list of lines."""
    reader = PdfReader(pdf_path)
    pages: list[list[str]] = []
    for page in reader.pages:
        raw = _clean(page.extract_text() or "")
        pages.append([line.strip() for line in raw.split("\n")])
    return pages


def extract_chunks(pdf_path: str, doc_id: str, doc_title: str) -> list[Chunk]:
    """Parse a regulation PDF into citable chunks."""
    return parse_pages(read_pages(pdf_path), doc_id, doc_title)


def parse_pages(
    pages: list[list[str]], doc_id: str, doc_title: str
) -> list[Chunk]:
    """Segment already-extracted page lines into citable chunks.

    Kept separate from PDF reading so the parsing rules can be tested against
    synthetic input rather than a 3MB binary.
    """
    boilerplate = _find_boilerplate(pages)
    issue = "unknown"
    for lines in pages[:3]:
        for line in lines:
            match = ISSUE_RE.search(line)
            if match:
                issue = match.group(1).lstrip("0") or match.group(1)
                break
        if issue != "unknown":
            break

    sections: list[_Section] = []
    current: _Section | None = None
    # The most recent bare heading, carried onto following articles as context.
    current_title = ""

    for page_number, lines in enumerate(pages, start=1):
        body = [
            line
            for line in lines
            if line.strip()
            and (_is_structural(line) or _mask_digits(line) not in boilerplate)
        ]
        if _is_toc_page(body):
            continue

        for line in body:
            heading = HEADING_RE.match(line)
            if heading:
                if current:
                    sections.append(current)
                current_title = heading.group(2).strip() or heading.group(1)
                # Becomes the active section so the prose that follows the
                # heading is captured, rather than dropped for want of an
                # enclosing article.
                current = _Section(
                    article=heading.group(1).upper(),
                    title=current_title,
                    page=page_number,
                    lines=[],
                )
                continue

            article = ARTICLE_RE.match(line)
            if article:
                if current:
                    sections.append(current)
                remainder = article.group(2).strip()
                current = _Section(
                    article=article.group(1),
                    title=current_title,
                    page=page_number,
                    lines=[remainder] if remainder else [],
                )
                continue

            if current:
                current.lines.append(line)

    if current:
        sections.append(current)

    chunks: list[Chunk] = []
    for section in sections:
        body = section.body
        if len(body) < MIN_CHUNK_CHARS:
            # Title-only entry: remember it as context, emit nothing.
            if body:
                current_title = body
            continue

        parts = _split_long(body)
        for index, part in enumerate(parts, start=1):
            chunks.append(
                Chunk(
                    doc_id=doc_id,
                    doc_title=doc_title,
                    issue=issue,
                    article=section.article,
                    title=section.title,
                    text=part,
                    page=section.page,
                    part=index,
                    total_parts=len(parts),
                )
            )

    logger.info(
        "Extracted %d chunks from %s (issue %s, %d pages)",
        len(chunks),
        doc_id,
        issue,
        len(pages),
    )
    return chunks
