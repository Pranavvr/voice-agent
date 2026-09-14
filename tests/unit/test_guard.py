"""Tests for the scope gate.

The gate is the enforcement point for the F1 domain lock, so these cover both
the happy path and every way it can fail -- a gate that breaks open silently is
worse than no gate at all.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import guard


def _fake_client(content=None, *, exc=None):
    """Build a stand-in for AsyncOpenAI returning `content` (or raising `exc`)."""
    client = MagicMock()
    if exc is not None:
        client.chat.completions.create = AsyncMock(side_effect=exc)
        return client

    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


@pytest.mark.asyncio
async def test_f1_question_is_allowed(monkeypatch):
    monkeypatch.setattr(guard, "_get_client", lambda: _fake_client("IN_SCOPE"))
    assert await guard.is_in_scope("who won at Monza?") is True


@pytest.mark.asyncio
async def test_off_topic_question_is_refused(monkeypatch):
    monkeypatch.setattr(guard, "_get_client", lambda: _fake_client("OUT_OF_SCOPE"))
    assert await guard.is_in_scope("how do I make a mango milkshake?") is False


@pytest.mark.asyncio
async def test_empty_utterance_is_refused_without_calling_the_api(monkeypatch):
    client = _fake_client("IN_SCOPE")
    monkeypatch.setattr(guard, "_get_client", lambda: client)

    assert await guard.is_in_scope("   ") is False
    client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_recent_turns_are_given_to_the_classifier(monkeypatch):
    """Follow-ups like "what about him?" carry no F1 keywords of their own."""
    client = _fake_client("IN_SCOPE")
    monkeypatch.setattr(guard, "_get_client", lambda: client)

    await guard.is_in_scope(
        "what about him?",
        [("user", "how did Verstappen do?"), ("assistant", "He finished P2.")],
    )

    messages = client.chat.completions.create.call_args.kwargs["messages"]
    prompt = messages[-1]["content"]
    assert "Verstappen" in prompt
    assert "what about him?" in prompt


@pytest.mark.asyncio
async def test_only_the_last_n_turns_are_sent(monkeypatch):
    client = _fake_client("IN_SCOPE")
    monkeypatch.setattr(guard, "_get_client", lambda: client)

    turns = [("user", f"turn {i}") for i in range(guard.CONTEXT_TURNS + 3)]
    await guard.is_in_scope("and then?", turns)

    prompt = client.chat.completions.create.call_args.kwargs["messages"][-1]["content"]
    assert "turn 0" not in prompt
    assert f"turn {guard.CONTEXT_TURNS + 2}" in prompt


@pytest.mark.asyncio
async def test_timeout_fails_open(monkeypatch):
    async def _hang(*args, **kwargs):
        await asyncio.sleep(5)

    client = MagicMock()
    client.chat.completions.create = _hang
    monkeypatch.setattr(guard, "_get_client", lambda: client)
    monkeypatch.setattr(guard, "CLASSIFIER_TIMEOUT_SECONDS", 0.01)

    assert await guard.is_in_scope("who won?") is guard.FAIL_OPEN


@pytest.mark.asyncio
async def test_api_error_fails_open(monkeypatch):
    monkeypatch.setattr(
        guard, "_get_client", lambda: _fake_client(exc=RuntimeError("API down"))
    )
    assert await guard.is_in_scope("who won?") is guard.FAIL_OPEN


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["maybe", "", None])
async def test_unparseable_verdict_fails_open(monkeypatch, verdict):
    monkeypatch.setattr(guard, "_get_client", lambda: _fake_client(verdict))
    assert await guard.is_in_scope("who won?") is guard.FAIL_OPEN


@pytest.mark.asyncio
async def test_verdict_is_case_and_whitespace_insensitive(monkeypatch):
    monkeypatch.setattr(guard, "_get_client", lambda: _fake_client("  out_of_scope\n"))
    assert await guard.is_in_scope("give me a recipe") is False
