"""
Tool implementations and dispatch.

Tools are registered in TOOL_REGISTRY and dispatched by name. The registry
replaces an if/elif chain that had no fallback branch, so an unrecognised tool
name used to leave `result` unbound and kill the relay's downstream loop.
"""

import inspect
import logging
import os

from tavily import AsyncTavilyClient

from app import crud
from app.config import F1_DOMAINS
from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

_tavily: AsyncTavilyClient | None = None


def _get_tavily() -> AsyncTavilyClient:
    global _tavily
    if _tavily is None:
        _tavily = AsyncTavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    return _tavily


async def get_user_history(user_id: str) -> str:
    """Recent conversation history, used to personalise answers."""
    async with AsyncSessionLocal() as db:
        history = await crud.get_recent_history(db, user_id)

    if not history:
        return "No previous history for this user. Treat them as a new listener."

    formatted = "\n".join(f"{m.role}: {m.content}" for m in history)
    return f"Recent history for {user_id}:\n{formatted}"


async def f1_search(query: str, recent: bool = False) -> str:
    """Search trusted F1 sources.

    `include_domains` is the tool-level half of the domain lock: even if an
    off-topic query reaches this function, there is nothing off-topic to find.
    """
    response = await _get_tavily().search(
        query,
        max_results=3,
        include_domains=F1_DOMAINS,
        topic="news" if recent else "general",
    )

    results = response.get("results", [])
    if not results:
        return (
            f"No results on trusted F1 sources for: {query}. "
            "Say you could not find it rather than guessing."
        )

    return "\n\n".join(f"{r['title']}\n{r['content']}" for r in results)


TOOL_REGISTRY = {
    "get_user_history": get_user_history,
    "f1_search": f1_search,
}


async def dispatch(name: str, args: dict, *, user_id: str) -> str:
    """Run a tool by name and always return a string for the model.

    Never raises: a tool failure is reported back to the model as text so the
    conversation can continue, rather than breaking the relay.
    """
    handler = TOOL_REGISTRY.get(name)
    if handler is None:
        logger.warning("Model called unknown tool: %r", name)
        return f"Unknown tool: {name}. Tell the user you cannot do that."

    # Drop hallucinated arguments, and supply the session's user_id if the
    # model omitted it.
    params = inspect.signature(handler).parameters
    call_args = {k: v for k, v in (args or {}).items() if k in params}
    if "user_id" in params and not call_args.get("user_id"):
        call_args["user_id"] = user_id

    try:
        return await handler(**call_args)
    except TypeError as exc:
        logger.warning("Bad arguments for %s: %s", name, exc)
        return f"Could not run {name}: invalid arguments."
    except Exception:
        logger.exception("Tool %s failed", name)
        return f"{name} is unavailable right now. Tell the user you could not look that up."
