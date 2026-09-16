"""
Scope gate.

Decides whether a transcribed utterance is allowed to reach the model. This is
the enforcement point for the F1 domain lock: `main.py` withholds
`response.create` when this returns False, so the model never generates a free
answer to an off-topic question.

Runs on the critical path of every turn, so it is deliberately one small call
with a hard timeout.
"""

import asyncio
import logging
import os

from openai import AsyncOpenAI

from app.config import CLASSIFIER_PROMPT

logger = logging.getLogger(__name__)

CLASSIFIER_MODEL = os.getenv("CLASSIFIER_MODEL", "gpt-5.6-luna")
CLASSIFIER_TIMEOUT_SECONDS = float(os.getenv("CLASSIFIER_TIMEOUT_SECONDS", "1.5"))

# How many prior turns the classifier sees. Voice conversations are highly
# elliptical ("what about him?", "and last year?"), and those utterances carry
# no F1 keywords of their own -- without context they get rejected.
CONTEXT_TURNS = 4

# On timeout or API error, allow the turn through. A classifier outage that
# refuses everything leaves the agent completely unusable, whereas failing open
# degrades to an occasional off-topic answer -- and the domain-locked search
# tool still prevents off-topic *retrieval*.
FAIL_OPEN = True

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


def _build_messages(utterance: str, recent_turns: list[tuple[str, str]]) -> list[dict]:
    if recent_turns:
        context = "\n".join(
            f"{role}: {content}" for role, content in recent_turns[-CONTEXT_TURNS:]
        )
    else:
        context = "(no previous turns)"

    return [
        {"role": "system", "content": CLASSIFIER_PROMPT},
        {
            "role": "user",
            "content": (
                f"Conversation so far:\n{context}\n\n"
                f"Utterance to classify:\n{utterance}"
            ),
        },
    ]


async def is_in_scope(
    utterance: str,
    recent_turns: list[tuple[str, str]] | None = None,
) -> bool:
    """Return True if `utterance` belongs in an F1 conversation.

    `recent_turns` is an ordered list of (role, content) pairs; only the last
    CONTEXT_TURNS are used.
    """
    if not utterance.strip():
        return False

    try:
        response = await asyncio.wait_for(
            _get_client().chat.completions.create(
                model=CLASSIFIER_MODEL,
                messages=_build_messages(utterance, recent_turns or []),
            ),
            timeout=CLASSIFIER_TIMEOUT_SECONDS,
        )
        verdict = (response.choices[0].message.content or "").strip().upper()
    except asyncio.TimeoutError:
        logger.warning(
            "Scope classifier timed out after %ss; failing %s",
            CLASSIFIER_TIMEOUT_SECONDS,
            "open" if FAIL_OPEN else "closed",
        )
        return FAIL_OPEN
    except Exception:
        logger.exception("Scope classifier failed; failing %s", "open" if FAIL_OPEN else "closed")
        return FAIL_OPEN

    if "OUT_OF_SCOPE" in verdict:
        return False
    if "IN_SCOPE" in verdict:
        return True

    logger.warning("Scope classifier returned unexpected verdict: %r", verdict)
    return FAIL_OPEN
