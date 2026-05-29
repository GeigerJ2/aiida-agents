"""AiiDA exploration agent using Pydantic AI."""

from __future__ import annotations
import asyncio
import os
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel

# Import our refactored MCP tool functions directly
from aiida_agents.mcp.tools.processes import get_process_status, list_processes
from aiida_agents.mcp.tools.nodes import query_nodes, get_node_inputs, get_node_outputs
from aiida_agents.mcp.tools.structures import search_structures


def load_env(env_path: str = ".env") -> None:  # pragma: no cover
    """Load environment variables from a .env file if it exists."""
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    # Don't overwrite variables already set in the shell
                    if key.strip() not in os.environ:
                        os.environ[key.strip()] = val.strip().strip('"').strip("'")


# Load local environment variables from .env
load_env()

# Automatically set OLLAMA_BASE_URL to point to Windows/WSL localhost if not set
if "OLLAMA_BASE_URL" not in os.environ:  # pragma: no cover
    os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434/v1"


def get_model() -> Model:
    """Get the configured AI model dynamically from environment variables.

    Ensuring that agent is fully model-agnostic and modular:
    1. By default, it runs your lightweight local 'qwen3.5:2b'.
    2. In production/servers, the AiiDA team can point it to cloud models or larger local
       models simply by setting environment variables in their shell.
    """
    # Allowed providers: 'ollama', 'openai', 'anthropic', 'gemini'
    model_provider = os.getenv("AIIDA_AGENT_PROVIDER", "ollama").lower()
    model_name = os.getenv("AIIDA_AGENT_MODEL", "qwen3.5:2b")

    if model_provider == "ollama":
        # Use Pydantic AI's native OpenAI-compatible Ollama provider
        return OpenAIChatModel(
            model_name=model_name,
            provider="ollama",
        )
    elif model_provider == "openai":  # pragma: no cover
        # Standard OpenAI cloud model (looks up OPENAI_API_KEY environment variable)
        return OpenAIChatModel(model_name=model_name)
    else:  # pragma: no cover
        # Fallback to Pydantic AI's dynamic inference (handles 'anthropic:claude-3-5-sonnet', etc.)
        from pydantic_ai.models import infer_model

        return infer_model(f"{model_provider}:{model_name}")


# Instantiate our modular model
model = get_model()

# Create the AiiDA Agent with our local tools!
agent = Agent(
    model,
    tools=[
        get_process_status,
        list_processes,
        query_nodes,
        get_node_inputs,
        get_node_outputs,
        search_structures,
    ],
    system_prompt=(
        "You are an expert agentic assistant for the AiiDA (Automated Interactive Infrastructure "
        "for Database Applications) materials science database. You help materials scientists "
        "explore calculations, structures, and process provenance records by querying the database graph.\n\n"
        "CRITICAL TOOL SELECTION RULES:\n"
        "1. PROCESS STATUS & DETAILS:\n"
        "   - To check the status, state, exit code, or exit message of a specific process PK, you MUST use 'get_process_status(pk=...)'.\n"
        "   - To list recent processes, use 'list_processes(limit=...)'.\n"
        "2. PROVENANCE INPUTS AND OUTPUTS:\n"
        "   - To find the inputs (incoming links) of any node, you MUST use 'get_node_inputs(pk=...)'. Do NOT use query_nodes or list_processes for this.\n"
        "   - To find the outputs (outgoing links) of any node, you MUST use 'get_node_outputs(pk=...)'. Do NOT use query_nodes or list_processes for this.\n"
        "3. CRYSTAL STRUCTURE SEARCHING:\n"
        "   - To find crystal structures (by elements, formulas, or names), always use 'search_structures(formula=...)'.\n"
        "4. GENERIC NODE SEARCH:\n"
        "   - Only use 'query_nodes' if the user specifically requests a generic search for nodes of a certain type (e.g. KpointsData, CalcJobNode) and does not specify a specific PK or process to inspect.\n\n"
        "MULTI-STEP REASONING FLOW (DIAGNOSTICS):\n"
        "- If a user asks to diagnose a failed calculation (e.g. 'Check status of calculation X. If it failed, what outputs did it produce?'):\n"
        "  1. First call 'get_process_status(pk=X)'.\n"
        "  2. Inspect the returned status and exit_status. If state is FINISHED and exit_status != 0, it failed.\n"
        "  3. If it failed, immediately call 'get_node_outputs(pk=X)' to identify what was produced. Do NOT call list_processes or query_nodes in between.\n\n"
        "OUTPUT FORMATTING RULES:\n"
        "- Always present data clearly in Markdown tables or lists.\n"
        "- Keep answers direct, concise, and professional.\n"
        "- NEVER output raw python wrapper strings like 'AgentRunResult' in your final text.\n"
        "- Ground your responses purely in the tool outputs. Do not guess PKs, UUIDs, or statuses."
    ),
)


async def ask(question: str) -> None:  # pragma: no cover
    """Run a user query through the agent and stream the response in real-time."""
    print("Agent is thinking and querying tools...\n")
    try:
        # Use run_stream to stream the response as it is being generated
        async with agent.run_stream(question) as result:
            print("🤖 Agent: ", end="", flush=True)
            printed_len = 0
            async for text in result.stream_text(debounce_by=None):
                new_text = text[printed_len:]
                print(new_text, end="", flush=True)
                printed_len = len(text)
            print("\n")
    except Exception as e:
        print(f"\n❌ Error running agent: {e}\n")


def main() -> None:  # pragma: no cover
    """Interactive loop to talk to the AiiDA Agent."""
    print("=" * 60)
    print("AiiDA Exploration Agent (Pydantic AI) - Ready!")
    print(
        f"Active Model: {os.getenv('AIIDA_AGENT_PROVIDER', 'ollama')}:{os.getenv('AIIDA_AGENT_MODEL', 'qwen3.5:2b')}"
    )
    print("Type your question or 'quit'/'exit' to exit.")
    print("=" * 60 + "\n")

    while True:
        try:
            question = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if question.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        if not question:
            continue

        asyncio.run(ask(question))


if __name__ == "__main__":  # pragma: no cover
    from aiida import load_profile

    # Load the default active AiiDA database profile inside the process
    load_profile()
    main()
