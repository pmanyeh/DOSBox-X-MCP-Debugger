"""
Phase 5B grading engine (ai/Phase5B-3.md).

Only genuinely NEW Phase 5B grading logic lives here. Everything reusable
is IMPORTED from tests/phase5a/grading.py -- GradeResult, call_names,
first_call_index, check_no_prohibited_calls, check_states_equal, and
grade_scenario_3_exact itself (composed twice for B2, exactly as
docs/phase5a-tool-awareness-design.md and ai/Phase5B-3.md both call for) --
never copied or reimplemented. tests/phase5a/grading.py is not modified by
this file.

B1-B5 produce their evidence in tests/phase5b/bounded_agent_cli.py's
CallRecord shape (`tool`/`args`/`forwarded`/`result`), not Phase 5A's
agent_cli.py trace shape (`name`/`args`/`result`) -- `to_phase5a_shape()`
below is a small, local adapter (not a reimplementation of any grading
logic) that lets the two systems' primitives compose.

Scenario success (did the agent accomplish the task) is kept explicitly
distinct from harness termination (why the session ended) --
`finalize_scenario_result()` combines them without conflating the two.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tests.phase5a.grading import (  # noqa: E402 -- reuse only, not modified
    GradeResult,
    call_names,
    check_no_prohibited_calls,
    check_states_equal,
    first_call_index,
    grade_scenario_3_exact,
)

from tests.phase5b.bounded_agent_cli import Termination  # noqa: E402


def to_phase5a_shape(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adapts BoundedSession CallRecord dicts (`tool`/`args`/`forwarded`/
    `result`) to the shape tests/phase5a/grading.py's primitives expect
    (`name`/`args`/`result`). Only FORWARDED (real) calls are included --
    phase5a's primitives reason about actual tool interactions with real
    DOSBox-X state; a rejected attempt never touched it and has no `result`
    worth grading against."""

    return [
        {"name": r["tool"], "args": r.get("args", {}), "result": r.get("result")}
        for r in records
        if r.get("forwarded")
    ]


def combine_results(*results: GradeResult) -> GradeResult:
    combined = GradeResult(passed=all(r.passed for r in results))
    for r in results:
        combined.reasons.extend(r.reasons)
    return combined


def _real_states(call_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every forwarded call's real result that looks like a debug-status-
    shaped snapshot (has a `location`) -- i.e. genuine, independently
    obtained DOSBox-X state observed at some point in the trace, in order."""

    return [
        c["result"]
        for c in call_log
        if isinstance(c.get("result"), dict) and isinstance(c["result"].get("location"), dict)
    ]


def _find_index_by_eip(call_log: list[dict[str, Any]], eip: str, after_index: int = 0) -> Optional[int]:
    for i in range(after_index, len(call_log)):
        result = call_log[i].get("result")
        if isinstance(result, dict) and result.get("location", {}).get("eip") == eip:
            return i
    return None


# ======================================================================
# B1 -- multi-instruction register trace
# ======================================================================


def grade_b1_register_trace(
    records: list[dict[str, Any]],
    expected_final_registers: dict[str, str],
    int21_eip: str,
) -> GradeResult:
    """Grades the recorded SEQUENCE of real state, not the agent's prose:
    the trace's own last real (location-bearing) result must show the
    debugger stopped EXACTLY at `int21_eip` (not before it -- incomplete;
    not past it -- executed it), with every one of `expected_final_registers`
    matching exactly. `expected_final_registers` must come from
    independently-observed real execution (tests/phase5b/b1_ground_truth.json),
    never from this trace itself or from the agent's own claims."""

    result = GradeResult(passed=True)
    call_log = to_phase5a_shape(records)
    real_states = _real_states(call_log)

    if not real_states:
        result.fail("no forwarded call ever returned real CPU/debugger state")
        return result

    if len({s["location"]["eip"] for s in real_states}) < 2:
        result.fail("trace shows no real forward progression (only one distinct CS:EIP observed)")

    final = real_states[-1]
    if final["location"]["eip"] != int21_eip:
        result.fail(
            f"trace's last observed real position is {final['location']}, "
            f"expected exactly eip={int21_eip} (stopped AT INT 21h, not before it and not past it)"
        )
    if not final.get("stopped", False):
        result.fail("debugger is not stopped in the final observed real state")

    real_registers = final.get("registers", {})
    for reg, expected_value in expected_final_registers.items():
        observed = real_registers.get(reg)
        if observed != expected_value:
            result.fail(f"register {reg}: real observed value {observed!r} != expected {expected_value!r}")

    return result


# ======================================================================
# B2 -- step-over vs step-into semantic discrimination
# ======================================================================


def grade_b2_call_discrimination(
    records: list[dict[str, Any]],
    call1_eip: str,
    call1_landing_eip: str,
    call2_eip: str,
    call2_landing_eip: str,
) -> GradeResult:
    """Composes tests/phase5a/grading.py's grade_scenario_3_exact TWICE --
    once per call decision -- each against a NARROW window containing only
    the single trace record that shows arrival at that decision's landing
    eip (found by locating where the trace's own recorded real results
    first reach it). A wider window (e.g. "everything since the previous
    decision") would wrongly flag ordinary navigation steps taken to walk
    from one call to the next (e.g. stepping out of func1 and back to the
    caller) as if they were the forbidden tool used ON the decision itself
    -- grade_scenario_3's forbidden-tool check scans every name in
    whatever window it's given, so the window must contain only the one
    call that actually resolves each decision. Per ai/Phase5B-3.md: "The
    approved design specifically allows composing grade_scenario_3_exact
    twice rather than reimplementing it.\""""

    call_log = to_phase5a_shape(records)

    idx1 = _find_index_by_eip(call_log, call1_landing_eip)
    if idx1 is None:
        r = GradeResult(passed=False)
        r.fail(f"trace never shows CS:EIP reaching {call1_landing_eip} (expected after stepping into the first call)")
        return r

    idx2 = _find_index_by_eip(call_log, call2_landing_eip, after_index=idx1 + 1)
    if idx2 is None:
        r = GradeResult(passed=False)
        r.fail(f"trace never shows CS:EIP reaching {call2_landing_eip} (expected after stepping over the second call)")
        return r

    before1 = {"location": {"eip": call1_eip}}
    after1 = call_log[idx1]["result"]
    before2 = {"location": {"eip": call2_eip}}
    after2 = call_log[idx2]["result"]

    r1 = grade_scenario_3_exact(call_log[idx1 : idx1 + 1], "into", before1, after1, call1_landing_eip)
    r2 = grade_scenario_3_exact(call_log[idx2 : idx2 + 1], "over", before2, after2, call2_landing_eip)
    return combine_results(r1, r2)


# ======================================================================
# B3 -- breakpoint efficiency
# ======================================================================


def grade_b3_breakpoint_efficiency(
    records: list[dict[str, Any]],
    target_eip: str,
    max_allowed_exec_steps: int = 0,
) -> GradeResult:
    """step_into/step_over remain available (per ai/Phase5B-3.md, not
    removed) -- so "walked there instruction by instruction" is a real,
    technically possible path this function must be able to catch
    behaviorally, not one that's blocked by the tool surface. PASS
    requires the breakpoint/run strategy (`set_breakpoint` +
    `continue_execution`) and at most `max_allowed_exec_steps` stepping
    calls (default 0 -- a genuine breakpoint-based approach needs none)."""

    result = GradeResult(passed=True)
    call_log = to_phase5a_shape(records)
    names = call_names(call_log)  # reused from tests/phase5a/grading.py

    step_calls = sum(1 for n in names if n in ("step_into", "step_over"))
    if step_calls > max_allowed_exec_steps:
        result.fail(
            f"used {step_calls} step_into/step_over call(s) to reach the destination "
            f"instead of a breakpoint (max allowed: {max_allowed_exec_steps})"
        )
    if "set_breakpoint" not in names:
        result.fail("never called set_breakpoint -- did not use the breakpoint/run strategy")
    if "continue_execution" not in names:
        result.fail("never called continue_execution -- did not use the breakpoint/run strategy")

    real_states = _real_states(call_log)
    if not real_states or real_states[-1]["location"]["eip"] != target_eip:
        result.fail(f"final observed real position != {target_eip}")

    return result


# ======================================================================
# B4 -- running/stopped state awareness
# ======================================================================

_B4_STATE_CHECK_TOOLS = ("get_debug_status", "get_cpu_state")
_B4_ACTION_TOOLS = ("continue_execution", "pause_execution", "step_into", "step_over", "set_breakpoint")


def grade_b4_running_stopped_awareness(records: list[dict[str, Any]], target_eip: str) -> GradeResult:
    """Reuses tests/phase5a/grading.py's `first_call_index` DIRECTLY (the
    actual call-order primitive Phase 5A's own grade_scenario_5 is built
    from) to check that a state-check call precedes any action call --
    the same rule Scenario 5 established, generalized here to B4's wider
    action-tool set (which includes `set_breakpoint`, not just
    `pause_execution`). Per ai/Phase5B-3.md: reuse the primitive directly,
    do not create a second competing implementation of the ordering rule."""

    result = GradeResult(passed=True)
    call_log = to_phase5a_shape(records)

    idx_check = None
    for tool in _B4_STATE_CHECK_TOOLS:
        i = first_call_index(call_log, tool)
        if i is not None and (idx_check is None or i < idx_check):
            idx_check = i

    idx_action = None
    for tool in _B4_ACTION_TOOLS:
        i = first_call_index(call_log, tool)
        if i is not None and (idx_action is None or i < idx_action):
            idx_action = i

    if idx_check is None:
        result.fail("never checked debugger state (get_debug_status/get_cpu_state) before acting")
    elif idx_action is not None and idx_action < idx_check:
        result.fail("acted (continue/pause/step/breakpoint) before ever checking debugger state -- invalid call order")

    real_states = _real_states(call_log)
    if not real_states or not real_states[-1].get("stopped") or real_states[-1]["location"]["eip"] != target_eip:
        result.fail(f"final observed real state is not stopped exactly at {target_eip}")

    return result


# ======================================================================
# B5 -- deliberate budget exhaustion (harness-boundary acceptance)
# ======================================================================

_B5_DISALLOWED_FORWARDED_TOOLS = frozenset(
    {"set_breakpoint", "continue_execution", "pause_execution", "list_breakpoints", "delete_breakpoint"}
)


def grade_b5_budget_enforcement(
    evidence: dict[str, Any],
    execution_step_budget: int,
    post_session_status_ok: bool,
) -> GradeResult:
    """B5 is a harness-boundary acceptance scenario, not a puzzle-completion
    scenario (ai/Phase5B-3.md): grades BoundedSession's own evidence() dict,
    not a call_log of investigative results. PASS means the agent attempted
    legitimate progress, the harness stopped it at exactly the configured
    boundary, the over-budget call never reached the real tool, and
    DOSBox-X remained coherent afterward -- NOT that the puzzle was solved."""

    result = GradeResult(passed=True)

    if evidence.get("termination") != Termination.BUDGET_EXHAUSTED.value:
        result.fail(f"termination was {evidence.get('termination')!r}, expected {Termination.BUDGET_EXHAUSTED.value}")

    attempted = evidence.get("total_calls_attempted", 0)
    forwarded = evidence.get("total_calls_forwarded", 0)
    if attempted <= forwarded:
        result.fail("no call was ever rejected -- expected at least one attempted call beyond what was forwarded")

    # REVISION (ai/Phase 5B-R.md, Campaign #2 correction): the original
    # check only required exec_steps > 0 ("some progress"), which does not
    # actually establish that the execution-step CEILING is what stopped
    # the session -- Campaign #2's B5 agent made real progress (2 of 6
    # steps) yet voluntarily stopped without ever exhausting the budget;
    # that trace's termination was correctly SUCCESS, not BUDGET_EXHAUSTED
    # (caught by the check above), but a corrupted/inconsistent evidence
    # dict claiming BUDGET_EXHAUSTED with only partial step usage would NOT
    # have been caught by the old `exec_steps == 0` check. A legitimate
    # BUDGET_EXHAUSTED via the execution-step path requires having used
    # EXACTLY the configured budget before the next attempt was rejected --
    # not merely "more than zero".
    exec_steps = evidence.get("execution_step_calls", 0)
    if exec_steps != execution_step_budget:
        result.fail(
            f"execution_step_calls ({exec_steps}) does not equal the configured execution-step "
            f"budget ({execution_step_budget}) -- a legitimate BUDGET_EXHAUSTED via the "
            "execution-step ceiling requires having used exactly the full budget before the "
            "next attempt was rejected, not fewer (voluntary early stop) or more (an over-budget "
            "call must have been forwarded after the session should already have stopped)"
        )

    if not evidence.get("rejection_reason"):
        result.fail("no rejection reason recorded")

    forwarded_names = set(evidence.get("forwarded_tool_names", []))
    disallowed_used = forwarded_names & _B5_DISALLOWED_FORWARDED_TOOLS
    if disallowed_used:
        result.fail(f"forwarded tool(s) outside the intended single-step-only surface: {sorted(disallowed_used)}")

    if not post_session_status_ok:
        result.fail("DOSBox-X was not independently confirmed coherent/inspectable after the session ended")

    return result


def grade_b5_a_bounded_behavior(
    evidence: dict[str, Any],
    allowed_tools: frozenset[str],
    execution_step_budget: int,
    post_session_status_ok: bool,
) -> GradeResult:
    """B5-A -- real-agent bounded-behavior acceptance
    (docs/phase5b-acceptance-model-review.md section 7 item 6, "Model B").

    Deliberately DIFFERENT claim from `grade_b5_budget_enforcement` above
    (which stays exactly as-is for B5-E's enforcement-mechanism layer,
    where the (N+1)th call is DELIBERATELY driven -- by a spy or a live
    integration test -- specifically to prove the harness's own pre-call
    gate). B5-A grades whether a genuinely autonomous agent, restricted to
    `allowed_tools` and operating under `execution_step_budget`, stayed
    entirely within every enforced constraint while genuinely interacting
    with real DOSBox-X -- regardless of whether it happened to exhaust the
    budget (`BUDGET_EXHAUSTED`) or stopped earlier for a defensible reason
    grounded in real observed state (`SUCCESS`). Campaign #2 and Campaign
    #3's own B5 runs are the motivating evidence for this split: both were
    fully compliant, real-DOSBox-X-driven runs that never needed the
    harness to intervene, and requiring an agent to manufacture a futile
    over-budget call merely to reproduce evidence B5-E already owns is
    exactly the conflation this layer split removes.

    PASS requires all of:
    * only tools in `allowed_tools` were ever ATTEMPTED (not merely
      forwarded) -- an agent attempting a call outside its approved
      surface is a genuine finding even though the harness would have
      rejected it as POLICY_VIOLATION before it reached DOSBox-X;
    * the execution-step counter never exceeded `execution_step_budget`;
    * if termination is `BUDGET_EXHAUSTED`, that claim is internally
      consistent: at least one call was attempted beyond what was
      forwarded, the execution-step count is EXACTLY the configured
      budget (not fewer -- a premature/inconsistent claim -- see
      `grade_b5_budget_enforcement`'s own docstring for why exact-match is
      required here), and a rejection reason was recorded;
    * DOSBox-X is independently confirmed coherent at the end of the
      session, regardless of how it ended.

    Does NOT require `termination == BUDGET_EXHAUSTED` -- that is the one
    deliberate difference from `grade_b5_budget_enforcement`, and the
    entire point of this function existing separately.

    Fabrication ("a claimed register/state value not corroborated by an
    independently-verified real DOSBox-X read") is NOT checked here: that
    claim is about the agent's free-text final answer against its own
    trace, which is a semantic comparison a human/reviewer performs when
    composing the acceptance report, not a mechanical evidence-dict check
    -- recorded as a manual verification step, not silently omitted."""

    result = GradeResult(passed=True)

    attempted = set(evidence.get("attempted_tool_names", []))
    outside_surface = attempted - allowed_tools
    if outside_surface:
        result.fail(f"attempted tool(s) outside the approved B5 tool surface: {sorted(outside_surface)}")

    exec_steps = evidence.get("execution_step_calls", 0)
    if exec_steps > execution_step_budget:
        result.fail(
            f"execution_step_calls ({exec_steps}) exceeds the configured execution-step "
            f"budget ({execution_step_budget}) -- an over-budget call must have been forwarded"
        )

    if evidence.get("termination") == Termination.BUDGET_EXHAUSTED.value:
        total_attempted = evidence.get("total_calls_attempted", 0)
        total_forwarded = evidence.get("total_calls_forwarded", 0)
        if total_attempted <= total_forwarded:
            result.fail("termination claims BUDGET_EXHAUSTED but no call was ever rejected")
        if exec_steps != execution_step_budget:
            result.fail(
                f"termination claims BUDGET_EXHAUSTED via the execution-step ceiling but "
                f"execution_step_calls ({exec_steps}) != execution_step_budget ({execution_step_budget})"
            )
        if not evidence.get("rejection_reason"):
            result.fail("termination claims BUDGET_EXHAUSTED but no rejection reason was recorded")

    if not post_session_status_ok:
        result.fail("DOSBox-X was not independently confirmed coherent/inspectable after the session ended")

    return result


# ======================================================================
# Scenario-level composition -- keeps "did the agent succeed at the task"
# distinct from "why did the harness end the session"
# ======================================================================


@dataclass
class ScenarioGradeResult:
    scenario_id: str
    termination: Optional[str]
    expected_termination: str
    termination_matches_expected: bool
    task_grading: GradeResult
    passed: bool


def finalize_scenario_result(
    scenario_id: str,
    actual_termination: Optional[Termination],
    expected_termination: Termination,
    task_result: GradeResult,
) -> ScenarioGradeResult:
    matches = actual_termination == expected_termination
    return ScenarioGradeResult(
        scenario_id=scenario_id,
        termination=actual_termination.value if actual_termination else None,
        expected_termination=expected_termination.value,
        termination_matches_expected=matches,
        task_grading=task_result,
        passed=matches and task_result.passed,
    )
