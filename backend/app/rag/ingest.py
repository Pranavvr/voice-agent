"""Fetch FIA regulation PDFs, chunk them, and load them into Chroma.

Runs in the background on startup when the collection is empty, and can be
invoked directly:

    PYTHONPATH=backend python -m app.rag.ingest [--force]

Rebuilding on startup rather than persisting the index is a deliberate trade:
the corpus is ~1,600 chunks and roughly 125k tokens, so a full rebuild costs
well under a cent in embeddings. Paying that per deploy is cheaper -- in money
and in infrastructure -- than an EFS-backed Chroma service whose only job is
surviving a teardown.

The regulations are reissued frequently (the 2026 Sporting Regulations reached
Issue 05 within seven months), so source URLs are configuration, and the issue
number is carried into chunk metadata for citation.
"""

import argparse
import asyncio
import logging
import os
import tempfile

import httpx

from app.rag import store
from app.rag.extract import extract_chunks

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_SECONDS = 180

# Each entry is (doc_id, human title, source URL). Override via env to pick up
# a newer issue without a code change.
REGULATION_SOURCES: list[tuple[str, str, str]] = [
    (
        "fia_2026_sporting",
        "2026 F1 Sporting Regulations",
        os.getenv(
            "FIA_SPORTING_URL",
            "https://www.fia.com/system/files/documents/"
            "fia_2026_f1_regulations_-_section_b_sporting_-_iss_05_-_2026-02-27.pdf",
        ),
    ),
    (
        "fia_2026_technical",
        "2026 F1 Technical Regulations",
        os.getenv(
            "FIA_TECHNICAL_URL",
            "https://www.fia.com/sites/default/files/"
            "fia_2026_formula_1_technical_regulations_issue_8_-_2024-06-24.pdf",
        ),
    ),
]

# Set once ingestion finishes so /health and the retrieval tool can report
# honestly while the corpus is still loading.
_ready = False


def is_ready() -> bool:
    return _ready or store.count() > 0


async def _download(url: str, destination: str) -> None:
    async with httpx.AsyncClient(
        timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        with open(destination, "wb") as handle:
            handle.write(response.content)


async def ingest_source(doc_id: str, doc_title: str, url: str) -> int:
    """Download, chunk, and store one regulation document."""
    with tempfile.TemporaryDirectory() as workdir:
        path = os.path.join(workdir, f"{doc_id}.pdf")
        logger.info("Downloading %s", url)
        await _download(url, path)

        # pypdf is synchronous and CPU-bound; keep it off the event loop.
        chunks = await asyncio.to_thread(extract_chunks, path, doc_id, doc_title)

    written = await store.add_chunks(chunks)
    logger.info("Stored %d chunks for %s", written, doc_id)
    return written


async def ingest_all(force: bool = False) -> int:
    """Populate the collection. No-op when already populated unless `force`."""
    global _ready

    existing = store.count()
    if existing and not force:
        logger.info("Regulation corpus already loaded (%d chunks); skipping", existing)
        _ready = True
        return existing

    total = 0
    for doc_id, doc_title, url in REGULATION_SOURCES:
        try:
            total += await ingest_source(doc_id, doc_title, url)
        except Exception:
            # One unavailable document should not leave the corpus empty.
            logger.exception("Ingestion failed for %s", doc_id)

    _ready = total > 0
    logger.info("Ingestion complete: %d chunks", total)
    return total


def auto_ingest_enabled() -> bool:
    """Whether startup should build the corpus.

    On by default so a deployed task is self-sufficient. CI sets this false:
    ingestion downloads ~5MB of PDFs and spends real embedding calls, neither
    of which belongs in a unit test run.
    """
    return os.getenv("RAG_AUTO_INGEST", "true").strip().lower() not in {
        "false",
        "0",
        "no",
    }


async def ingest_in_background() -> None:
    """Entry point for startup. Never raises into the lifespan."""
    if not auto_ingest_enabled():
        logger.info("RAG_AUTO_INGEST is off; skipping regulation ingestion")
        return

    try:
        await ingest_all()
    except Exception:
        logger.exception("Background ingestion failed; f1_knowledge will be unavailable")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load FIA regulations into Chroma")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest even if the collection is already populated",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(ingest_all(force=args.force))


if __name__ == "__main__":
    main()
