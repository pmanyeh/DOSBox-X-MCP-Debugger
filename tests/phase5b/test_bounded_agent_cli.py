"""
Focused tests for the Phase 5B bounded-autonomy harness
(tests/phase5b/bounded_agent_cli.py), per the Phase 5B implementation
instructions: these exercise BoundedSession's enforcement logic directly,
against a fake/spy tool resolver -- no live DOSBox-X bridge, no
ai/server_phase5a.py, no tests/phase5a/agent_cli.py dependency, so they
never skip and never flake on environment/timing. B1-B5 scenarios are
explicitly out of scope here.
"""

import pytest

from tests.phase5b.bounded_agent_cli import (
    BoundedSession,
    BudgetConfig,
    EXECUTION_STEP_TOOLS,
    Termination,
)


class SpyResolver:
    """Fake tool_resolver: records every call it actually receives (i.e.
    every call BoundedSession forwarded) and returns a canned result. If
    BoundedSession's enforcement has a gap, this spy's own call count is
    the ground truth that catches it -- not BoundedSession's own bookkeeping,
    which could in principle be self-consistently wrong."""

    def __init__(self):
        self.invocations: list[tuple[str, dict]] = []

    def __call__(self, name: str, args: dict):
        self.invocations.append((name, args))
        return {"ok": True, "result": {"tool": name, "args": args}}

    @property
    def call_count(self) -> int:
        return len(self.invocations)


class FakeClock:
    """Deterministic, injectable monotonic-style clock -- starts at an
    arbitrary nonzero offset (to catch any code that wrongly assumes t=0)
    and only advances when told to, so timeout tests never sleep."""

    def __init__(self, start: float = 1_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_config(**overrides) -> BudgetConfig:
    defaults = dict(
        total_call_budget=100,
        execution_step_budget=100,
        deadline_seconds=3600.0,
        allowed_tools=frozenset(
            {"get_debug_status", "get_cpu_state", "step_into", "step_over", "set_breakpoint", "continue_execution"}
        ),
    )
    defaults.update(overrides)
    return BudgetConfig(**defaults)


# ======================================================================
# Test 1 -- total-call boundary
# ======================================================================


def test_total_call_boundary_exact_count_and_rejection():
    spy = SpyResolver()
    config = make_config(total_call_budget=3)
    session = BoundedSession(config, spy)

    r1 = session.call("get_debug_status")
    r2 = session.call("get_debug_status")
    r3 = session.call("get_debug_status")
    assert r1["ok"] and r2["ok"] and r3["ok"]
    assert spy.call_count == 3

    r4 = session.call("get_debug_status")

    assert spy.call_count == 3, "the 4th call must never reach the underlying tool"
    assert r4["ok"] is False
    assert r4["error"]["code"] == Termination.BUDGET_EXHAUSTED.value
    assert session.termination == Termination.BUDGET_EXHAUSTED
    assert session.total_calls_attempted == 4
    assert session.total_calls_forwarded == 3


# ======================================================================
# Test 2 -- execution-step boundary
# ======================================================================


def test_execution_step_boundary_observation_calls_are_free():
    spy = SpyResolver()
    config = make_config(total_call_budget=100, execution_step_budget=2)
    session = BoundedSession(config, spy)

    # Many observation calls -- must NOT consume the execution-step budget.
    for _ in range(10):
        result = session.call("get_debug_status")
        assert result["ok"], result
    assert session.execution_step_calls == 0
    assert spy.call_count == 10
    assert not session.terminated

    # step_into/step_over DO consume it.
    r1 = session.call("step_into")
    r2 = session.call("step_over")
    assert r1["ok"] and r2["ok"]
    assert session.execution_step_calls == 2
    assert spy.call_count == 12

    # Third execution-step attempt must be rejected BEFORE forwarding.
    r3 = session.call("step_into")
    assert spy.call_count == 12, "the over-budget execution-step call must never reach the underlying tool"
    assert r3["ok"] is False
    assert r3["error"]["code"] == Termination.BUDGET_EXHAUSTED.value
    assert session.termination == Termination.BUDGET_EXHAUSTED
    assert session.execution_step_calls == 2

    for tool in EXECUTION_STEP_TOOLS:
        assert tool in {"step_into", "step_over"}


def test_execution_step_boundary_independent_of_total_budget():
    # Even with plenty of TOTAL budget left, exhausting the (stricter)
    # execution-step budget must still terminate the session.
    spy = SpyResolver()
    config = make_config(total_call_budget=50, execution_step_budget=1)
    session = BoundedSession(config, spy)

    assert session.call("step_into")["ok"] is True
    rejected = session.call("step_over")
    assert rejected["ok"] is False
    assert rejected["error"]["code"] == Termination.BUDGET_EXHAUSTED.value
    assert session.total_calls_forwarded == 1  # far below total_call_budget=50
    assert spy.call_count == 1


# ======================================================================
# Test 3 -- timeout boundary (deterministic, no real sleeping)
# ======================================================================


def test_timeout_boundary_uses_injected_monotonic_clock():
    spy = SpyResolver()
    clock = FakeClock(start=1_000.0)
    config = make_config(deadline_seconds=10.0)
    session = BoundedSession(config, spy, clock=clock)

    # Well within the deadline -- forwarded normally.
    ok = session.call("get_debug_status")
    assert ok["ok"] is True
    assert spy.call_count == 1

    # Force a deterministic expired deadline -- no time.sleep anywhere.
    clock.advance(11.0)

    result = session.call("get_debug_status")

    assert spy.call_count == 1, "a call attempted past the deadline must never reach the underlying tool"
    assert result["ok"] is False
    assert result["error"]["code"] == Termination.TIMEOUT_EXCEEDED.value
    assert session.termination == Termination.TIMEOUT_EXCEEDED
    assert session.attempted_tool_names[-1] == "get_debug_status"
    assert session.evidence()["deadline_exceeded"] is True


# ======================================================================
# Test 4 -- policy violation
# ======================================================================


def test_policy_violation_rejects_tool_outside_allowed_set():
    spy = SpyResolver()
    config = make_config(allowed_tools=frozenset({"get_debug_status", "step_into", "step_over"}))
    session = BoundedSession(config, spy)

    result = session.call("set_breakpoint", {"address": "1234:0100"})

    assert spy.call_count == 0, "a policy-violating call must never reach the underlying tool"
    assert result["ok"] is False
    assert result["error"]["code"] == Termination.POLICY_VIOLATION.value
    assert session.termination == Termination.POLICY_VIOLATION
    assert session.attempted_tool_names == ["set_breakpoint"]
    assert session.forwarded_tool_names == []


def test_policy_violation_write_register_and_write_memory_never_available():
    # Phase 5B requirement: write_register/write_memory stay unavailable.
    # Even if a scenario's allowed_tools set were mistakenly constructed to
    # include them, BoundedSession's own EXECUTION_STEP_TOOLS/allowed-set
    # mechanism treats them like any other tool name -- the real guarantee
    # (as in Phase 5A) is that ai/server_phase5a.py never exposes them at
    # all, so no resolver built from it can ever be asked to run them.
    # Here we confirm the harness layer ALSO rejects them if a caller
    # somehow attempted one against a scenario that (correctly) never
    # allow-lists them.
    spy = SpyResolver()
    config = make_config(allowed_tools=frozenset({"get_debug_status"}))
    session = BoundedSession(config, spy)

    for tool in ("write_register", "write_memory"):
        session = BoundedSession(config, spy)
        result = session.call(tool, {"register": "eax", "value": "0"})
        assert result["error"]["code"] == Termination.POLICY_VIOLATION.value
        assert spy.call_count == 0


# ======================================================================
# Test 5 -- exactly-one termination
# ======================================================================


def test_exactly_one_termination_not_silently_replaced():
    spy = SpyResolver()
    config = make_config(total_call_budget=1)
    session = BoundedSession(config, spy)

    session.call("get_debug_status")  # consumes the only budgeted call
    rejected = session.call("get_debug_status")  # triggers BUDGET_EXHAUSTED
    assert rejected["error"]["code"] == Termination.BUDGET_EXHAUSTED.value
    assert session.termination == Termination.BUDGET_EXHAUSTED
    first_reason = session.termination_reason

    # Orchestrator mistakenly (or in a race) calls finish_success() after
    # the session already terminated -- must be a no-op.
    session.finish_success()
    assert session.termination == Termination.BUDGET_EXHAUSTED
    assert session.termination_reason == first_reason

    # Further calls after termination must also never reach the real tool,
    # and must not change the recorded termination either.
    still_rejected = session.call("get_cpu_state")
    assert still_rejected["ok"] is False
    assert session.termination == Termination.BUDGET_EXHAUSTED
    assert spy.call_count == 1, "no call after termination may ever reach the underlying tool"


def test_exactly_one_termination_success_is_final_too():
    spy = SpyResolver()
    config = make_config(total_call_budget=5)
    session = BoundedSession(config, spy)

    session.call("get_debug_status")
    session.finish_success()
    assert session.termination == Termination.SUCCESS

    # A later over-budget-style call must not silently convert SUCCESS into
    # BUDGET_EXHAUSTED or any other outcome.
    session.call("get_debug_status")
    assert session.termination == Termination.SUCCESS


# ======================================================================
# Evidence / trace content (supports the "prove the rejected call never
# reached the real tool" requirement independent of the specific tests above)
# ======================================================================


def test_evidence_records_attempted_vs_forwarded_distinctly():
    spy = SpyResolver()
    config = make_config(total_call_budget=2)
    session = BoundedSession(config, spy)

    session.call("get_debug_status")
    session.call("get_cpu_state")
    session.call("step_into")  # 3rd call -- over budget, rejected

    ev = session.evidence()
    assert ev["total_calls_attempted"] == 3
    assert ev["total_calls_forwarded"] == 2
    assert ev["attempted_tool_names"] == ["get_debug_status", "get_cpu_state", "step_into"]
    assert ev["forwarded_tool_names"] == ["get_debug_status", "get_cpu_state"]
    assert ev["last_attempted_tool"] == "step_into"
    assert ev["termination"] == Termination.BUDGET_EXHAUSTED.value
    assert ev["rejection_reason"] is not None
    assert spy.call_count == 2


# ======================================================================
# Persistence round-trip (supports cross-process CLI use; not itself a
# required test, but exercises harness code the CLI entry point depends on)
# ======================================================================


def test_state_round_trip_preserves_enforcement():
    spy = SpyResolver()
    config = make_config(total_call_budget=2, execution_step_budget=1)
    session = BoundedSession(config, spy)
    session.call("get_debug_status")
    session.call("step_into")

    state = session.to_state_dict()
    restored = BoundedSession.from_state_dict(state, spy)

    assert restored.total_calls_forwarded == 2
    assert restored.execution_step_calls == 1
    assert restored.config.total_call_budget == 2

    # Budget continues to be enforced correctly after restoration.
    rejected = restored.call("get_debug_status")
    assert rejected["ok"] is False
    assert rejected["error"]["code"] == Termination.BUDGET_EXHAUSTED.value
    assert spy.call_count == 2
