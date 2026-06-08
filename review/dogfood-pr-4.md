# Dogfooding PR #4 locally (asking the agent something)

This works against the PR as-is (no refactor needed). Three things to set up: the
environment, an AiiDA profile with some data, and an LLM backend. Then run the
REPL.

## 1. Provision the environment

```bash
cd <repo>
uv sync           # installs aiida-core, aiida-restapi, pydantic-ai, fastmcp, ...
```

## 2. An AiiDA profile with data

The agent's `__main__` calls `load_profile()`, so you need a **default** profile,
ideally one with nodes to query.

Realistic path (recommended): point at a profile you already have.

```bash
verdi profile list
verdi profile setdefault <profile-with-data>
```

Throwaway path: a service-free sqlite profile, then seed one node so queries
return something.

```bash
verdi presto                       # creates + defaults a sqlite profile, no broker
verdi shell                        # then paste:
#   from aiida import orm
#   s = orm.StructureData(cell=[[3,0,0],[0,3,0],[0,0,3]])
#   s.append_atom(position=(0, 0, 0), symbols="Si")
#   print("stored StructureData pk", s.store().pk)
```

(For *process* questions you need a process node, which means running a calc; the
test fixtures in `tests/conftest.py` show a daemon-free `run_get_node` of
`ArithmeticAddCalculation` if you want to seed one. Otherwise use a populated
profile.)

## 3. An LLM backend

The agent reads `AIIDA_AGENT_PROVIDER` / `AIIDA_AGENT_MODEL` at import, so set them
before launching if you want non-defaults. The default is `ollama` + `qwen3.5:2b`,
which is a real, tool-calling Ollama tag (Qwen 3.5 small series, ~2.7 GB); you just
need to `ollama pull` it once before first use.

Ollama (local, the default provider):

```bash
ollama serve &                     # if not already running
ollama pull qwen3.5:2b             # the agent's default; tool-calling capable (~2.7 GB)
# OLLAMA_BASE_URL is defaulted to http://localhost:11434/v1 by the code
# Override the model if you like: export AIIDA_AGENT_MODEL=qwen3.5:4b
```

OpenAI (cloud; far better tool-calling for a real dogfood):

```bash
export AIIDA_AGENT_PROVIDER=openai
export OPENAI_API_KEY=sk-...
export AIIDA_AGENT_MODEL=gpt-4o-mini
```

A `.env` file in the repo root with the same `KEY=value` lines also works (the
current `_load_env` reads it at import).

## 4. Run it

```bash
uv run python -m aiida_agents.agent
```

At the `You:` prompt, try:

- `List the last 5 processes in the database`
- `What is the status of process <pk>?`
- `What are the inputs of node <pk>?`
- `Find crystal structures containing Si`

Type `quit` to exit.

## What you'll likely notice (and it lines up with the review)

- First run needs the model pulled: `ollama pull qwen3.5:2b`. The default tag is
  real (I checked the Ollama library), but Ollama won't fetch it until you pull it.
- Tool-selection quality tracks the model. A 2-3B local model often picks the
  wrong tool or invents a pk; a capable model (`gpt-4o-mini`, or a larger local
  one) actually drives the right tools. This is exactly why tool selection is an
  evaluation, not a unit test: it depends on the model, not on our code.
- Output streams via `print` today (`nh_no_print_repl`); it works, it's just the
  thing to route through a CLI layer later.
- An empty profile yields "no processes / no structures"; seed data or use a
  populated profile.
