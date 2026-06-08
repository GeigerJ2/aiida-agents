# PR #4 review: `✨ added model-agnostic AiiDA exploration agent using Pydantic AI`

Branch `feat/pydantic-ai-agent` → `main`. Reviewed at `2b5f6f3`. No prior review comments on the PR.

## Answers to your three questions first

**1. Does #4 still contain old code from #3?** No, not in the tree. PR #3 (`refactor/mcp-layout-and-tests`) was **squash-merged** into `main` as commit `5b9ee8d` (single parent `2f1703a`, so the project squash-merges). `origin/main` is now a full ancestor of this branch, and `git diff origin/main HEAD -- src/aiida_agents/mcp tests/mcp` is **empty**. Every MCP source and test file in #4 is byte-identical to `main`. The merge `e50eabc` reconciled everything correctly; there are no stale `#3` copies in the working tree.

Where the "old code" smell *does* live is the **history**, not the tree. Because the branch first merged the refactor branch directly (`3e65998`) and *then* merged `origin/main` (which carried the squashed `#3`), the branch log lists ~30 commits including the original un-squashed refactor commits (`fdc11bb`, `b5a655b`, `6f7c5d1`, …) that are already represented by the single squash commit on `main`. The PR *diff* is clean regardless, because GitHub computes it against the merge-base (`origin/main`), which is fully contained in HEAD. See `t_history_duplication`.

**2. Should you merge or rebase?** There is nothing to merge *from* `main`. HEAD already contains all of `origin/main` (`git log HEAD..origin/main` is empty). For correctness you don't need to do anything. Since `#3` was squash-merged and `#4` will presumably be squash-merged too, the duplicated commits collapse into one clean commit on merge, so the messy log is cosmetic. If you want a readable PR history before merge, `git rebase --onto origin/main origin/main HEAD` (or an interactive rebase dropping the duplicated refactor commits) gives a clean diff of just the agent work. Optional, not required. See `t_history_duplication`.

**3. Other comments on what #4 adds:** the net diff is 9 files: `agent.py`, `prompts/`, `tests/test_eval_harness.py`, ADR-04/05, `pyproject.toml`, `uv.lock`, `.gitignore`. The biggest issue, that the eval harness tests nothing, is already posted on the PR; the items still to raise are below.

---

## Status (PR conversation as of 2026-06-08)

Seven comments posted, no pending/draft (all submitted). Those findings have been removed from this file, which now tracks only what's left to post. Posted and removed: the eval-harness tautology, the agent-construction comment (import-time side effects + `OLLAMA_BASE_URL` env mutation), the `_load_env`-to-`load_dotenv` swap, the `.gitignore` entries, the `pyproject.toml:27` lower-bound question, and the system-prompt-to-`.md` comment.

What's left, below: one must-fix (mf_coverage_comment_false, the `pyproject.toml:94-96` "validated by the eval harness" claim; worth posting next to pair with the eval-harness comment), plus the nice-to-haves (nh_default_model_tag as an error-UX point, nh_pydantic_ai_slim, nh_no_console_script, nh_ruff_select_missing, nh_no_print_repl) and the four tangential items.

Scope: #4 is the first agent infrastructure. The construction cleanup (factory, no import side effects, explicit `base_url`, no env mutation) is fair game for #4. The provider-matrix expansion (anthropic, openai-compatible) and the CLI/presentation refactor (no-print, `stream_answer`/`_render`, click/rich) are follow-up PRs, not blockers here; `review/snippets.md` keeps that design as forward reference.

---

## TL;DR

### Must-fix

- [ ] `pyproject.toml:94-96`: the coverage comment claims the agent/LLM IO boundaries "are validated by the eval harness, not by mock-to-hit-lines tests." They are not validated by anything (see above). Correct the comment or make the harness real; right now it documents a guarantee that does not exist (mf_coverage_comment_false)

### Nice-to-have

- [ ] `agent.py` dies with a ~50-line `ModelHTTPError` traceback when the Ollama model isn't pulled (or Ollama is down). Confirmed by dogfooding: `qwen3.5:2b` 404s from local Ollama until `ollama pull`'d. The default tag itself is real (verified on the Ollama library; my earlier "bogus tag" claim was wrong, so the tag is not the problem); this is an error-UX issue. Catch the connection-refused / 404 at the REPL boundary and surface "Is Ollama running, and is `<model>` pulled? `ollama pull <model>`" instead of the stack trace (nh_default_model_tag)
- [ ] `pyproject.toml:27`: `pydantic-ai>=1.44.0` pulls the entire provider matrix into `uv.lock` (anthropic, cohere, groq, mistralai, google-genai, openai, boto3/bedrock, huggingface-hub, logfire, opentelemetry, …). You support three providers (Ollama, OpenAI, Anthropic), so `pydantic-ai-slim[openai,anthropic]` gives exactly those and drops the rest (groq, mistral, cohere, google/vertex, bedrock, huggingface) plus the default telemetry, at a fraction of the footprint (nh_pydantic_ai_slim)
- [ ] No `[project.scripts]` entry for the agent; the only launch path is `python -m aiida_agents.agent`. Add a console script (e.g. `aiida-agents = "aiida_agents.agent:main"`) and document it (nh_no_console_script)
- [ ] `src/aiida_agents/agent.py` is a flat module at the package root, but the project is a multi-agent system (ADR-04: orchestrator + sub-agents), so a singular `agent.py` won't scale. Mirror `mcp/` with an `agents/` subpackage; the current agent is ADR-04's Analysis Agent, so `agents/analysis.py` names it right (and resolves the generic-naming point in the tangential ADR-04 item). Cheap in #4, churn if deferred past the settled `aiida_agents.agent` import path (nh_agents_subpackage)
- [ ] `pyproject.toml:99-110` has no `lint.select`, so ruff runs only its default rules (`E4`, `E7`, `E9`, `F`). The whole `lint.ignore` list (`TRY003`, `EM101`, ...) and the `dev/` `T201` ignore are dead config: those rules aren't selected, so ignoring them is a no-op. Verified with ruff 0.4.1: `ruff check src/aiida_agents/agent.py` passes, `--select T20` flags 4 prints. Add the `select` the ignore list implies (`["ALL"]` with the curated ignores, or minimally `+ T20`) so the intended ruleset actually runs (nh_ruff_select_missing)
- [ ] `agent.py:77-87` uses `print` for the REPL banner and token streaming (flagged in #3). Route user output through the CLI layer (`click.echo`, AiiDA-standard) or `sys.stdout`, keep diagnostics on `logging`, and ideally keep `ask` from presenting at all (stream/yield text, let the entry point display it). Enforced automatically once `select` carries `T20` (nh_no_print_repl)

### Tangential / not on TL;DR

- [ ] History carries duplicated un-squashed `#3` commits; tree is clean; rebase optional (full discussion above) (t_history_duplication)
- [ ] ADR-04 hides its `Seed` marker inside an HTML comment (`adr/04:3`) while ADR-05 shows it as a blockquote (`adr/05:3`), pick one convention (t_adr04_seed_comment_hidden)
- [ ] The implemented `agent` is a single all-tools agent, i.e. the "Analysis Agent" of ADR-04, not the routed Orchestrator the ADR describes. Fine for milestone 1, but the generic name/docstring don't say so (t_adr04_monolithic_vs_impl)
- [ ] `test_eval_harness.py:30` sets `result.data`; pydantic-ai renamed `AgentRunResult.data` to `.output` (`.data` is deprecated). Harmless (never asserted) but signals coding against an older API than the `>=1.44.0` pin (t_result_data_deprecated)

---

## Inline comments

### Coverage comment documents a guarantee that doesn't exist (mf_coverage_comment_false)

`pyproject.toml:94-96`:

```toml
# Floor only. The deterministic, safety-critical core (validator, HITL, query
# construction) targets ~100%; LLM/agent IO boundaries use `# pragma: no cover`
# and are validated by the eval harness, not by mock-to-hit-lines tests.
```

The eval harness validates none of the agent IO boundaries (it mocks `agent.run` itself, raised in the posted comment on `tests/test_eval_harness.py`), and `agent.py`'s `ask`, `main`, `_load_env`, and the non-ollama `get_model` branches are all `# pragma: no cover`. So the agent's real behaviour has ~zero test coverage while this comment asserts the opposite. Either make the harness real or rewrite the comment to reflect that agent behaviour is currently validated only by manual runs.

### Raw traceback when the model isn't pulled / Ollama is down (nh_default_model_tag)

`agent.py:46-47` sets the default `model_name = "qwen3.5:2b"`. Two corrections to my earlier take, the second validated by dogfooding:

- The tag is real. `qwen3.5:2b` is a current Ollama library tag (2.27B, Q8_0, ~2.7 GB, native tool calling, Qwen 3.5 small series, post-cutoff); verified against the Ollama library tags page. My earlier "not a real tag / 404" claim is withdrawn; the default is a fine, tool-calling-capable choice.
- The run-time UX is genuinely rough, and now demonstrated. With the model not pulled locally, the agent dies with a ~50-line `pydantic_ai.exceptions.ModelHTTPError: status_code: 404 ... model 'qwen3.5:2b' not found` stack trace. A tired researcher reads that as "the agent is broken," not "I need to pull the model." Ollama's OpenAI-compatible endpoint returns the same 404 whether the model is unpulled or the tag is wrong, so the message needs interpreting.

Fix: at the REPL boundary (`main` / the presentation layer, not the library functions), catch `ModelHTTPError` and connection-refused and emit a one-line hint, e.g. "Can't reach model `<model>` on Ollama. Is `ollama serve` running, and have you run `ollama pull <model>`?", keeping the full traceback behind a debug/verbose flag. Small, but it's the difference between a usable first run and a wall of stack frames.

### `pydantic-ai` pulls every provider SDK, prefer `pydantic-ai-slim[openai,anthropic]` (nh_pydantic_ai_slim)

`pyproject.toml:27`:

```toml
"pydantic-ai>=1.44.0",
```

The resulting `uv.lock` adds `anthropic`, `cohere`, `groq`, `mistralai`, `google-genai`, `google-auth`, `openai`, `boto3`/`botocore` (Bedrock), `huggingface-hub`/`hf-xet`, `logfire`/`logfire-api`, and a stack of `opentelemetry-*`. The meta-package `pydantic-ai` is "everything." You support three providers: Ollama (via `OpenAIChatModel` + `OllamaProvider`, which needs the `openai` extra), OpenAI (`openai`), and Anthropic (`anthropic`). `pydantic-ai-slim[openai,anthropic]` gives exactly those and drops the SDKs you don't use (groq, mistral, cohere, google/vertex, bedrock, huggingface) plus `logfire`/opentelemetry telemetry. Add another extra explicitly if you add a provider. Worth weighing against the `adding-dependencies` checklist.

On your PR question about the `>=1.44.0` lower bound: I don't see a reason for that specific floor (it's a recent release). A lower bound should be the earliest version that has the APIs you call (`OpenAIChatModel`, `OllamaProvider`, `Agent.override`), not whatever was latest when it was added; an arbitrarily high floor blocks resolution for downstream users with no payoff. Either justify `1.44.0` against a concrete API you need, or relax it to the real minimum (and if you move to `pydantic-ai-slim`, the bound moves with it). Scope-wise this is a `#4` item since the dependency is in this PR.

### No console-script entry point for the agent (nh_no_console_script)

`pyproject.toml` has no `[project.scripts]`, so the agent is only reachable via `python -m aiida_agents.agent` (which works only because of the `if __name__ == "__main__"` guard in `agent.py:101-105`). For a tool aimed at non-CS researchers, an `aiida-agents`/`aiida-agent` console entry (`aiida-agents = "aiida_agents.agent:main"`) is the discoverable affordance, and it gives a natural home for the `load_profile()` call that currently lives in the `__main__` block. Document the launch command in the README/CONTRIBUTING alongside the MCP-server instructions #3 added.

### `lint.select` is missing, so the ruleset is inert (nh_ruff_select_missing)

`pyproject.toml:99-110`:

```toml
[tool.ruff]
lint.ignore = ["TRY003", "EM101", "EM102", "PLR2004", "FBT002", "TID252"]
[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["INP001", "S101"]
"dev/**/*.py" = ["INP001", "T201"]
```

There's no `lint.select`, so ruff uses its default rule set (`E4`, `E7`, `E9`, `F`). Every rule in the `ignore` list (`TRY003`, `EM101`, `EM102`, `PLR2004`, `FBT002`, `TID252`) and the `dev/` `T201` ignore belongs to groups that aren't selected, so those lines do nothing today: you can't ignore a rule that isn't on. The ignore list only makes sense if a broad `select` (almost certainly `["ALL"]`) was intended and got dropped. Verified with ruff 0.4.1: `ruff check src/aiida_agents/agent.py` reports "All checks passed!", while `ruff check --select T20 src/...` flags four `T201 print found`. Add the intended `select` (`["ALL"]` with the curated ignores, or at minimum extend with `T20`) so the rules the ignore list presupposes actually run. This is also what makes the no-print rule enforceable (see the print finding below). It is why CI is green with the prints in place: CI runs ruff through the `ruff-check` pre-commit hook (`hatch run pre-commit:run --all-files`, `.github/workflows/ci.yaml`), which uses this same config, so `T201` is never checked. Green CI here is the symptom, not a contradiction.

### `print` in the REPL (nh_no_print_repl)

`agent.py:77-87` (`ask` and `main`):

```python
print("Agent: ", end="", flush=True)
...
print(text[printed_len:], end="", flush=True)
...
print()
...
print(f"AiiDA Agent ...")
```

Print was flagged in #3 and it's back here for the REPL banner and token streaming. For diagnostics the convention is `logging`; for genuine user-facing CLI output use the CLI layer's printer (`click.echo`, which the AiiDA ecosystem uses, or `sys.stdout.write` for raw streaming) rather than the `print` builtin. Cleanest is to keep `ask` from doing presentation at all (stream/yield text and let the `__main__` / CLI entry display it), so the library code has no stdout writes. Either way, once `select` carries `T20` (the ruff-config finding above) this is caught automatically, and the existing `dev/` `T201` ignore already exempts dev scripts.

Relatedly, the REPL output is noisy: `ask` echoes the user's own question back as an INFO log (`logger.info("Running agent query: %s", ...)`), and third-party INFO chatter shows too (the `httpx` "HTTP Request" lines). Demote the echo to `debug`, and default the interactive REPL's logging to WARNING with a verbose opt-in, so the user sees the answer rather than their own input plus HTTP logs.

### `agent.py` should be an `agents/` subpackage (nh_agents_subpackage)

`src/aiida_agents/agent.py` sits as a flat module at the package root, beside the `mcp/` and `prompts/` subpackages. But the package is named `aiida_agents` (plural) and ADR-04 commits to a multi-agent architecture: an Orchestrator plus Analysis / Diagnostic / Config / Workflow sub-agents. A flat `agent.py` has no room for that; it either grows into a god-module or sprouts sibling `orchestrator.py` / `diagnostic.py` files at the package root.

Mirror `mcp/` and make `agents/` a subpackage. The current agent is exactly ADR-04's Analysis Agent (read-only tools):

```
src/aiida_agents/agents/
    __init__.py          # re-export the public API (get_agent, ...)
    _models.py           # get_model(): shared model selection (ADR-04: agents share one model)
    analysis/
        __init__.py      # the Analysis agent: get_agent() + its tool selection
        prompt.md        # its one system prompt (loaded via importlib.resources)
    # orchestrator/, diagnostic/, ... added later, each its own sibling subpackage
```

Each agent is a subpackage (package-by-feature) with its prompt co-located, so adding an agent is adding a directory. Two things stay out of the per-agent dirs because they're not per-agent: `get_model()` is split into `agents/_models.py` now (ADR-04 has every agent share one model, so it's shared infrastructure; giving it its home now avoids a later move), and the interactive REPL (`main`/`ask`) is an app entry, not Analysis-specific, so it belongs at app level (e.g. `aiida_agents/cli.py`), driving whichever agent is active.

On prompts the word is overloaded. MCP does define a `prompts` primitive (tools / resources / prompts), but those are templates the *server* advertises to clients, and our server exposes none today, only tools. The current `SYSTEM_PROMPT` is the *agent's* system prompt (`Agent(system_prompt=...)`), never exposed over MCP, so it's an agent concern and lives with its agent (`agents/analysis/prompt.md`) as a single file, not a `prompts/` subdir (one prompt does not need a directory; promote to one only if an agent grows several prompt files). If we later advertise protocol-level prompts/resources from the server, those would live in `mcp/prompts/` and `mcp/resources/`, mirroring `mcp/tools/`, a different layer from the agent's system prompt. Naming the subpackage `analysis` also resolves the generic-naming point parked in the tangential ADR-04 item, and the console-script target becomes `aiida_agents.cli:main` (or the active agent's entry).

Worth doing in #4: the move is cheap now (one file, update the test imports and the console-script path), but once `from aiida_agents.agent import ...` is an established import path, changing it is needless churn.

### History duplication / merge-vs-rebase (t_history_duplication)

Already answered up top. Summary: tree is clean (`#4` MCP files == `main`), nothing to merge from `main`, the duplicated un-squashed `#3` commits are cosmetic and vanish under a squash-merge. Optional cleanup: `git rebase --onto origin/main origin/main HEAD`.

### ADR-04 hides its seed marker; ADR-05 shows it (t_adr04_seed_comment_hidden)

`docs/adr/04-multi-agent-architecture.md:3`:

```markdown
<!-- > Seed — direction confirmed 2026-05-25; agent boundaries and inter-agent protocol still to be specified during implementation. -->
```

vs `docs/adr/05-rag-over-aiida-docs.md:3`:

```markdown
> Seed — direction confirmed 2026-05-25; chunking strategy, collection schema, and retriever integration still to be specified during implementation.
```

Same status, two renderings (hidden HTML comment vs visible blockquote). Pick one so readers see a consistent "this ADR is a seed, not final" banner across the set. Check `docs/adr/README.md` for the intended convention.

### Implemented agent is monolithic; ADR-04 describes a routed orchestrator (t_adr04_monolithic_vs_impl)

`agent.py:59-70` builds one `Agent` holding all six read-only tools with one `SYSTEM_PROMPT`. That matches ADR-04's "Analysis Agent" (read-only MCP tools, the stated first-milestone deliverable), not the Orchestrator + sub-agent routing the ADR's Decision section specifies, and it's the very "single monolithic agent with all tools" the ADR lists under rejected alternatives. That's a reasonable milestone-1 starting point, but the module/object is named generically (`agent`, "AiiDA exploration agent") with no note that it's the Analysis Agent precursor and that routing is deferred. A one-line docstring pointer to ADR-04 milestone scope would keep code and ADR honest.

### Mock uses deprecated `result.data` (t_result_data_deprecated)

`test_eval_harness.py:30`:

```python
result.data = response_text
```

pydantic-ai renamed `AgentRunResult.data` to `.output`; `.data` is a deprecated alias. It's never asserted so nothing breaks, but it's a tell that the harness was written against an older API than the `pydantic-ai>=1.44.0` pin. If the harness is rewritten to use a real `TestModel`/`FunctionModel`, this goes away on its own.

---

## Verification artifacts

- `review/prove_tautology.py`: standalone reproduction showing the eval-harness assertion passes against a zero-tool, no-model stub agent. Run: `python3 review/prove_tautology.py`.
- Git facts verified: `5b9ee8d` (main) has a single parent → squash-merge of #3; `git log HEAD..origin/main` empty → main fully contained in HEAD; `git diff origin/main HEAD -- src/aiida_agents/mcp tests/mcp` empty → no stale #3 code in the tree.
- Did **not** run the real pytest suite: the worktree `.venv` is unprovisioned (no `aiida`, `pydantic_ai`) and a full `uv sync` pulls `aiida-core`/`aiida-restapi` from git, not warranted for the claims in this review, all of which are verified by reading + the standalone repro.
