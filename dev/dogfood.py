"""Headless driver for dogfooding the AiiDA agents.

Reuses the exact pieces the REPL runs (:func:`_build_agent`, :func:`ask`,
:func:`plan`) so a scripted or model-in-the-loop conversation exercises the real
planner, routing, tools and grounding checks, without the interactive TUI and
with a structured transcript in place of rich rendering. The point is to let an
evaluator drive the tool turn by turn and read back *what actually happened*
(which specialist answered, which tools ran with which arguments, whether the
reply carried ungrounded quantities), rather than eyeballing a terminal.

Read-only by design here: a turn that proposes a write (the run returns a
``DeferredToolRequests``) is recorded and stopped at, never approved. Auto
approval against the disposable sandbox copy is a deliberate later increment,
gated on a sandbox-only safety check, so this version cannot mutate storage.

One turn, persisting history so the next invocation resumes the conversation::

    .venv/bin/python dev/dogfood.py turn \\
        --profile agents-sandbox --agent auto \\
        --session /tmp/df.json --transcript /tmp/df.md \\
        --message "Run a PwRelaxWorkChain on the same structure as before."

A whole scenario (several turns) in one process::

    .venv/bin/python dev/dogfood.py scenario \\
        --profile agents-sandbox --agent auto --transcript /tmp/df.md \\
        --turn "What structures are in this profile?" \\
        --turn "Relax the first one with a PwRelaxWorkChain."

The turns run against whatever provider/model ``ModelSettings`` resolves (the
repo ``.env``, then ``AIIDA_AGENTS_*`` env, then flags), so the driver talks to
the same backend a manual ``aiida-agents chat`` session would.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Heavy aiida / agent-stack imports stay inside the functions that need them, so
# ``--help`` stays instant and importing this module never loads AiiDA.

_DEFAULT_PROFILE = "agents-sandbox"
_AGENT_CHOICES = ("auto", "analysis", "execution", "codegen")


def _progress(message: str) -> None:
    """A live status line on stderr, kept out of the markdown transcript.

    A turn on a slow provider makes several LLM round-trips (planner, then the
    specialist's tool rounds), and the rendered turn only appears once it is all
    done; without this a long run is indistinguishable from a hung one.
    """
    sys.stderr.write(f"[dogfood] {message}\n")
    sys.stderr.flush()

#: Tool-return content is spliced whole into the JSONL record but truncated in
#: the human transcript, where a multi-kB QueryBuilder dump would bury the prose.
_TRANSCRIPT_CONTENT_CHARS = 400


@dataclass
class ToolEvent:
    """One tool call or its return, in the order the run produced it."""

    kind: str  # "call" | "return"
    name: str
    detail: str


@dataclass
class StepRecord:
    """What one plan step produced: routing, tool trace, reply, grounding."""

    specialist: str
    task: str
    tools: list[ToolEvent] = field(default_factory=list)
    output: str | None = None
    error: str | None = None
    proposed_writes: list[str] = field(default_factory=list)
    # Present only when --yes-in-sandbox ran the writes: what each approved call
    # returned (submitted PKs, or an error), and any the triage denied as invalid.
    submitted: list[Any] = field(default_factory=list)
    auto_denied: list[str] = field(default_factory=list)
    ungrounded_quantities: list[str] = field(default_factory=list)
    ungrounded_symbols: list[str] = field(default_factory=list)
    syntax_errors: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0


@dataclass
class TurnRecord:
    """One user turn and every step the plan ran for it."""

    index: int
    question: str
    plan: list[str] = field(default_factory=list)
    steps: list[StepRecord] = field(default_factory=list)


class DogfoodSession:
    """A resumable, headless agent conversation over one profile.

    Mirrors the REPL's structure: in ``auto`` mode each specialist keeps its own
    message history (their tool sets differ, so replaying one's history to
    another references tools it does not have), built lazily on first use.
    """

    def __init__(
        self,
        *,
        profile: str,
        agent_type: str,
        provider: str | None = None,
        model: str | None = None,
        allow_writes: bool = False,
    ) -> None:
        from aiida_agents.cli.agent import _resolve_model_settings

        self.profile = profile
        self.agent_type = agent_type
        self.settings = _resolve_model_settings(provider, model)
        self.allow_writes = allow_writes
        self._agents: dict[str, Any] = {}
        # Per-specialist message history, kept as native pydantic-ai objects.
        self._histories: dict[str, list[Any]] = {}
        self._turns = 0
        if allow_writes:
            # Fail before any LLM call if the target is not a self-contained
            # sandbox: auto-approval must never be able to write through a
            # profile that shares storage with a real one.
            self._verify_sandbox_writable()

    def _verify_sandbox_writable(self) -> None:
        """Refuse write mode unless the profile shares storage with no other.

        The same question ``sandbox check`` / ``init`` / ``teardown`` ask
        (:func:`profiles_sharing_storage`): an empty result is the only proof
        that a write here cannot reach another profile's data. Anything else
        (a proven overlap, or a config that cannot be read) fails closed.
        """
        from aiida.manage.configuration import get_config

        from aiida_agents.sandbox.copy import profiles_sharing_storage

        config = get_config()
        if self.profile not in {p.name for p in config.profiles}:
            msg = f"profile {self.profile!r} is not registered; refusing --yes-in-sandbox"
            raise SystemExit(msg)
        sharing = profiles_sharing_storage(config, self.profile)
        if sharing:
            detail = "; ".join(f"{self.profile!r} {s.describe()}" for s in sharing)
            msg = (
                f"refusing --yes-in-sandbox: {self.profile!r} is not a self-contained "
                f"sandbox ({detail}). Auto-approval only runs against a profile that "
                "shares no storage with any other."
            )
            raise SystemExit(msg)
        _progress(
            f"writes ENABLED against sandbox {self.profile!r} "
            "(guard passed: shares no storage with any profile)"
        )

    # -- persistence -------------------------------------------------------

    def to_file(self, path: Path) -> None:
        """Serialise agent type, profile and per-specialist history to JSON.

        History goes through ``ModelMessagesTypeAdapter`` so a resumed run gets
        back the exact message objects pydantic-ai emitted, tool-call/return
        pairs intact, rather than a lossy hand-rolled dump.
        """
        from pydantic_ai.messages import ModelMessagesTypeAdapter

        payload = {
            "profile": self.profile,
            "agent_type": self.agent_type,
            "turns": self._turns,
            "histories": {
                specialist: ModelMessagesTypeAdapter.dump_python(messages, mode="json")
                for specialist, messages in self._histories.items()
            },
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_file(self, path: Path) -> None:
        """Restore history from a prior :meth:`to_file`, if the file exists."""
        from pydantic_ai.messages import ModelMessagesTypeAdapter

        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        self._turns = payload.get("turns", 0)
        self._histories = {
            specialist: ModelMessagesTypeAdapter.validate_python(messages)
            for specialist, messages in payload.get("histories", {}).items()
        }

    # -- running -----------------------------------------------------------

    def _plan(self, question: str) -> list[Any]:
        """Resolve the request into steps, honouring an explicitly named agent.

        The same rule as ``_resolve_plan``: ``auto`` asks the planner, a named
        specialist is a single step, minus the console printing (the plan is
        captured into the record instead).
        """
        from aiida_agents.agents.planner import Step, _as_specialist, plan

        if self.agent_type != "auto":
            return [Step(_as_specialist(self.agent_type), "")]
        _progress("  resolving plan (planner LLM call)...")
        return plan(question, self.settings)

    def _agent_for(self, specialist: str) -> Any:
        if specialist not in self._agents:
            from aiida_agents.cli.agent import _build_agent

            self._agents[specialist] = _build_agent(
                self.settings, self.profile, specialist
            )
        return self._agents[specialist]

    def run_turn(self, question: str) -> TurnRecord:
        """Run one user turn through the plan and return a structured record."""
        from aiida_agents.cli.agent import _StepResult

        self._turns += 1
        _progress(f'turn {self._turns}: "{_oneline(question, 60)}"')
        steps = self._plan(question)
        plan_labels = [
            f"{step.specialist}: {step.task}".rstrip(": ") for step in steps
        ]
        _progress(f"  plan = {' -> '.join(plan_labels) or '(none)'}")
        record = TurnRecord(index=self._turns, question=question, plan=plan_labels)

        previous: _StepResult | None = None
        for step in steps:
            step_record, references = self._run_step(step, question, previous)
            record.steps.append(step_record)
            if step_record.output is None:
                # Errored, or stopped at a write. A later step built on a
                # premise this one never established is worse than no step.
                break
            previous = _StepResult(step.specialist, step_record.output, references)
        return record

    def _run_step(
        self, step: Any, question: str, previous: Any
    ) -> tuple[StepRecord, tuple[Any, ...]]:
        """Run one step; return its record and the node references its tools
        produced (empty on error or a stopped write), for the next step's handoff.
        """
        from aiida_agents.agents.handoff import node_references_from_messages
        from aiida_agents.cli.agent import _step_prompt, ask
        from pydantic_ai.tools import DeferredToolRequests

        specialist = step.specialist
        record = StepRecord(specialist=specialist, task=step.task)
        prompt = _step_prompt(step, question, previous)

        _progress(f"  step {specialist}: running...")
        start = time.monotonic()
        try:
            agent = self._agent_for(specialist)
            result = asyncio.run(
                ask(agent, prompt, self._histories.get(specialist) or None)
            )
        except KeyboardInterrupt:
            record.error = "interrupted"
            record.elapsed_s = time.monotonic() - start
            return record, ()
        except Exception as exc:  # noqa: BLE001 - same boundary the CLI has
            record.error = f"{type(exc).__name__}: {exc}"
            record.elapsed_s = time.monotonic() - start
            _progress(f"  step {specialist}: ERROR after {record.elapsed_s:.1f}s: {exc}")
            return record, ()
        record.elapsed_s = time.monotonic() - start

        record.tools = _tool_events(result.new_messages())
        _progress(
            f"  step {specialist}: done in {record.elapsed_s:.1f}s, "
            f"{len(record.tools)} tool events"
        )

        if isinstance(result.output, DeferredToolRequests):
            record.proposed_writes = [c.tool_name for c in result.output.approvals]
            if not self.allow_writes:
                # Read-only: record what it wanted, advance nothing. Leaving the
                # unanswered tool call out of history keeps the next turn valid.
                return record, ()
            _progress(
                f"  step {specialist}: auto-approving "
                f"{', '.join(record.proposed_writes)} in sandbox..."
            )
            self._handle_write(agent, result, specialist, question, record)
            return record, ()

        record.output = result.output
        references = node_references_from_messages(result.new_messages())
        self._histories[specialist] = result.all_messages()
        _grounding_into(record, result.all_messages(), question)
        return record, references

    def _handle_write(
        self,
        agent: Any,
        result: Any,
        specialist: str,
        question: str,
        record: StepRecord,
    ) -> None:
        """Approve and run the pending writes against the guarded sandbox.

        Reuses the CLI's own approval machinery (:mod:`aiida_agents.cli.hitl`)
        so a submission is resolved, validated and run on the main thread the
        same way an interactive approval would, minus the ``click.confirm``.
        Invalid submissions are recorded as denials rather than looping the
        model to self-correct; that round-trip is a later refinement, and a turn
        reporting "the agent proposed an invalid submission" is itself a finding.
        """
        from aiida_agents.cli.hitl import (
            _run_approvals,
            _splice_outcomes,
            _triage_submissions,
        )
        from pydantic_ai.tools import DeferredToolRequests

        pending = result.output
        auto, previews = _triage_submissions(pending)
        record.auto_denied = [denied.message for denied in auto.values()]
        if not previews:
            # Every proposed write was invalid and denied before running.
            return
        outcomes = _run_approvals(agent, previews, auto)
        record.submitted = list(outcomes.values())
        updated = _splice_outcomes(result, pending, outcomes)
        self._histories[specialist] = updated

        # Let the agent see the outcomes and report the PKs it submitted.
        try:
            narration = asyncio.run(agent.run(None, message_history=updated))
        except Exception as exc:  # noqa: BLE001 - same provider boundary as above
            record.error = f"post-submit narration failed: {type(exc).__name__}: {exc}"
            return
        record.tools += _tool_events(narration.new_messages())
        if isinstance(narration.output, DeferredToolRequests):
            # A further write after the submit: record it, do not auto-run again.
            record.proposed_writes += [c.tool_name for c in narration.output.approvals]
            return
        record.output = narration.output
        self._histories[specialist] = narration.all_messages()
        _grounding_into(record, narration.all_messages(), question)


def _tool_events(messages: list[Any]) -> list[ToolEvent]:
    """Flatten a run's new messages into an ordered call/return trace."""
    from pydantic_ai.messages import ToolCallPart, ToolReturnPart

    events: list[ToolEvent] = []
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                try:
                    detail = json.dumps(part.args_as_dict(), default=str)
                except Exception:  # noqa: BLE001 - args can be a raw string
                    detail = str(part.args)
                events.append(ToolEvent("call", part.tool_name, detail))
            elif isinstance(part, ToolReturnPart):
                events.append(ToolEvent("return", part.tool_name, str(part.content)))
    return events


def _grounding_into(record: StepRecord, messages: list[Any], question: str) -> None:
    """Fill the record's grounding fields, the same checks ``_warn_ungrounded`` runs."""
    from aiida_agents.grounding import (
        syntax_errors,
        tool_output_text,
        ungrounded_quantities,
        ungrounded_symbols,
    )

    evidence = tool_output_text(messages)
    record.ungrounded_quantities = sorted(
        ungrounded_quantities(record.output or "", evidence, question)
    )
    record.ungrounded_symbols = sorted(
        ungrounded_symbols(record.output or "", evidence)
    )
    record.syntax_errors = list(syntax_errors(record.output or ""))


# -- rendering -------------------------------------------------------------


def _render_turn(record: TurnRecord, *, full: bool) -> str:
    """One turn as markdown. ``full`` keeps whole tool returns (for the JSONL's
    companion transcript we truncate; ``full`` is unused for now but kept so a
    verbose mode is a one-line change)."""
    lines: list[str] = []
    lines.append(f'## Turn {record.index}: "{_oneline(record.question)}"')
    lines.append("")
    arrow = " -> ".join(record.plan) if record.plan else "(no plan)"
    lines.append(f"**Plan:** {arrow}")
    lines.append("")
    for number, step in enumerate(record.steps, start=1):
        lines.append(f"### step {number}: {step.specialist}  ({step.elapsed_s:.1f}s)")
        if step.error is not None:
            lines.append(f"- error: {step.error}")
        for event in step.tools:
            marker = "->" if event.kind == "call" else "<-"
            detail = event.detail
            if not full and len(detail) > _TRANSCRIPT_CONTENT_CHARS:
                detail = detail[:_TRANSCRIPT_CONTENT_CHARS] + " ...[truncated]"
            lines.append(f"- {marker} `{event.name}` {detail}")
        wrote = bool(step.submitted or step.auto_denied)
        if step.proposed_writes and not wrote:
            joined = ", ".join(step.proposed_writes)
            lines.append(f"- **proposed writes (STOPPED, read-only):** {joined}")
        elif step.proposed_writes:
            joined = ", ".join(step.proposed_writes)
            lines.append(f"- **proposed writes (auto-approved in sandbox):** {joined}")
        for outcome in step.submitted:
            lines.append(f"- ✅ ran/submitted: {outcome}")
        for denial in step.auto_denied:
            lines.append(f"- ✗ denied before running (invalid): {_oneline(denial, 160)}")
        if step.ungrounded_quantities:
            lines.append(
                f"- ⚠ ungrounded quantities: {', '.join(step.ungrounded_quantities)}"
            )
        if step.ungrounded_symbols:
            lines.append(
                f"- ⚠ ungrounded symbols: {', '.join(step.ungrounded_symbols)}"
            )
        if step.syntax_errors:
            lines.append(f"- ⚠ syntax errors: {'; '.join(step.syntax_errors)}")
        lines.append("")
        if step.output is not None:
            lines.append("**Agent:**")
            lines.append("")
            lines.append(step.output)
            lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _oneline(text: str, limit: int = 80) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit] + "..."


def _record_to_jsonl(record: TurnRecord) -> str:
    """One turn as a single JSON line, tool returns kept whole for the record."""
    return json.dumps(asdict(record), default=str)


def _emit(record: TurnRecord, transcript: Path | None) -> None:
    """Append the turn to the transcript (+ a sibling JSONL) and to stdout."""
    rendered = _render_turn(record, full=False)
    if transcript is not None:
        with transcript.open("a", encoding="utf-8") as handle:
            handle.write(rendered)
        jsonl = transcript.with_suffix(".jsonl")
        with jsonl.open("a", encoding="utf-8") as handle:
            handle.write(_record_to_jsonl(record) + "\n")
    # Stdout gets the same markdown so a single Bash run shows the whole turn
    # without opening the file.
    sys.stdout.write(rendered)
    sys.stdout.flush()


# -- CLI -------------------------------------------------------------------


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", default=_DEFAULT_PROFILE)
    parser.add_argument("--agent", default="auto", choices=_AGENT_CHOICES)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--transcript",
        type=Path,
        default=None,
        help="Markdown transcript to append to (a sibling .jsonl is written too).",
    )
    parser.add_argument(
        "--yes-in-sandbox",
        action="store_true",
        help=(
            "Actually run proposed writes (submissions), instead of stopping at "
            "them. Refuses unless --profile is a sandbox that shares storage with "
            "no other profile. Writes go to that disposable copy only."
        ),
    )


def _cmd_turn(args: argparse.Namespace) -> int:
    session = DogfoodSession(
        profile=args.profile,
        agent_type=args.agent,
        provider=args.provider,
        model=args.model,
        allow_writes=args.yes_in_sandbox,
    )
    session_path = Path(args.session)
    session.load_file(session_path)

    message = sys.stdin.read() if args.message == "-" else args.message
    _print_header(session)
    record = session.run_turn(message)
    _emit(record, args.transcript)
    session.to_file(session_path)
    return 0


def _cmd_scenario(args: argparse.Namespace) -> int:
    turns: list[str] = list(args.turn or [])
    if args.file is not None:
        turns.extend(_load_turns(Path(args.file)))
    if not turns:
        sys.stderr.write("No turns given (use --turn or --file).\n")
        return 2

    session = DogfoodSession(
        profile=args.profile,
        agent_type=args.agent,
        provider=args.provider,
        model=args.model,
        allow_writes=args.yes_in_sandbox,
    )
    _print_header(session)
    for turn in turns:
        record = session.run_turn(turn)
        _emit(record, args.transcript)
    if args.session is not None:
        session.to_file(Path(args.session))
    return 0


def _load_turns(path: Path) -> list[str]:
    """Turns from a file: a JSON list, or ``---``-separated blocks of text."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(text)
        if not isinstance(data, list):
            msg = f"{path}: expected a JSON list of strings"
            raise ValueError(msg)
        return [str(item) for item in data]
    return [block.strip() for block in text.split("\n---\n") if block.strip()]


def _print_header(session: DogfoodSession) -> None:
    mode = "WRITE (auto-approve in sandbox)" if session.allow_writes else "read-only"
    sys.stdout.write(
        f"# dogfood: profile={session.profile} agent={session.agent_type} "
        f"provider={session.settings.provider} model={session.settings.model} "
        f"mode={mode}\n\n"
    )
    sys.stdout.flush()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    turn = sub.add_parser("turn", help="Run one turn, persisting history to --session.")
    _add_common(turn)
    turn.add_argument("--session", required=True, help="History file (JSON), resumed if present.")
    turn.add_argument("--message", required=True, help="The user turn ('-' reads stdin).")
    turn.set_defaults(func=_cmd_turn)

    scenario = sub.add_parser("scenario", help="Run several turns in one process.")
    _add_common(scenario)
    scenario.add_argument("--turn", action="append", help="A user turn (repeatable).")
    scenario.add_argument("--file", default=None, help="JSON list or ---separated turns.")
    scenario.add_argument("--session", default=None, help="Optional: persist final history here.")
    scenario.set_defaults(func=_cmd_scenario)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
