"""ChromaDB vector store for the regulation corpus.

Chroma runs embedded (`PersistentClient`) inside the backend container rather
than as a separate service. The corpus is read-only at runtime and rebuilt from
source PDFs when the collection is empty, so there is nothing to persist across
a teardown -- which is what a separate Chroma service plus an EFS mount would
exist to protect.

Retrieval is hybrid, but narrowly so. Embeddings are poor at exact
identifiers -- "Article 4.1", "Article 4.2" and "Article 3.1" all land in
nearly the same place in vector space -- and a regulation corpus is mostly
identifiers. So a query naming an article gets an exact metadata lookup
alongside the semantic search, and the two result sets are merged. That targets
the actual failure mode without maintaining a second full-text index.
"""

import asyncio
import logging
import os
import re

import chromadb
from chromadb.config import Settings
from openai import AsyncOpenAI

from app.rag.extract import Chunk

logger = logging.getLogger(__name__)

CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_index")
COLLECTION_NAME = "f1_regulations"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

# OpenAI accepts batched embedding inputs; keep batches modest so a single
# failure costs little and progress is visible in logs during ingestion.
EMBED_BATCH_SIZE = 100

# Matches an article reference in a user query: "article 4.1", "B5.13.4", "3.5".
ARTICLE_QUERY_RE = re.compile(r"\b([A-Z]?\d+(?:\.\d+)+)\b", re.I)

_client: chromadb.ClientAPI | None = None
_openai: AsyncOpenAI | None = None


def _get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _openai


def get_collection() -> chromadb.Collection:
    """The regulations collection, created on first use."""
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=CHROMA_PATH,
            settings=Settings(anonymized_telemetry=False, allow_reset=False),
        )
    return _client.get_or_create_collection(
        name=COLLECTION_NAME,
        # Cosine matches how OpenAI embeddings are meant to be compared;
        # Chroma's default is squared L2.
        metadata={"hnsw:space": "cosine"},
    )


def count() -> int:
    try:
        return get_collection().count()
    except Exception:
        logger.exception("Could not read Chroma collection count")
        return 0


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed `texts` in batches, preserving order."""
    vectors: list[list[float]] = []
    client = _get_openai()

    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[start : start + EMBED_BATCH_SIZE]
        response = await client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        # The API documents order preservation, but sorting by index makes this
        # independent of that guarantee.
        vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
        logger.info("Embedded %d/%d chunks", min(start + len(batch), len(texts)), len(texts))

    return vectors


async def add_chunks(chunks: list[Chunk]) -> int:
    """Embed and store `chunks`. Returns the number written."""
    if not chunks:
        return 0

    embeddings = await embed_texts([c.embed_text for c in chunks])
    collection = get_collection()

    collection.upsert(
        ids=[c.chunk_id for c in chunks],
        embeddings=embeddings,
        documents=[c.text for c in chunks],
        metadatas=[
            {
                "doc_id": c.doc_id,
                "doc_title": c.doc_title,
                "issue": c.issue,
                "article": c.article,
                "title": c.title,
                "page": c.page,
                "citation": c.citation,
            }
            for c in chunks
        ],
    )
    return len(chunks)


def _rows(result: dict) -> list[dict]:
    """Flatten a Chroma query/get response into a list of rows."""
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []

    # `query` nests per-query-embedding; `get` does not.
    if documents and isinstance(documents[0], list):
        documents = documents[0]
        metadatas = metadatas[0] if metadatas else []

    return [
        {"text": doc, "metadata": meta or {}}
        for doc, meta in zip(documents, metadatas)
    ]


def _exact_article_matches(query: str, limit: int) -> list[dict]:
    """Metadata lookup for any article number named in the query."""
    references = {m.group(1).upper() for m in ARTICLE_QUERY_RE.finditer(query)}
    if not references:
        return []

    try:
        result = get_collection().get(
            where={"article": {"$in": sorted(references)}},
            limit=limit,
        )
    except Exception:
        logger.exception("Exact article lookup failed for %r", query)
        return []

    rows = _rows(result)
    if rows:
        logger.info("Exact article match for %s", sorted(references))
    return rows


async def search(query: str, n_results: int = 4) -> list[dict]:
    """Retrieve regulation passages for `query`.

    Exact article matches are returned first, then semantic matches, deduped by
    chunk text. Runs the two lookups concurrently.
    """
    collection = get_collection()

    async def _semantic() -> list[dict]:
        embeddings = await embed_texts([query])
        return _rows(
            collection.query(query_embeddings=embeddings, n_results=n_results)
        )

    exact_task = asyncio.to_thread(_exact_article_matches, query, n_results)
    semantic, exact = await asyncio.gather(
        _semantic(), exact_task, return_exceptions=True
    )

    rows: list[dict] = []
    for group in (exact, semantic):
        if isinstance(group, BaseException):
            logger.warning("Retrieval branch failed: %s", group)
            continue
        rows.extend(group)

    seen: set[str] = set()
    deduped: list[dict] = []
    for row in rows:
        key = row["text"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    return deduped[:n_results]
