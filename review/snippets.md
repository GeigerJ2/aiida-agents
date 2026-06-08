# Replacing the hand-rolled `_load_env` in `src/aiida_agents/agent.py`

Original (the thing being replaced):

```python
def _load_env(env_path: str = ".env") -> None:  # pragma: no cover
    """Load environment variables from a .env file without overwriting existing ones."""
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                if key.strip() not in os.environ:
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")
```

Issues: reinvents python-dotenv; uses `os.path` (CLAUDE.md prefers `pathlib`); `.strip('"').strip("'")` corrupts values, e.g. `KEY='a"b'` loses the legitimate inner `"`, and unquoted values get stray quote chars stripped too.

## Option A (recommended): use python-dotenv, delete the function

`load_dotenv(override=False)` *is* exactly "load `.env` without overwriting existing env vars" (`override=False` is the default). It also parses quotes, `export ` prefixes, and multi-line values correctly, so the whole helper goes away.

Add the dependency in `pyproject.toml`:

```toml
dependencies = [
    ...
    "python-dotenv>=1.0",
]
```

Then the top of `agent.py` becomes (the `_load_env` function and its `_load_env()` call are both removed):

```python
from dotenv import load_dotenv

# Reads a .env from the current working directory; never clobbers values
# already set in the environment. Silent no-op if the file is missing.
load_dotenv(".env")
```

Pass the path explicitly. Bare `load_dotenv()` (no args) calls `find_dotenv()`, which walks *upward* from the calling module's directory looking for a `.env`. The current `_load_env` only ever checks `.env` in the CWD, so `load_dotenv(".env")` preserves that behaviour exactly while `load_dotenv()` would silently change it.

## Option B: no new dependency, just `pathlib` + a correct parse

If you'd rather not add a dependency, at least drop `os.path` for `pathlib`, use a guard clause to cut nesting, use `str.partition` (no risk of a bad unpack), and strip only a *matching* surrounding quote pair instead of blindly stripping all quote characters:

```python
def _load_env(env_path: str | Path = ".env") -> None:  # pragma: no cover
    """Load environment variables from a ``.env`` file without overwriting existing ones.

    :param env_path: Path to the ``.env`` file; missing files are ignored.
    """
    path = Path(env_path)
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        if key in os.environ:
            continue

        value = value.strip()
        # Strip one matching pair of surrounding quotes only, so inner quotes
        # and apostrophes survive (KEY="it's fine" -> it's fine).
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ[key] = value
```

This needs `from pathlib import Path` (and the existing `import os`) at the top of the module.

---

# Removing the import-time side effects and the env mutation

To remove import-time side effects, **delete** the import-time block (`_load_env`, its call, and the `OLLAMA_BASE_URL` assignment at `agent.py:21-37`), plus the module-level `agent = Agent(...)` (`agent.py:59-70`).

**Replace** with a factory that builds fresh (mirroring `get_mcp()`), and construct the Ollama provider with an explicit `base_url` instead of mutating the environment:

```python
from dotenv import load_dotenv                       # new
from pydantic_ai.providers.ollama import OllamaProvider  # new
from pydantic_ai.providers.openai import OpenAIProvider  # new (openai-compatible mode)
# os, Agent, Model, OpenAIChatModel, _TOOLS, SYSTEM_PROMPT already in agent.py


def get_model() -> Model:
    """Return the configured model from AIIDA_AGENT_PROVIDER / AIIDA_AGENT_MODEL.

    Providers:
      * ``ollama`` (default): any local model; ``OLLAMA_BASE_URL`` overrides the
        ``http://localhost:11434/v1`` default.
      * ``openai`` / ``anthropic``: hosted models; read their own API-key env vars.
      * ``openai-compatible``: any OpenAI-compatible endpoint (DeepSeek, Together,
        Fireworks, Perplexity, Azure, OpenRouter, vLLM, ...). Requires
        ``AIIDA_AGENT_BASE_URL``; ``AIIDA_AGENT_API_KEY`` is optional (a placeholder
        is sent for keyless local servers).
    """
    provider = os.getenv("AIIDA_AGENT_PROVIDER", "ollama").lower()
    model_name = os.getenv("AIIDA_AGENT_MODEL", "qwen3.5:2b")

    if provider == "ollama":
        # OllamaProvider has no default and raises UserError when OLLAMA_BASE_URL
        # is unset, so resolve base_url here: localhost by default, overridable
        # via the env var. No os.environ write.
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        return OpenAIChatModel(model_name, provider=OllamaProvider(base_url=base_url))
    if provider == "openai":
        return OpenAIChatModel(model_name)  # OpenAIProvider reads OPENAI_API_KEY
    if provider == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel  # lazy: optional extra

        return AnthropicModel(model_name)  # AnthropicProvider reads ANTHROPIC_API_KEY
    if provider == "openai-compatible":
        # The whole OpenAI-compatible universe via the openai extra (no new SDK):
        # the Ollama pattern with a user-supplied base_url.
        base_url = os.getenv("AIIDA_AGENT_BASE_URL")
        if not base_url:
            msg = (
                "AIIDA_AGENT_PROVIDER='openai-compatible' requires AIIDA_AGENT_BASE_URL "
                "(e.g. https://api.deepseek.com/v1)."
            )
            raise ValueError(msg)
        # Placeholder key so keyless local servers (vLLM, LM Studio) work.
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
```

(`_TOOLS` is the existing `tools=[...]` list, lifted to a module constant.)

The original's `infer_model(f"{provider}:{model_name}")` catch-all is replaced by an explicit set: three named providers (`ollama`, `openai`, `anthropic`) plus one generic `openai-compatible` branch. That branch reaches the entire OpenAI-compatible universe (DeepSeek, Together, Fireworks, Perplexity, Azure, OpenRouter, vLLM, LM Studio, ...) through `OpenAIProvider(base_url=...)`, needs only the `openai` extra you already have (no new SDK), and is just the Ollama pattern with a user-supplied base_url. The native non-compatible providers (Gemini, Grok, Bedrock, Groq, Mistral, Cohere, Hugging Face) stay explicit-add-with-an-extra, which is honest while you're slimming deps. The old catch-all was why two branches carried `# pragma: no cover`: an open-ended "any provider" path is hard to cover and silently accepts typos. Every branch here is reachable and dummy-key testable, so `get_model` carries no pragma and the error names the supported providers. `AnthropicModel` is imported lazily so the module still imports without the `anthropic` extra.

There's no `_configure_env` helper any more. The only env *read* that needed a home was `OLLAMA_BASE_URL`, and that now lives at its point of use in `get_model`. The one remaining setup step is `load_dotenv`, which goes into `main()`. Presentation also stays out of the agent functions: a pure `stream_answer` generator yields text, and the entry point owns the single stdout boundary, so the eventual CLI library (click, rich, or another) changes only that boundary:

```python
import sys
from collections.abc import AsyncIterator
# asyncio already imported in agent.py


async def stream_answer(agent: Agent, question: str) -> AsyncIterator[str]:
    """Yield the agent's answer as incremental text chunks.

    Pure: no stdout, no presentation. Choosing click / rich later touches only
    the boundary below, never this, get_agent, or get_model.
    """
    logger.debug("Running agent query: %s", question)  # debug: don't echo input in the REPL
    async with agent.run_stream(question) as result:
        emitted = 0
        async for text in result.stream_text(debounce_by=None):
            yield text[emitted:]
            emitted = len(text)


async def _render(agent: Agent, question: str) -> None:  # pragma: no cover
    """Presentation boundary: the only place that writes to stdout."""
    sys.stdout.write("Agent: ")
    async for chunk in stream_answer(agent, question):
        sys.stdout.write(chunk)
        sys.stdout.flush()
    sys.stdout.write("\n")


def main() -> None:  # pragma: no cover
    """Interactive REPL. Replace _render's writes with click/rich when chosen."""
    load_dotenv(".env")
    agent = get_agent()
    sys.stdout.write("AiiDA Agent ready. Type 'quit' to exit.\n")
    while True:
        question = input("You: ").strip()
        if question.lower() in {"quit", "exit", "q"} or not question:
            break
        asyncio.run(_render(agent, question))
```

`stream_answer` carries no `# pragma: no cover`: a `TestModel`-overridden agent drives it in a test. `_render` and `main` keep the pragma since they are genuine interactive stdout/stdin glue. When the CLI library is chosen, only `_render` changes: `click.echo(chunk, nl=False)` per chunk (then a final `click.echo()`), or a `rich` `Console` / `Live` for richer rendering.

## Why no env mutation

The original set `OLLAMA_BASE_URL` via `os.environ.setdefault(...)` so the `provider="ollama"` string shortcut (which builds `OllamaProvider()` with no args) wouldn't raise. That is load-bearing, not redundant: pydantic-ai's `OllamaProvider` has no built-in default and raises `UserError` when the var is unset (verified against the installed version). But writing to the process-global environment to hand a value to a library is the wrong mechanism: it has process-wide blast radius (any later reader, including an `ollama` subprocess, sees the value you injected) and it only works by leaning on the string-inference path. Constructing `OllamaProvider(base_url=...)` reads the env var (`os.getenv`, config in) without ever writing it, and drops the string shortcut. Same out-of-box behaviour, no global side effect.

## Why this shape (factory, not memoised)

`get_mcp()` is **not** memoised. It builds a fresh `FastMCP` each call, and the one instance lives in the module-level `mcp = get_mcp()`. So #3's import isn't side-effect-free either; what it deferred was the genuinely-unsafe part (the profile load) into `_lifespan`. The principle is "defer the unsafe work," not "construct nothing at import."

For the agent the unsafe-at-import bits are reading `.env` and building a model. Those leave import scope: `load_dotenv` and `get_agent()` are called from `main()`, not at module load.

Unlike `mcp`, the agent has **no external discovery need** for a module-level object (nothing does `fastmcp run agent.py`), so there's no reason to keep a module global at all. Build it once in `main()` and pass it down. That's why I'd drop both the module-level `agent` *and* a `@lru_cache`: threading the instance is less hidden state than either, and tests just call `get_agent()` to get their own instance.

## What is called where

- **`import aiida_agents.agent`**: runs only the `def`s and `_TOOLS`. No `.env` read, no `os.environ` mutation, no model or `Agent` built. Test collection no longer depends on a constructible model.
- **`get_model()`**: reads the provider/model env vars and builds the `Model`, resolving the Ollama `base_url` explicitly. No env write.
- **`get_agent()`**: builds a fresh `Agent` from `get_model()` and the tools. Pure construction.
- **`main()`**: `load_dotenv(".env")`, then `get_agent()` once, then the input loop dispatches `ask(agent, q)`.
- **`python -m aiida_agents.agent`**: `load_profile()` (tools need a profile when invoked), then `main()`.

## Tests

With the catch-all gone, every branch of `get_model` is reachable, so it carries no `# pragma: no cover`. Pin each one: the Ollama `base_url` fallback (localhost when unset, the env var when set), the openai branch, and the unknown-provider error.

```python
import pytest

from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider

from aiida_agents.agent import get_model


def test_get_model_defaults_to_localhost_ollama(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("AIIDA_AGENT_PROVIDER", "ollama")
    model = get_model()
    assert isinstance(model.provider, OllamaProvider)
    assert model.provider.base_url == "http://localhost:11434/v1"


def test_get_model_respects_ollama_base_url(monkeypatch):
    monkeypatch.setenv("AIIDA_AGENT_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://remote:11434/v1")
    assert get_model().provider.base_url == "http://remote:11434/v1"


def test_get_model_openai(monkeypatch):
    monkeypatch.setenv("AIIDA_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")  # provider needs a non-empty key
    assert isinstance(get_model(), OpenAIChatModel)


def test_get_model_anthropic(monkeypatch):
    monkeypatch.setenv("AIIDA_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert isinstance(get_model(), AnthropicModel)


def test_get_model_openai_compatible(monkeypatch):
    monkeypatch.setenv("AIIDA_AGENT_PROVIDER", "openai-compatible")
    monkeypatch.setenv("AIIDA_AGENT_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("AIIDA_AGENT_API_KEY", "test-key")
    model = get_model()
    assert isinstance(model, OpenAIChatModel)
    assert str(model.provider.base_url).rstrip("/") == "https://api.deepseek.com/v1"


def test_get_model_openai_compatible_requires_base_url(monkeypatch):
    monkeypatch.setenv("AIIDA_AGENT_PROVIDER", "openai-compatible")
    monkeypatch.delenv("AIIDA_AGENT_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="AIIDA_AGENT_BASE_URL"):
        get_model()


def test_get_model_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("AIIDA_AGENT_PROVIDER", "no-such-provider")
    with pytest.raises(ValueError, match="Unsupported"):
        get_model()
```

(Confirm the public accessors against the installed pydantic-ai: `model.provider` and `provider.base_url` are the expected names, but check that `base_url` keeps the trailing path you passed.)

## Test call-site change for the harness

`tests/test_eval_harness.py` does `from aiida_agents.agent import agent`; there's no module-level `agent` now, so it becomes `from aiida_agents.agent import get_agent`. That also unlocks the real harness the `mf_eval_harness_tautology` item wants: each test builds its own agent and overrides the model instead of mocking `agent.run`:

```python
from pydantic_ai.models.test import TestModel

from aiida_agents.agent import get_agent


async def test_tools_are_wired_and_runnable(add_calc):
    agent = get_agent()
    # Drive the real tools against the real fixtures with a fake model.
    with agent.override(model=TestModel()):
        result = await agent.run("List the last 5 processes")
    # ... assert on result.output / the tool calls actually made ...
```
