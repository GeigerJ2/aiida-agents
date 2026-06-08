"""AiiDA exploration agent using Pydantic AI."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider

from aiida_agents.mcp.tools.nodes import get_node_inputs, get_node_outputs, query_nodes
from aiida_agents.mcp.tools.processes import get_process_status, list_processes
from aiida_agents.mcp.tools.structures import search_structures
from aiida_agents.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_TOOLS = [
    get_process_status,
    list_processes,
    query_nodes,
    get_node_inputs,
    get_node_outputs,
    search_structures,
]


def get_model() -> Model:
    """Return the configured model from ``AIIDA_AGENT_PROVIDER`` / ``AIIDA_AGENT_MODEL``.

    Providers:
      * ``ollama`` (default): any local model; ``OLLAMA_BASE_URL`` overrides the
        ``http://localhost:11434/v1`` default.
      * ``openai`` / ``anthropic``: hosted models; read their own API-key env vars.
      * ``openai-compatible``: any OpenAI-compatible endpoint (DeepSeek, Together,
        OpenRouter, vLLM, ...). Requires ``AIIDA_AGENT_BASE_URL``;
        ``AIIDA_AGENT_API_KEY`` is optional (placeholder for keyless local servers).

    :raises ValueError: if the provider is not one of the above.
    """
    provider = os.getenv("AIIDA_AGENT_PROVIDER", "ollama").lower()
    model_name = os.getenv("AIIDA_AGENT_MODEL", "qwen3.5:2b")

    if provider == "ollama":
        # OllamaProvider has no default and raises UserError when OLLAMA_BASE_URL
        # is unset, so resolve base_url here (no os.environ write).
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        return OpenAIChatModel(model_name, provider=OllamaProvider(base_url=base_url))
    if provider == "openai":
        return OpenAIChatModel(model_name)  # OpenAIProvider reads OPENAI_API_KEY
    if provider == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel  # lazy: optional extra

        return AnthropicModel(model_name)  # AnthropicProvider reads ANTHROPIC_API_KEY
    if provider == "openai-compatible":
        base_url = os.getenv("AIIDA_AGENT_BASE_URL")
        if not base_url:
            msg = (
                "AIIDA_AGENT_PROVIDER='openai-compatible' requires AIIDA_AGENT_BASE_URL "
                "(e.g. https://api.deepseek.com/v1)."
            )
            raise ValueError(msg)
        api_key = os.getenv("AIIDA_AGENT_API_KEY", "api-key-not-set")
        return OpenAIChatModel(
            model_name, provider=OpenAIProvider(base_url=base_url, api_key=api_key)
        )

    msg = (
        f"Unsupported AIIDA_AGENT_PROVIDER {provider!r}; use 'ollama', 'openai', "
        "'anthropic', or 'openai-compatible'."
    )
    raise ValueError(msg)


def get_agent() -> Agent:
    """Build and return the AiiDA exploration agent. No profile needed here."""
    return Agent(get_model(), tools=_TOOLS, system_prompt=SYSTEM_PROMPT)


async def ask(agent: Agent, question: str) -> None:  # pragma: no cover
    """Run a query through the agent and stream the response to stdout."""
    logger.debug("Running agent query: %s", question)
    async with agent.run_stream(question) as result:
        sys.stdout.write("Agent: ")
        printed = 0
        async for text in result.stream_text(debounce_by=None):
            sys.stdout.write(text[printed:])
            sys.stdout.flush()
            printed = len(text)
        sys.stdout.write("\n")


def main() -> None:  # pragma: no cover
    """Interactive loop for the AiiDA agent."""
    load_dotenv(".env")  # read config; never write os.environ ourselves
    agent = get_agent()
    sys.stdout.write(
        f"AiiDA Agent ({os.getenv('AIIDA_AGENT_PROVIDER', 'ollama')}:"
        f"{os.getenv('AIIDA_AGENT_MODEL', 'qwen3.5:2b')}). Type 'quit' to exit.\n"
    )
    while True:
        try:
            question = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if question.lower() in ("quit", "exit", "q") or not question:
            break
        asyncio.run(ask(agent, question))


if __name__ == "__main__":  # pragma: no cover
    from aiida import load_profile

    load_profile()
    main()
