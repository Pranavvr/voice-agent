"""Tests for the Chroma-backed regulation store.

These run against a real Chroma instance in a temp directory with stubbed
embeddings. Mocking Chroma itself would only assert that mocks were called;
exercising it for real catches the things that actually break -- response
shapes, metadata round-tripping, and the exact-article lookup.
"""

import hashlib

import pytest

from app.rag import store
from app.rag.extract import Chunk


def _vector(text: str) -> list[float]:
    """Deterministic pseudo-embedding: identical text gives identical vectors."""
    digest = hashlib.sha256(text.encode()).digest()
    return [byte / 255.0 for byte in digest[:16]]


async def _fake_embed(texts: list[str]) -> list[list[float]]:
    return [_vector(t) for t in texts]


def _chunk(article: str, text: str, doc_id: str = "sporting") -> Chunk:
    return Chunk(
        doc_id=doc_id,
        doc_title="2026 F1 Sporting Regulations",
        issue="5",
        article=article,
        title="Section",
        text=text,
        page=1,
    )


@pytest.fixture
def chroma(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CHROMA_PATH", str(tmp_path / "index"))
    monkeypatch.setattr(store, "_client", None)
    monkeypatch.setattr(store, "embed_texts", _fake_embed)
    yield
    monkeypatch.setattr(store, "_client", None)


@pytest.mark.asyncio
async def test_chunks_round_trip_with_their_citation(chroma):
    await store.add_chunks([_chunk("B5.13.4", "The Safety Car leads the field.")])

    results = await store.search("The Safety Car leads the field.")

    assert results
    assert results[0]["text"] == "The Safety Car leads the field."
    citation = results[0]["metadata"]["citation"]
    assert "Issue 5" in citation
    assert "B5.13.4" in citation


@pytest.mark.asyncio
async def test_count_reflects_what_was_stored(chroma):
    assert store.count() == 0
    await store.add_chunks([_chunk("B1.1.1", "a" * 60), _chunk("B1.1.2", "b" * 60)])
    assert store.count() == 2


@pytest.mark.asyncio
async def test_adding_nothing_is_a_no_op(chroma):
    assert await store.add_chunks([]) == 0


@pytest.mark.asyncio
async def test_reingesting_the_same_article_upserts(chroma):
    """Chunk ids are derived from doc, article and part, so a reissued document
    replaces its articles instead of duplicating them."""
    await store.add_chunks([_chunk("B1.1.1", "original text here, long enough")])
    await store.add_chunks([_chunk("B1.1.1", "amended text here, long enough")])

    assert store.count() == 1


# --- exact article lookup -------------------------------------------------


@pytest.mark.asyncio
async def test_query_naming_an_article_retrieves_it_exactly(chroma):
    """Embeddings cannot separate "Article 4.1" from "Article 4.2", so a named
    article is looked up by metadata rather than by vector similarity."""
    await store.add_chunks(
        [
            _chunk("B4.1", "Rules about tyres and their allocation."),
            _chunk("B4.2", "Rules about fuel and its sampling."),
            _chunk("B9.9", "Completely unrelated provision about personnel."),
        ]
    )

    results = await store.search("what does article B4.2 say?")

    assert any(r["metadata"]["article"] == "B4.2" for r in results)


@pytest.mark.asyncio
async def test_exact_match_is_ranked_before_semantic_matches(chroma):
    await store.add_chunks(
        [
            _chunk("B4.2", "Rules about fuel and its sampling."),
            _chunk("B7.1", "Something else entirely about scrutineering."),
        ]
    )

    results = await store.search("article B4.2")

    assert results[0]["metadata"]["article"] == "B4.2"


@pytest.mark.asyncio
async def test_results_are_deduped_across_both_lookups(chroma):
    """The same chunk can surface from the exact and semantic branches."""
    text = "Rules about fuel and its sampling, stated at sufficient length."
    await store.add_chunks([_chunk("B4.2", text)])

    results = await store.search("B4.2 Section\n" + text)

    assert len([r for r in results if r["text"] == text]) == 1


@pytest.mark.asyncio
async def test_query_without_an_article_number_still_searches(chroma):
    await store.add_chunks([_chunk("B5.1", "The Safety Car procedure is as follows.")])

    results = await store.search("what happens under the safety car")

    assert results


@pytest.mark.asyncio
async def test_search_on_an_empty_collection_returns_nothing(chroma):
    assert await store.search("anything at all") == []


# --- response shape -------------------------------------------------------


def test_rows_flattens_the_nested_query_shape():
    """`query` nests results per query embedding; `get` does not."""
    nested = {"documents": [["a", "b"]], "metadatas": [[{"x": 1}, {"x": 2}]]}
    flat = {"documents": ["a", "b"], "metadatas": [{"x": 1}, {"x": 2}]}

    assert store._rows(nested) == store._rows(flat)
    assert [r["text"] for r in store._rows(nested)] == ["a", "b"]


def test_rows_tolerates_missing_metadata():
    assert store._rows({"documents": ["a"], "metadatas": None}) == []
    assert store._rows({}) == []


@pytest.mark.parametrize(
    "query,expected",
    [
        ("what does article 4.1 say", {"4.1"}),
        ("explain B5.13.4 please", {"B5.13.4"}),
        ("compare 3.1 and 3.2", {"3.1", "3.2"}),
        ("who won at Monza", set()),
        ("the 2026 season", set()),
    ],
)
def test_article_references_are_detected_in_queries(query, expected):
    found = {m.group(1).upper() for m in store.ARTICLE_QUERY_RE.finditer(query)}
    assert found == expected
