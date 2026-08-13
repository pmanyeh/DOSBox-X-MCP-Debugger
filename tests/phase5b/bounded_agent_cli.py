"""
Phase 5B bounded-autonomy enforcement layer
(docs/phase5b-bounded-autonomous-debugging-design.md sections 1-2).

Sits ABOVE the existing, unmodified Phase 5A tool mechanism
(tests/phase5a/agent_cli.py's tool lookup, itself built on the unmodified
ai/server_phase5a.py). Enforces three independent limits -- total tool-call
budget, execution-step budget, wall-clock deadline -- plus a per-scenario
tool allowlist, ALL checked BEFORE a call is forwarded to the real tool.
A rejected call NEVER reaches the real tool; this file's own class,
BoundedSession, is the single place that decides forward-or-reject, so
that guarantee holds regardless of caller (a real subagent via the CLI
below, or a test with a fake/spy resolver).

This module does not implement, and does not import anything from, any
B1-B5 scenario -- per the Phase 5B implementation instructions, those are
explicitly deferred. It also does not modify, and does not need to modify,
anything under tests/phase5a/ or ai/server_phase5a.py: BoundedSession takes
a `tool_resolver` callable as a dependency, and the CLI entry point at the
bottom of this file is the ONLY place that plugs in the real one
(tests.phase5a.agent_cli's already-registered tool lookup) -- the
enforcement class itself has no live-DOSBox-X dependency at all, which is
what lets tests/phase5b/test_bounded_agent_cli.py exercise every limit
deterministically with a spy, no live bridge required.
"""

from __future__ import annotations

import argparse
import enum
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent


class Termination(enum.Enum):
    """The exactly-four recognized outcomes
    (docs/phase5b-bounded-autonomous-debugging-design.md section 2). A
    BoundedSession's termination, once set, is never overwritten -- see
    BoundedSession._finalize()."""

    SUCCESS = "SUCCESS"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    TIMEOUT_EXCEEDED = "TIMEOUT_EXCEEDED"
    POLICY_VIOLATION = "POLICY_VIOLATION"


# Only these tools advance real guest CPU time and therefore count against
# the (stricter) execution-step budget -- every other tool is a pure
# observation/control-plane call and only counts against the total budget.
EXECUTION_STEP_TOOLS = frozenset({"step_into", "step_over"})


@dataclass
class BudgetConfig:
    total_call_budget: int
    execution_step_budget: int
    deadline_seconds: float
    allowed_tools: frozenset[str]

    def to_dict(self) -> dict:
        return {
            "total_call_budget": self.total_call_budget,
            "execution_step_budget": self.execution_step_budget,
            "deadline_seconds": self.deadline_seconds,
            "allowed_tools": sorted(self.allowed_tools),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BudgetConfig":
        return cls(
            total_call_budget=d["total_call_budget"],
            execution_step_budget=d["execution_step_budget"],
            deadline_seconds=d["deadline_seconds"],
            allowed_tools=frozenset(d["allowed_tools"]),
        )


@dataclass
class CallRecord:
    tool: str
    args: dict
    forwarded: bool
    result: Any = None
    rejection_reason: Optional[str] = None
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "args": self.args,
            "forwarded": self.forwarded,
            "result": self.result,
            "rejection_reason": self.rejection_reason,
            "timestamp": self.timestamp,
        }


class BoundedSession:
    """Enforces Phase 5B's bounded observe -> reason -> act -> observe loop
    over a real (or, for testing, fake/spy) tool resolver.

    `tool_resolver(name, kwargs) -> result` is the ONLY way this class ever
    reaches "the real tool" -- in production (see `main()` below) it wraps
    tests/phase5a/agent_cli.py's tool lookup (itself the unmodified
    ai/server_phase5a.py functions); in tests it can be any spy callable,
    so every limit here is verified with zero dependency on a live
    DOSBox-X bridge.

    `clock` defaults to time.monotonic but is injectable for deterministic,
    non-flaky timeout tests -- per the Phase 5B implementation
    instructions, "avoid a flaky test based on real sleeping ... inject or
    mock the monotonic clock." `start` lets a reconstructed (persisted)
    session keep the SAME deadline anchor a fresh one established, rather
    than resetting the clock every process invocation.
    """

    def __init__(
        self,
        config: BudgetConfig,
        tool_resolver: Callable[[str, dict], Any],
        clock: Callable[[], float] = time.monotonic,
        start: Optional[float] = None,
    ):
        self.config = config
        self._tool_resolver = tool_resolver
        self._clock = clock
        self._start = start if start is not None else clock()
        self._deadline = self._start + config.deadline_seconds

        self.total_calls_attempted = 0
        self.total_calls_forwarded = 0
        self.execution_step_calls = 0

        self.attempted_tool_names: list[str] = []
        self.forwarded_tool_names: list[str] = []
        self.records: list[CallRecord] = []

        self._termination: Optional[Termination] = None
        self._termination_reason: Optional[str] = None

    # -- termination bookkeeping -------------------------------------

    @property
    def terminated(self) -> bool:
        return self._termination is not None

    @property
    def termination(self) -> Optional[Termination]:
        return self._termination

    @property
    def termination_reason(self) -> Optional[str]:
        return self._termination_reason

    def _finalize(self, termination: Termination, reason: str) -> None:
        # "Do not silently translate one termination type into another" --
        # once set, this session's termination is immutable. A later call
        # to _finalize() (e.g. finish_success() invoked after a budget
        # rejection already happened) is a no-op, not an overwrite.
        if self._termination is not None:
            return
        self._termination = termination
        self._termination_reason = reason

    def finish_success(self) -> None:
        """Called by the orchestrator once the agent's turn ends normally
        (it produced a final answer and made no further calls) without any
        limit having been hit. A no-op if the session already terminated
        some other way."""

        self._finalize(Termination.SUCCESS, "agent completed its turn within budget and deadline")

    # -- the enforcement gate -----------------------------------------

    def call(self, tool_name: str, args: Optional[dict] = None) -> dict:
        """Attempt one tool call. Checks policy, deadline, and both budgets
        -- in that order -- BEFORE ever invoking the real tool_resolver.
        Every attempt (forwarded or not) is recorded."""

        args = args or {}
        now = self._clock()
        self.total_calls_attempted += 1
        self.attempted_tool_names.append(tool_name)

        if self.terminated:
            # Session already ended -- refuse further calls without ever
            # touching the real tool, and without changing the recorded
            # termination (see _finalize()).
            reason = f"session already terminated: {self._termination.value}"
            self.records.append(CallRecord(tool=tool_name, args=args, forwarded=False, rejection_reason=reason, timestamp=now))
            return {"ok": False, "error": {"code": self._termination.value, "message": reason}}

        # 1. policy check -- tool outside this scenario's allowed surface.
        if tool_name not in self.config.allowed_tools:
            reason = f"tool {tool_name!r} is not in this scenario's allowed tool set {sorted(self.config.allowed_tools)}"
            self._finalize(Termination.POLICY_VIOLATION, reason)
            self.records.append(CallRecord(tool=tool_name, args=args, forwarded=False, rejection_reason=reason, timestamp=now))
            return {"ok": False, "error": {"code": Termination.POLICY_VIOLATION.value, "message": reason}}

        # 2. deadline check -- monotonic clock only, per the design.
        if now > self._deadline:
            elapsed = now - self._start
            reason = f"wall-clock deadline exceeded ({elapsed:.3f}s elapsed > {self.config.deadline_seconds}s budget)"
            self._finalize(Termination.TIMEOUT_EXCEEDED, reason)
            self.records.append(CallRecord(tool=tool_name, args=args, forwarded=False, rejection_reason=reason, timestamp=now))
            return {"ok": False, "error": {"code": Termination.TIMEOUT_EXCEEDED.value, "message": reason}}

        # 3. total tool-call budget.
        if self.total_calls_forwarded >= self.config.total_call_budget:
            reason = f"total tool-call budget exhausted ({self.config.total_call_budget} calls)"
            self._finalize(Termination.BUDGET_EXHAUSTED, reason)
            self.records.append(CallRecord(tool=tool_name, args=args, forwarded=False, rejection_reason=reason, timestamp=now))
            return {"ok": False, "error": {"code": Termination.BUDGET_EXHAUSTED.value, "message": reason}}

        # 4. execution-step budget -- only step_into/step_over count.
        is_exec_step = tool_name in EXECUTION_STEP_TOOLS
        if is_exec_step and self.execution_step_calls >= self.config.execution_step_budget:
            reason = f"execution-step budget exhausted ({self.config.execution_step_budget} steps)"
            self._finalize(Termination.BUDGET_EXHAUSTED, reason)
            self.records.append(CallRecord(tool=tool_name, args=args, forwarded=False, rejection_reason=reason, timestamp=now))
            return {"ok": False, "error": {"code": Termination.BUDGET_EXHAUSTED.value, "message": reason}}

        # -- allowed: forward to the real tool. --
        result = self._tool_resolver(tool_name, args)
        self.total_calls_forwarded += 1
        self.forwarded_tool_names.append(tool_name)
        if is_exec_step:
            self.execution_step_calls += 1
        self.records.append(CallRecord(tool=tool_name, args=args, forwarded=True, result=result, timestamp=now))
        return result

    # -- evidence -------------------------------------------------------

    def evidence(self) -> dict:
        """Machine-readable evidence of what happened this session -- at
        minimum the fields docs/phase5b-bounded-autonomous-debugging-design.md
        and the Phase 5B implementation instructions require."""

        return {
            "termination": self._termination.value if self._termination else None,
            "termination_reason": self._termination_reason,
            "total_calls_attempted": self.total_calls_attempted,
            "total_calls_forwarded": self.total_calls_forwarded,
            "execution_step_calls": self.execution_step_calls,
            "attempted_tool_names": list(self.attempted_tool_names),
            "forwarded_tool_names": list(self.forwarded_tool_names),
            "last_attempted_tool": self.attempted_tool_names[-1] if self.attempted_tool_names else None,
            "deadline_exceeded": self._termination == Termination.TIMEOUT_EXCEEDED,
            "rejection_reason": (
                self._termination_reason
                if self._termination in (Termination.BUDGET_EXHAUSTED, Termination.TIMEOUT_EXCEEDED, Termination.POLICY_VIOLATION)
                else None
            ),
        }

    # -- persistence (cross-process CLI use only; unused by the core
    #    enforcement tests, which talk to BoundedSession in-process) -------

    def to_state_dict(self) -> dict:
        return {
            "config": self.config.to_dict(),
            "start": self._start,
            "total_calls_attempted": self.total_calls_attempted,
            "total_calls_forwarded": self.total_calls_forwarded,
            "execution_step_calls": self.execution_step_calls,
            "attempted_tool_names": self.attempted_tool_names,
            "forwarded_tool_names": self.forwarded_tool_names,
            "records": [r.to_dict() for r in self.records],
            "termination": self._termination.value if self._termination else None,
            "termination_reason": self._termination_reason,
        }

    @classmethod
    def from_state_dict(cls, d: dict, tool_resolver: Callable[[str, dict], Any], clock: Callable[[], float] = time.monotonic) -> "BoundedSession":
        session = cls(BudgetConfig.from_dict(d["config"]), tool_resolver, clock=clock, start=d["start"])
        session.total_calls_attempted = d["total_calls_attempted"]
        session.total_calls_forwarded = d["total_calls_forwarded"]
        session.execution_step_calls = d["execution_step_calls"]
        session.attempted_tool_names = list(d["attempted_tool_names"])
        session.forwarded_tool_names = list(d["forwarded_tool_names"])
        session.records = [CallRecord(**r) for r in d["records"]]
        if d["termination"] is not None:
            session._termination = Termination(d["termination"])
            session._termination_reason = d["termination_reason"]
        return session


# ======================================================================
# CLI entry point -- production wiring only. Not exercised by
# tests/phase5b/test_bounded_agent_cli.py (which drives BoundedSession
# directly with a fake/spy resolver); reuses tests/phase5a/agent_cli.py's
# already-registered real tool lookup, unmodified, unduplicated. Not used
# by any B1-B5 scenario yet -- those are explicitly out of scope for this
# change.
# ======================================================================


def _real_tool_resolver():
    """Builds a resolver over the REAL, unmodified Phase 5A tools by
    reusing tests/phase5a/agent_cli.py's own tool lookup -- imported, not
    reimplemented. Deferred until actually needed (CLI use) so this
    module's core classes above have no import-time dependency on
    ai/server_phase5a.py or a live DOSBox-X bridge."""

    sys.path.insert(0, str(_ROOT))
    from tests.phase5a import agent_cli  # noqa: PLC0415

    tools = agent_cli._registered_tools()

    def resolver(name: str, args: dict) -> Any:
        return tools[name](**args)

    return resolver


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, help="Path to this session's persisted JSON state file")
    parser.add_argument("--tool", required=True, help="Tool name to attempt")
    parser.add_argument("--args", default="{}", help="JSON object of keyword arguments")
    parser.add_argument("--total-budget", type=int, help="Total tool-call budget (required to initialize a new session)")
    parser.add_argument("--exec-budget", type=int, help="Execution-step budget (required to initialize a new session)")
    parser.add_argument("--deadline-seconds", type=float, help="Wall-clock deadline in seconds (required to initialize a new session)")
    parser.add_argument("--allowed-tools", help="Comma-separated allowed tool names (required to initialize a new session)")
    ns = parser.parse_args()

    resolver = _real_tool_resolver()
    state_path = Path(ns.state)

    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        session = BoundedSession.from_state_dict(state, resolver)
    else:
        missing = [
            flag
            for flag, val in [
                ("--total-budget", ns.total_budget),
                ("--exec-budget", ns.exec_budget),
                ("--deadline-seconds", ns.deadline_seconds),
                ("--allowed-tools", ns.allowed_tools),
            ]
            if val is None
        ]
        if missing:
            parser.error(f"state file does not exist yet -- must provide {missing} to initialize a new session")
        config = BudgetConfig(
            total_call_budget=ns.total_budget,
            execution_step_budget=ns.exec_budget,
            deadline_seconds=ns.deadline_seconds,
            allowed_tools=frozenset(t.strip() for t in ns.allowed_tools.split(",") if t.strip()),
        )
        session = BoundedSession(config, resolver)

    args = json.loads(ns.args)
    result = session.call(ns.tool, args)

    state_path.write_text(json.dumps(session.to_state_dict(), indent=2), encoding="utf-8")
    print(json.dumps({"result": result, "evidence": session.evidence()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
