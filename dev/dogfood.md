# dogfood.py: headless agent eval driver

A headless driver over the real agent stack (`_build_agent` / `ask` / `plan`, the
same pieces the REPL runs). It drives scripted or agent-in-the-loop conversations
against a profile, emits a structured transcript (markdown + JSONL) and a
resumable session, and records tool traces, grounding-check hits, and (in write
mode) submission outcomes. Use it to dogfood the agents: drive turns, read back
exactly what happened, and file what breaks.

This doc is written to be fed to another agent to run the eval loop.

## Setup

- **venv**: a synced aiida-agents env; run tools as `.venv/bin/python`. Provider
  and model come from `.env` / `AIIDA_AGENTS_*` (currently `openrouter` /
  `openrouter/free`, which is slow and intermittently returns empty responses).
- **profile**: always run against a **sandbox copy**, never a real profile.
  Create one: `aiida-agents sandbox init --profile <real-profile>` (registers
  `agents-sandbox`). Confirm isolation: `aiida-agents sandbox check`. Remove it
  when done: `aiida-agents sandbox teardown --yes`.
- **QE scenarios**: `quantumespresso.pw.relax` needs `aiida-quantumespresso`
  *and* `pymatgen` importable in the venv, or the entry point fails to load.

## Running

One turn, resumable (re-run with the same `--session` to continue; history
persists per specialist):

```
.venv/bin/python dev/dogfood.py turn \
  --profile agents-sandbox --agent auto \
  --session /tmp/df.json --transcript /tmp/df.md \
  --message "How many nodes are in this profile?"
```

`--agent` is one of `auto | analysis | execution | codegen`; `auto` exercises the
planner (where routing bugs live). A scenario runs several turns in one process:

```
.venv/bin/python dev/dogfood.py scenario \
  --profile agents-sandbox --agent auto --transcript /tmp/df.md \
  --turn "What structures are in this profile?" \
  --turn "Relax the first one with a PwRelaxWorkChain."
```

or `--file scenario.json` (a JSON list of strings) / `--file scenario.txt`
(turns separated by a line containing only `---`).

**Write mode** (real submits, sandbox only): add `--yes-in-sandbox` to actually
run proposed writes. It refuses at startup unless the profile shares storage with
no other (the same check `sandbox check` runs), so writes can only ever hit the
disposable copy. Without it, a proposed write is recorded and stopped.

## Reading results

- **stderr** carries live `[dogfood]` progress: the plan, per-step timing and
  tool-event count, and any write action. Useful because a turn only prints once
  the whole plan finishes.
- **transcript** (stdout and `--transcript`), per turn: the routed plan, each
  step's tool call/return trace, proposed / auto-approved writes, submitted PKs
  or denials, grounding warnings (ungrounded quantities, ungrounded symbols,
  syntax errors), and the agent's reply.
- **`.jsonl`** sibling of the transcript: the full structured record with
  untruncated tool returns, for programmatic analysis.

## Run mechanics (the provider is slow and flaky)

- Run **backgrounded**, and read the output file. Do **not** pipe through `tail`:
  a pipeline reports `tail`'s exit code, hiding a crash or a killed process, and
  it buffers output so you see nothing until the end.
- Do **not** wrap in `timeout`; if a run hangs it is the provider, and the wrap
  just masks the kill.
- Retry on `UnexpectedModelBehavior: Invalid response ... ChatCompletion`: that
  is an empty free-tier response, not a harness bug (the driver records it as a
  per-step error and still writes the transcript).

## The loop

1. Pick a scenario that targets one behavior: routing, grounding, a workflow
   submit, error handling.
2. Run it read-only first; read the transcript.
3. For each defect, verify it is real against the tool trace (the harness records
   exactly what each tool returned), then write it up as
   `.github/issue-<slug>.md` in the shortest technically-accurate form. Match the
   house style of the existing drafts: `**Title:**` first line, prose plus
   bullets, `file:line` refs, evidence in a `<details>` fold, no em/en dashes.
4. Before filing, read the existing `.github/issue-*.md` so you do not re-file a
   known finding.
5. **Never post to GitHub**; the user posts. Read-only `gh` is fine.
6. A confirmed defect also makes a good regression case for `tests/evals/`
   (pydantic-evals, scored against real Discourse Q&A).

## Strengths and blind spots

- **Strong** at objective defects the tool trace proves: crashes, invented CLI,
  wrong routing, ungrounded PKs/quantities, draft-vs-submit contradictions.
- **Weak** at subjective answer quality (a model grading a model shares blind
  spots). For that, anchor on `tests/evals/`, which scores against human ground
  truth.

## Safety

Only `--yes-in-sandbox`, and only against a storage-isolated sandbox, can write;
the guard fails closed. Everything else is read-only.
