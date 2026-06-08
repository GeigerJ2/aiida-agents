"""Shows that tests/test_eval_harness.py asserts nothing about the agent.

Two demonstrations of the same point, using the verbatim assertion logic from the
PR's tests:

1. A StubAgent whose `run` raises and which has `tools = []`.
2. `class Empty: pass` -- an object with no methods or attributes at all.

In both, the assertion still passes, because it only inspects the value the test
itself stuffed into the mock. Run: `python3 review/prove_tautology.py`.
"""

from unittest.mock import AsyncMock, MagicMock, patch


def _make_agent_result(response_text, tool_names):
    """Verbatim from tests/test_eval_harness.py."""
    result = MagicMock()
    result.data = response_text
    parts = []
    for name in tool_names:
        part = MagicMock()
        part.tool_name = name
        parts.append(part)
    msg = MagicMock()
    msg.parts = parts
    result.all_messages.return_value = [msg]
    return result


async def run_verbatim_test_body(agent, *, create):
    """The exact body of test_agent_list_processes, against whatever `agent` is.

    `create=True` is only needed when `agent` has no `run` attribute to patch,
    which is itself the point: the test never touches a real method.
    """
    with patch.object(agent, "run", new_callable=AsyncMock, create=create) as mock_run:
        mock_run.return_value = _make_agent_result(
            "Here are the 5 most recent processes.",
            ["list_processes"],
        )
        result = await agent.run("List the last 5 processes in the database")

    tools_called = [
        p.tool_name
        for msg in result.all_messages()
        for p in msg.parts
        if hasattr(p, "tool_name")
    ]
    assert "list_processes" in tools_called


# --- Demonstration 1: a deliberately broken agent (no tools, run() raises) ----
class StubAgent:
    tools = []

    async def run(self, *_a, **_k):
        raise RuntimeError("real agent.run would need an LLM")


# --- Demonstration 2: an object with no methods or attributes at all ----------
class Empty:
    pass


async def main():
    import asyncio  # noqa: F401  (kept local; only main() is async)

    await run_verbatim_test_body(StubAgent(), create=False)
    print("PASSED against StubAgent (tools=[], run() raises)")

    await run_verbatim_test_body(Empty(), create=True)
    print("PASSED against `class Empty: pass` (no methods at all)")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
