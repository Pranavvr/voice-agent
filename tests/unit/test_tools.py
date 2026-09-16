"""Tests for tool dispatch and the domain-locked search tool."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app import tools
from app.config import F1_DOMAINS


def _fake_tavily(results=None, *, exc=None):
    client = MagicMock()
    if exc is not None:
        client.search = AsyncMock(side_effect=exc)
    else:
        client.search = AsyncMock(return_value={"results": results or []})
    return client


# --- dispatch -------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_tool_returns_a_message_instead_of_raising():
    """The old if/elif chain left `result` unbound here and killed the relay."""
    result = await tools.dispatch("definitely_not_a_tool", {}, user_id="u1")
    assert "Unknown tool" in result


@pytest.mark.asyncio
async def test_hallucinated_arguments_are_dropped(monkeypatch):
    client = _fake_tavily([{"title": "T", "content": "C"}])
    monkeypatch.setattr(tools, "_get_tavily", lambda: client)

    await tools.dispatch(
        "f1_search",
        {"query": "monza results", "nonsense": 123},
        user_id="u1",
    )

    assert "nonsense" not in client.search.call_args.kwargs
    assert client.search.call_args.args[0] == "monza results"


@pytest.mark.asyncio
async def test_missing_user_id_is_filled_from_the_session(monkeypatch):
    captured = {}

    async def _fake_history(user_id: str) -> str:
        captured["user_id"] = user_id
        return "history"

    monkeypatch.setitem(tools.TOOL_REGISTRY, "get_user_history", _fake_history)

    await tools.dispatch("get_user_history", {}, user_id="session_user")
    assert captured["user_id"] == "session_user"


@pytest.mark.asyncio
async def test_tool_failure_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(tools, "_get_tavily", lambda: _fake_tavily(exc=RuntimeError("boom")))

    result = await tools.dispatch("f1_search", {"query": "monza"}, user_id="u1")
    assert "unavailable" in result.lower()


# --- f1_search ------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_is_restricted_to_f1_domains(monkeypatch):
    """Tool-level half of the domain lock: nothing off-topic is reachable."""
    client = _fake_tavily([{"title": "T", "content": "C"}])
    monkeypatch.setattr(tools, "_get_tavily", lambda: client)

    await tools.f1_search("mango milkshake recipe")

    assert client.search.call_args.kwargs["include_domains"] == F1_DOMAINS


@pytest.mark.asyncio
async def test_recent_flag_selects_the_news_topic(monkeypatch):
    client = _fake_tavily([{"title": "T", "content": "C"}])
    monkeypatch.setattr(tools, "_get_tavily", lambda: client)

    await tools.f1_search("fp2 results", recent=True)
    assert client.search.call_args.kwargs["topic"] == "news"

    await tools.f1_search("1988 season", recent=False)
    assert client.search.call_args.kwargs["topic"] == "general"


@pytest.mark.asyncio
async def test_empty_results_tell_the_model_not_to_guess(monkeypatch):
    monkeypatch.setattr(tools, "_get_tavily", lambda: _fake_tavily([]))

    result = await tools.f1_search("something with no coverage")
    assert "No results" in result
    assert "guessing" in result
