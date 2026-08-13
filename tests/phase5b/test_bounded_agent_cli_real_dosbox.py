"""
Live integration test closing the B5-E enforcement audit's Property #5 gap
(docs/phase5b-b5e-enforcement-audit.md section 5, ai/Phase5E.md): proves the
complete, REAL production chain --

    BoundedSession -> _real_tool_resolver() -> tests/phase5a/agent_cli.py's
    registered tools -> ai/server_phase5a.py -> DOSBoxClient -> native AI
    bridge -> real DOSBox-X debugger/CPU

-- end to end, against a real, running DOSBox-X instance, not a fake/spy
resolver. tests/phase5b/test_bounded_agent_cli.py already establishes,
caller-independently, that BoundedSession's enforcement logic (forward-vs-
reject decision, exact-count budgeting, single termination) does not depend
on which resolver is injected -- this file's only job is to exercise that
SAME code path with the real one plugged in, and to independently observe
real DOSBox-X before and after, which no existing test does.

Requires a live DOSBox-X instance with the native AI bridge listening on
127.0.0.1:9876, launched exactly like tests/phase5a/test_harness_selftest.py
requires:

    dosbox-x.exe -break-start drive_c\\STEP.COM

(no stdout/stderr redirection). Every test in this file is skipped, not
failed, if the bridge is unreachable -- this is a live/integration test, not
part of the purely offline Phase 5B unit-test subset
(tests/phase5b/test_bounded_agent_cli.py, tests/phase5b/test_grading.py,
tests/phase5b/test_scenarios_config.py), same convention
tests/phase5a/test_harness_selftest.py already established for Phase 5A.

Startup-flake handling: reuses tests/phase5a/dosbox_session.py's existing
find_step_com_segment()/wait_for_stopped() polling (pause/continue/re-check
in a bounded retry loop) as the already-established setup policy for the
known `-break-start` startup flake -- the same mechanism every other live
Phase 4/5A test already relies on. If STEP.COM is never observed running,
that helper raises a clear AssertionError rather than silently retrying
past a genuine failure; this file does not add a second, separate retry
mechanism on top of it, and does not retry anything once the enforcement
sequence itself has started.

Budget choice (N=2): from LANDING_OFFSET (010C, "MOV AX,1111h"), the next
two instructions -- 010C and 010F ("MOV BX,2222h") -- are both ordinary,
non-CALL instructions, so two real step_into() calls land deterministically
on CALL_FUNC1_OFFSET (0112) without needing to resolve a CALL/RET boundary.
N=2 is the smallest budget that establishes a genuine N/N+1 boundary (at
least one real forwarded call, then a real rejected one) while keeping the
live sequence minimal, per ai/Phase5E.md's instruction not to reproduce B5's
historical six-step budget. This is independent of, and does not alter, the
approved B5 scenario configuration (ai/Phase5B-3.md) -- this test exercises
the identical BoundedSession enforcement code path with its own, smaller,
purpose-built budget.

Resolver-boundary instrumentation: `CountingResolver` below wraps the real
`bounded_agent_cli._real_tool_resolver()` -- the exact factory
`bounded_agent_cli.main()` uses in production -- purely to count
invocations; it delegates every call unchanged and does not reimplement any
Phase 5A tool logic. Combined with ai/server_phase5a.py's own independent
`get_call_log()` (a second, pre-existing, non-invasive observation point at
the recorded-tool-wrapper layer, one level closer to the native bridge than
the resolver itself), this gives two independent invocation counts, not
just `CallRecord.forwarded`, to prove N+1 never reached the real tool.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "ai"))

import pytest

import server_phase5a as s5a  # noqa: E402

from tests.phase5a import dosbox_session as ds  # noqa: E402
from tests.phase5b import bounded_agent_cli  # noqa: E402
from tests.phase5b.bounded_agent_cli import BoundedSession, BudgetConfig, Termination  # noqa: E402

pytestmark = pytest.mark.skipif(
    not ds.bridge_available(),
    reason=(
        f"native DOSBox-X AI bridge not reachable at {ds.HOST}:{ds.PORT} -- start "
        f"dosbox-x.exe -break-start drive_c\\STEP.COM (no stdout/stderr redirection) "
        f"before running this live B5-E integration test"
    ),
)


def is_hex(s, expected_len=None):
    if not isinstance(s, str):
        return False
    if expected_len is not None and len(s) != expected_len:
        return False
    try:
        int(s, 16)
        return True
    except ValueError:
        return False


class CountingResolver:
    """Wraps the real, production resolver -- observes/counts invocations
    only, delegates every permitted call unchanged. Not a fake/spy resolver
    in the sense tests/phase5b/test_bounded_agent_cli.py uses one (that file
    replaces the resolver entirely with a canned-response spy); this one
    forwards to the exact same real callable BoundedSession would otherwise
    call directly."""

    def __init__(self, real_resolver):
        self._real = real_resolver
        self.call_count = 0

    def __call__(self, name: str, args: dict):
        self.call_count += 1
        return self._real(name, args)


N = 2  # see module docstring "Budget choice"


def test_b5e_real_dosbox_execution_step_budget_enforcement():
    # -- 0. pre-test: bridge reachable, debugger genuinely stopped, starting
    #    from the intended live state (STEP.COM at LANDING_OFFSET). --
    cs = ds.find_step_com_segment()
    ds.clear_all_breakpoints()
    target = f"{cs}:{ds.LANDING_OFFSET}"
    bp = s5a.set_breakpoint(target)
    assert "error" not in bp, bp
    continued = s5a.continue_execution()
    assert "error" not in continued, continued
    landed = ds.wait_for_stopped(timeout=15.0)
    assert landed["location"] == {"cs": cs, "eip": ds.LANDING_OFFSET}, landed
    ds.clear_all_breakpoints()

    pre_status = s5a.verify.get_debug_status()
    assert "error" not in pre_status, pre_status
    assert pre_status["stopped"] is True, pre_status
    assert pre_status["location"] == {"cs": cs, "eip": ds.LANDING_OFFSET}, pre_status

    s5a.reset_call_log()  # clean slate for this test's own recorded-trace evidence

    # -- 1. the real production chain: BoundedSession -> _real_tool_resolver()
    #    -> tests/phase5a/agent_cli.py's registered tools ->
    #    ai/server_phase5a.py -> DOSBoxClient -> native AI bridge -> real
    #    DOSBox-X. Not a fake/spy resolver. --
    counting_resolver = CountingResolver(bounded_agent_cli._real_tool_resolver())
    config = BudgetConfig(
        total_call_budget=10,
        execution_step_budget=N,
        deadline_seconds=60.0,
        allowed_tools=frozenset({"step_into"}),
    )
    session = BoundedSession(config, counting_resolver)

    # -- 2. calls 1..N: attempted and forwarded, each a real guest step.
    #    (the REAL resolver returns ai/server_phase5a.py's raw tool result --
    #    a debug-status dict, or {"error": ...} on failure -- not the
    #    {"ok": ...} envelope tests/phase5b/test_bounded_agent_cli.py's
    #    SpyResolver invents for its own fake responses.) --
    for i in range(N):
        r = session.call("step_into")
        assert "error" not in r, r

    assert session.total_calls_attempted == N
    assert session.total_calls_forwarded == N
    assert session.execution_step_calls == N
    assert all(rec.forwarded for rec in session.records), session.records
    assert counting_resolver.call_count == N, "real resolver invocation count must equal exactly N after N permitted calls"
    assert len(s5a.get_call_log()) == N, "the real, recorded Phase 5A tool trace must independently show exactly N calls"
    assert not session.terminated

    # independent real-state proof the N forwarded calls genuinely advanced
    # real guest CPU state (010C -> 010F -> 0112), not a mock.
    mid_status = s5a.verify.get_debug_status()
    assert "error" not in mid_status, mid_status
    assert mid_status["location"] == {"cs": cs, "eip": ds.CALL_FUNC1_OFFSET}, mid_status

    resolver_count_before_reject = counting_resolver.call_count
    call_log_len_before_reject = len(s5a.get_call_log())

    # -- 3. call N+1: attempted, but must be rejected BEFORE reaching the
    #    real resolver / real tool / DOSBox-X. --
    rejected = session.call("step_into")

    assert session.total_calls_attempted == N + 1
    assert session.total_calls_forwarded == N
    assert rejected["ok"] is False
    assert rejected["error"]["code"] == Termination.BUDGET_EXHAUSTED.value
    assert session.termination == Termination.BUDGET_EXHAUSTED

    n_plus_1_record = session.records[-1]
    assert n_plus_1_record.tool == "step_into"
    assert n_plus_1_record.forwarded is False

    # necessary but not sufficient (per ai/Phase5E.md) -- corroborated below
    # by two independent real invocation counts.
    assert counting_resolver.call_count == resolver_count_before_reject, (
        "N+1 must not increase the real resolver's invocation count"
    )
    assert len(s5a.get_call_log()) == call_log_len_before_reject, (
        "N+1 must not increase the real, recorded Phase 5A tool trace either"
    )

    # -- 4. no call beyond the budget ever reaches the real resolver, even
    #    if the (already-terminated) session is attempted again. --
    further = session.call("step_into")
    assert further["ok"] is False
    assert further["error"]["code"] == Termination.BUDGET_EXHAUSTED.value
    assert session.termination == Termination.BUDGET_EXHAUSTED  # unchanged, not silently replaced
    assert counting_resolver.call_count == resolver_count_before_reject
    assert len(s5a.get_call_log()) == call_log_len_before_reject

    # -- 5. independent post-rejection coherence check. BoundedSession
    #    refuses all further calls once terminated (it never re-consults
    #    the resolver for those -- confirmed above), so this check goes
    #    straight to the real bridge, bypassing the terminated session
    #    entirely, exactly like ai/server_phase5a.py's own `verify`
    #    namespace is designed for. --
    post_status = s5a.verify.get_debug_status()
    assert "error" not in post_status, post_status
    assert post_status["stopped"] is True, post_status
    assert is_hex(post_status["location"]["cs"], 4), post_status
    assert is_hex(post_status["location"]["eip"], 4), post_status
    # rejection itself caused no further execution-state transition: still
    # exactly where the last FORWARDED step left it.
    assert post_status["location"] == {"cs": cs, "eip": ds.CALL_FUNC1_OFFSET}, post_status

    post_cpu = s5a.verify.get_cpu_state()
    assert "error" not in post_cpu, post_cpu
    for reg in ("eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp", "eflags"):
        assert is_hex(post_cpu.get(reg), 8), post_cpu
    for seg in ("cs", "ds", "es", "ss", "fs", "gs", "eip"):
        assert is_hex(post_cpu.get(seg), 4), post_cpu
    assert post_cpu["cs"] == cs, post_cpu
    assert post_cpu["eip"] == ds.CALL_FUNC1_OFFSET, post_cpu

    ds.clear_all_breakpoints()
