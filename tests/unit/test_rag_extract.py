"""Tests for regulation PDF parsing.

The synthetic pages below reproduce quirks observed in the real 2026 FIA PDFs:
repeated page furniture with an embedded page number, a table of contents whose
entries end in page numbers, appendix headings with no dotted article number,
and ligatures pypdf renders as stray glyphs.
"""

from app.rag import extract
from app.rag.extract import Chunk, parse_pages

DOC_ID = "test_doc"
DOC_TITLE = "Test Regulations"


def _page(*lines: str) -> list[str]:
    return list(lines)


def _furnished(*lines: str) -> list[str]:
    """A page carrying the repeated furniture seen in the real documents."""
    return [
        "SECTION B: SPORTING REGULATIONS",
        "©2026 Federation Internationale de l'Automobile",
        "Issue 05",
        *lines,
    ]


_WORDS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel")


def _filler(sentences: int, seed: str = "zulu") -> str:
    """Body prose.

    `seed` keeps it distinct across pages: text repeated verbatim on most pages
    is page furniture by definition, and the extractor is right to strip it.
    The seed is a word rather than a number because furniture detection masks
    digits, which would make numbered variants collide.
    """
    return " ".join(
        f"Regulation clause {seed} {_WORDS[i % len(_WORDS)]} sets out substantive content."
        for i in range(sentences)
    )


# --- boilerplate ----------------------------------------------------------


def test_repeated_page_furniture_is_stripped():
    pages = [
        _furnished(f"B1.{i}.1 Something", _filler(3, seed=_WORDS[i]))
        for i in range(1, 6)
    ]
    chunks = parse_pages(pages, DOC_ID, DOC_TITLE)

    assert chunks
    for chunk in chunks:
        assert "Federation Internationale" not in chunk.text
        assert "SECTION B" not in chunk.text


def test_page_numbers_inside_furniture_do_not_defeat_detection():
    """The technical regulations embed the page number in the header line, so
    identical-line matching misses it. Digits are masked before counting."""
    pages = [
        [
            f"2026 Formula 1 Technical Regulations {n} 24 June 2024",
            "Issue 8",
            f"4.{n}.1 Bodywork",
            _filler(3, seed=_WORDS[n % len(_WORDS)]),
        ]
        for n in range(1, 8)
    ]
    chunks = parse_pages(pages, DOC_ID, DOC_TITLE)

    assert chunks
    for chunk in chunks:
        assert "Technical Regulations" not in chunk.text


# --- table of contents ----------------------------------------------------


def test_contents_pages_are_skipped():
    toc = _page(
        "CONTENTS:",
        "B1.1 General Principles 4",
        "B1.2 FIA Delegates 4",
        "B1.3 Officials 5",
        "B1.4 Insurance 6",
    )
    body = _page("B1.4.1 " + _filler(3))
    chunks = parse_pages([toc, body, _page()], DOC_ID, DOC_TITLE)

    assert [c.article for c in chunks] == ["B1.4.1"]


# --- article segmentation -------------------------------------------------


def test_article_ids_parse_with_and_without_a_section_prefix():
    sporting = parse_pages([_page("B1.3.6 " + _filler(3))], DOC_ID, DOC_TITLE)
    technical = parse_pages([_page("3.5.1 " + _filler(3))], DOC_ID, DOC_TITLE)

    assert sporting[0].article == "B1.3.6"
    assert technical[0].article == "3.5.1"


def test_appendix_headings_end_the_preceding_article():
    """Without this, every appendix accumulated into the last numbered article
    and produced a single 22,000-character chunk."""
    pages = [
        _page(
            "B11.8.5 " + _filler(3),
            "APPENDIX B56: APPROVED CHANGES FOR SUBSEQUENT YEARS",
            _filler(3),
        )
    ]
    chunks = parse_pages(pages, DOC_ID, DOC_TITLE)
    articles = [c.article for c in chunks]

    assert "B11.8.5" in articles
    assert any(a.startswith("APPENDIX") for a in articles)
    body = next(c for c in chunks if c.article == "B11.8.5")
    assert "APPROVED CHANGES" not in body.text


def test_continuation_lines_join_their_article():
    pages = [_page("B1.4.1 The Promoter must procure", "third party insurance cover.")]
    chunks = parse_pages(pages, DOC_ID, DOC_TITLE)

    assert len(chunks) == 1
    assert chunks[0].text == "The Promoter must procure third party insurance cover."


def test_section_titles_become_metadata_not_chunks():
    pages = [
        _page(
            "ARTICLE B1: ORGANISATION OF A COMPETITION",
            "B1.4.1 " + _filler(3),
        )
    ]
    chunks = parse_pages(pages, DOC_ID, DOC_TITLE)
    article = next(c for c in chunks if c.article == "B1.4.1")

    assert article.title == "ORGANISATION OF A COMPETITION"


# --- chunk sizing ---------------------------------------------------------


def test_long_articles_are_split_with_parts_recorded():
    pages = [_page("B2.1.1 " + _filler(120))]
    chunks = parse_pages(pages, DOC_ID, DOC_TITLE)

    assert len(chunks) > 1
    assert all(c.article == "B2.1.1" for c in chunks)
    assert all(len(c.text) <= extract.MAX_CHUNK_CHARS for c in chunks)
    assert [c.part for c in chunks] == list(range(1, len(chunks) + 1))
    assert all(c.total_parts == len(chunks) for c in chunks)


def test_a_single_oversized_sentence_is_still_split():
    pages = [_page("B2.1.1 " + "x" * (extract.MAX_CHUNK_CHARS * 3))]
    chunks = parse_pages(pages, DOC_ID, DOC_TITLE)

    assert all(len(c.text) <= extract.MAX_CHUNK_CHARS for c in chunks)


# --- text cleaning --------------------------------------------------------


def test_mangled_ligatures_are_repaired():
    assert extract._clean("O=icials") == "Officials"
    assert extract._clean("signiﬁcant") == "significant"


def test_equations_are_not_treated_as_ligatures():
    """The technical regulations are full of "XF = 630"; the repair must not
    corrupt them."""
    assert extract._clean("XF = 630 and XC = -800") == "XF = 630 and XC = -800"
    assert extract._clean("a=1") == "a=1"


# --- citation -------------------------------------------------------------


def test_citation_names_document_issue_and_article():
    chunk = Chunk(
        doc_id=DOC_ID,
        doc_title="2026 F1 Sporting Regulations",
        issue="5",
        article="B5.13.4",
        title="Safety Car",
        text="text",
        page=42,
    )
    assert chunk.citation == "2026 F1 Sporting Regulations, Issue 5, Article B5.13.4"
    assert chunk.chunk_id == f"{DOC_ID}:B5.13.4:1"


def test_multipart_citation_identifies_the_part():
    chunk = Chunk(
        doc_id=DOC_ID,
        doc_title="Doc",
        issue="5",
        article="B1.1.1",
        title="",
        text="text",
        page=1,
        part=2,
        total_parts=3,
    )
    assert chunk.citation.endswith("(part 2 of 3)")


def test_embed_text_includes_article_and_title():
    """Article numbers are lexically distinctive but semantically weak, so they
    are embedded alongside the body rather than kept only in metadata."""
    chunk = Chunk(
        doc_id=DOC_ID,
        doc_title="Doc",
        issue="5",
        article="B1.4.1",
        title="Insurance",
        text="The Promoter must procure cover.",
        page=1,
    )
    assert chunk.embed_text.startswith("B1.4.1 Insurance")
    assert "must procure cover" in chunk.embed_text


def test_issue_number_is_read_from_the_document():
    chunks = parse_pages(
        [_page("Issue 05", "B1.1.1 " + _filler(3))], DOC_ID, DOC_TITLE
    )
    assert chunks[0].issue == "5"


def test_issue_is_unknown_when_the_document_does_not_state_one():
    chunks = parse_pages([_page("B1.1.1 " + _filler(3))], DOC_ID, DOC_TITLE)
    assert chunks[0].issue == "unknown"
