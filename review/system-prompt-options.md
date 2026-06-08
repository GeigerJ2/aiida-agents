# Better ways to hold the system prompt

The current implicit-concatenation form is the painful one: every line needs
quotes, you hand-place `\n`, and a forgotten trailing space at a line break
silently joins two words. Two cleaner options.

## Option A: triple-quoted string (one-line change, kills the pain)

Just real newlines, no quotes per line, no `\n`. The `"""\` swallows the leading
newline so the text starts clean; left-aligned at column 0 because it's a
module-level constant.

```python
SYSTEM_PROMPT = """\
You are an expert agentic assistant for the AiiDA (Automated Interactive Infrastructure for Database Applications) materials science database. You help materials scientists explore calculations, structures, and process provenance records by querying the database graph.

CRITICAL TOOL SELECTION RULES:
1. PROCESS STATUS & DETAILS:
   - To check the status, state, exit code, or exit message of a specific process PK, use 'get_process_status(pk=...)'.
   - To list recent processes, use 'list_processes(limit=...)'.
2. PROVENANCE INPUTS AND OUTPUTS:
   - To find the inputs (incoming links) of any node, use 'get_node_inputs(pk=...)'.
   - To find the outputs (outgoing links) of any node, use 'get_node_outputs(pk=...)'.
3. CRYSTAL STRUCTURE SEARCHING:
   - To find crystal structures by elements or formula, use 'search_structures(formula=...)'.
4. GENERIC NODE SEARCH:
   - Use 'query_nodes' only for generic node-type searches where no specific PK is given.

MULTI-STEP DIAGNOSTICS:
- For failed calculation diagnostics: call 'get_process_status' first, then 'get_node_outputs' if the exit_status is non-zero.

OUTPUT RULES:
- Present data in Markdown tables or lists.
- Ground responses in tool output only; do not guess PKs or statuses.
"""
```

(If you'd rather keep the text indented under the assignment to match code
nesting, wrap it: `SYSTEM_PROMPT = textwrap.dedent("""...""").strip()`.)

Note: I replaced the prompt's em-dash ("tool output only — do not guess") with a
semicolon. Cosmetic, your call, but worth keeping the prompt ASCII-clean.

## Option B: keep the prompt in its own `.md` file (best for heavy iteration)

Since you're tweaking the prompt a lot, the nicest editing experience is to take
it out of Python entirely: a plain Markdown file with real highlighting and zero
escaping. The package already has a `prompts/` subpackage, so it drops right in.

`src/aiida_agents/prompts/system_prompt.md` (pure text, edit freely):

```markdown
You are an expert agentic assistant for the AiiDA ... by querying the database graph.

CRITICAL TOOL SELECTION RULES:
1. PROCESS STATUS & DETAILS:
   - To check the status ... use 'get_process_status(pk=...)'.
... (the same content as above) ...

OUTPUT RULES:
- Present data in Markdown tables or lists.
- Ground responses in tool output only; do not guess PKs or statuses.
```

`src/aiida_agents/prompts/__init__.py` (loads it; replaces `system_prompt.py`):

```python
"""Prompt templates for the AiiDA agents."""

from __future__ import annotations

from importlib.resources import files

SYSTEM_PROMPT = (
    files(__package__).joinpath("system_prompt.md").read_text(encoding="utf-8").strip()
)

__all__ = ["SYSTEM_PROMPT"]
```

Then delete `system_prompt.py`. `importlib.resources.files` (3.9+, you're 3.10+)
works in editable installs and wheels alike.

Packaging: hatchling ships everything under the package directory by default, so
`prompts/system_prompt.md` is included in the wheel. Verify once with
`python -c "from aiida_agents.prompts import SYSTEM_PROMPT; print(len(SYSTEM_PROMPT))"`
after a build, or add it explicitly under `[tool.hatch.build.targets.wheel]` if a
build ever drops it.

## Which to use

- Editing it occasionally: Option A. One-line change, no packaging to think about.
- Iterating heavily / want Markdown editing and diffs that read as prose: Option B.
  It also keeps `agent.py` and the prompt cleanly separated.
