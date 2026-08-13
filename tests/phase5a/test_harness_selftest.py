"""
Phase 5A test-harness self-test.

Validates the GRADING MACHINERY itself (tests/phase5a/grading.py) against
real DOSBox-X state, before pointing any real agent at it: for each of the
5 scenarios in docs/phase5a-tool-awareness-design.md section 2, a small
scripted function stands in for "the agent" -- one version calls the
Phase 5A restricted tools (ai/server_phase5a.py) the way a correct agent
should, another deliberately violates one documented rule. Grading must
PASS the correct one and FAIL the incorrect one for every scenario;
otherwise the harness itself cannot be trusted to grade a real agent later.

This does NOT run an autonomous loop and does NOT involve any live LLM --
per ai/Phase5A.md ("目前不要實作 autonomous debugging loop"), that is
explicitly out of scope for this stage. The scripted stand-ins are fixed,
short Python functions, not an agent making its own decisions.

Two call paths matter here, and this file is careful to keep them separate:

  * `s5a.<tool>()` -- the RECORDED path (ai/server_phase5a.py's wrapped
    functions). Used only for calls meant to represent "what the
    agent-under-test did" -- these are what tests/phase5a/grading.py's
    checks are graded against, via `s5a.get_call_log()`.
  * `s5a.verify.<tool>()` -- the UNRECORDED path, for this file's OWN
    before/after ground-truth snapshots and scenario setup/positioning.
    These must never appear in the graded trace, or a scenario's own
    bookkeeping would corrupt what's being graded.

Session layout (three separate live DOSBox-X launches, exactly like the
existing Phase 4 test files already require of the human/CI runner --
`-break-start drive_c\\STEP.COM` / `drive_c\\TEST.COM`, no stdout/stderr
redirection per ai/Phase4E-2.md):

    STEP-A (drive_c/STEP.COM, first launch)
        test_step_a_01 .. test_step_a_06

    STEP-B (drive_c/STEP.COM, SECOND, fresh launch)
        test_step_b_01 .. test_step_b_02

    TEST   (drive_c/TEST.COM launch)
        test_scenario_4* / test_scenario_5*

Two separate STEP.COM launches are required because STEP.COM's control flow
is strictly linear/forward within one run (see
tests/test_step_execution.py's module docstring: "there is no way to
're-land' on an already-passed instruction") and it has exactly two CALL
instructions -- not enough to exercise all four
{into,over} x {correct,wrong} combinations for Scenario 3 in a single run.
STEP-A walks forward through both CALLs taking the CORRECT branch each
time; STEP-B (a fresh process, so LANDING_OFFSET is reachable again) walks
forward through both CALLs taking the WRONG branch each time. Within each
group, tests rely on pytest's default file-order execution and must not be
reordered, exactly like tests/test_step_execution.py.

TEST.COM's busy loop does not have this constraint (it loops for a very
long time before actually exiting, so it stays "in the loop" for the
duration of this file's TEST group and can be safely re-caught by
find_test_com_segment() as many times as needed) -- the Scenario 4/5 tests
below are independent of each other, in any order.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "ai"))

import pytest

import server_phase5a as s5a  # noqa: E402

from tests.phase5a import dosbox_session as ds  # noqa: E402
from tests.phase5a import grading  # noqa: E402

pytestmark = pytest.mark.skipif(
    not ds.bridge_available(),
    reason=(
        f"native DOSBox-X AI bridge not reachable at {ds.HOST}:{ds.PORT} -- start "
        f"dosbox-x.exe -break-start drive_c\\STEP.COM or drive_c\\TEST.COM (no "
        f"stdout/stderr redirection) before running this harness self-test"
    ),
)


# ======================================================================
# STEP-A: first STEP.COM launch -- correct-agent branch throughout.
# Forward walk: 010C -> (no move) -> 010F -> 0112(CALL1) -> 0122(in func1)
#               -> 0125 -> 0115 -> 0118(CALL2) -> 011B
# Do not reorder -- see module docstring.
# ======================================================================


def test_step_a_01_scenario1_correct_agent_passes():
    # land at LANDING_OFFSET fresh (first landing this session)
    cs = ds.find_step_com_segment()
    ds.clear_all_breakpoints()
    target = f"{cs}:{ds.LANDING_OFFSET}"
    bp = s5a.set_breakpoint(target)
    assert "error" not in bp, bp
    continued = s5a.continue_execution()
    assert "error" not in continued, continued
    status = ds.wait_for_stopped(timeout=15.0)
    assert status["location"] == {"cs": cs, "eip": ds.LANDING_OFFSET}, status
    ds.clear_all_breakpoints()

    before = s5a.verify.get_debug_status()
    s5a.reset_call_log()

    # -- simulated correct agent: pure inspection --
    status = s5a.get_debug_status()
    cs_reported, eip_reported = status["location"]["cs"], status["location"]["eip"]

    after = s5a.verify.get_debug_status()
    result = grading.grade_scenario_1(s5a.get_call_log(), before, after, cs_reported, eip_reported)
    assert result.passed, result.reasons


def test_step_a_02_scenario2_correct_agent_passes():
    # still at LANDING_OFFSET -- scenario 1 above was read-only, no move.
    before = s5a.verify.get_debug_status()
    s5a.reset_call_log()

    # -- simulated correct agent: reads the instruction, does not execute --
    instr = s5a.get_current_instruction()
    mnemonic = instr["instruction"]

    after = s5a.verify.get_debug_status()
    result = grading.grade_scenario_2(s5a.get_call_log(), before, after, mnemonic)
    assert result.passed, result.reasons


def test_step_a_03_scenario1_wrong_agent_fails():
    # still at LANDING_OFFSET (010C). This test consumes one forward step.
    before = s5a.verify.get_debug_status()
    assert before["location"]["eip"] == ds.LANDING_OFFSET, before
    s5a.reset_call_log()

    # -- simulated wrong agent: inspects, then also executes (prohibited) --
    status = s5a.get_debug_status()
    cs_reported, eip_reported = status["location"]["cs"], status["location"]["eip"]
    s5a.step_into()

    after = s5a.verify.get_debug_status()
    assert after["location"]["eip"] == ds.AFTER_A_OFFSET, after  # 010C -> 010F

    result = grading.grade_scenario_1(s5a.get_call_log(), before, after, cs_reported, eip_reported)
    assert not result.passed, "grading should have caught the prohibited step_into() call"


def test_step_a_04_scenario2_wrong_agent_fails():
    # now at 010F. This test consumes the next forward step, landing on CALL func1.
    before = s5a.verify.get_debug_status()
    assert before["location"]["eip"] == ds.AFTER_A_OFFSET, before
    s5a.reset_call_log()

    # -- simulated wrong agent: executes instead of just reading --
    result_step = s5a.step_into()
    mnemonic = result_step["instruction"]["text"]

    after = s5a.verify.get_debug_status()
    assert after["location"]["eip"] == ds.CALL_FUNC1_OFFSET, after  # 010F -> 0112

    result = grading.grade_scenario_2(s5a.get_call_log(), before, after, mnemonic)
    assert not result.passed, "grading should have caught execution during an identification-only task"


def test_step_a_05_scenario3_into_correct_agent_passes():
    # now at CALL_FUNC1_OFFSET (0112).
    before = s5a.verify.get_debug_status()
    assert before["location"]["eip"] == ds.CALL_FUNC1_OFFSET, before
    s5a.reset_call_log()

    # -- simulated correct agent: "see inside" -> step_into --
    after = s5a.step_into()

    result = grading.grade_scenario_3_exact(
        s5a.get_call_log(), "into", before, after, ds.FUNC1_ENTRY_OFFSET
    )
    assert result.passed, result.reasons


def test_step_a_06_scenario3_over_correct_agent_passes():
    # now inside func1 (0122). Walk forward (setup only, not graded) through
    # func1's own instruction and RET, back to the caller, to reach CALL func2.
    status = s5a.verify.get_debug_status()
    assert status["location"]["eip"] == ds.FUNC1_ENTRY_OFFSET, status
    status = s5a.step_into()  # executes MOV DX,4444h -> RET (0125)
    status = s5a.step_into()  # executes RET -> back at 0115
    assert status["location"]["eip"] == "0115", status
    status = s5a.step_into()  # executes MOV CX,3333h -> CALL func2 (0118)
    assert status["location"]["eip"] == ds.CALL_FUNC2_OFFSET, status

    before = status
    s5a.reset_call_log()

    # -- simulated correct agent: "skip internals" -> step_over --
    after = s5a.step_over()

    result = grading.grade_scenario_3_exact(
        s5a.get_call_log(), "over", before, after, ds.AFTER_CALL_FUNC2_OFFSET
    )
    assert result.passed, result.reasons
    # independent proof the callee genuinely ran (Phase4E-established side effect)
    assert after["registers"]["edi"][-4:] == "6666", after


# ======================================================================
# STEP-B: SECOND, fresh STEP.COM launch -- wrong-agent branch throughout.
# Forward walk: 010C -> 010F -> 0112(CALL1) -> 0115 -> 0118(CALL2) -> 0126
# Do not reorder -- see module docstring.
# ======================================================================


def test_step_b_01_scenario3_into_wrong_agent_fails():
    cs = ds.find_step_com_segment()
    ds.clear_all_breakpoints()
    target = f"{cs}:{ds.LANDING_OFFSET}"
    bp = s5a.set_breakpoint(target)
    assert "error" not in bp, bp
    continued = s5a.continue_execution()
    assert "error" not in continued, continued
    status = ds.wait_for_stopped(timeout=15.0)
    assert status["location"] == {"cs": cs, "eip": ds.LANDING_OFFSET}, status
    ds.clear_all_breakpoints()

    status = s5a.step_into()  # setup: 010C -> 010F
    status = s5a.step_into()  # setup: 010F -> 0112 (CALL func1)
    assert status["location"]["eip"] == ds.CALL_FUNC1_OFFSET, status

    before = status
    s5a.reset_call_log()

    # -- simulated wrong agent: "see inside" task, but calls step_over --
    after = s5a.step_over()

    result = grading.grade_scenario_3_exact(
        s5a.get_call_log(), "into", before, after, ds.FUNC1_ENTRY_OFFSET
    )
    assert not result.passed, "grading should have caught step_over used for an 'into' task"


def test_step_b_02_scenario3_over_wrong_agent_fails():
    # now past CALL func1 (0115, since STEP-B's step_over just executed it for real).
    status = s5a.verify.get_debug_status()
    assert status["location"]["eip"] == "0115", status
    status = s5a.step_into()  # setup: 0115 -> 0118 (CALL func2)
    assert status["location"]["eip"] == ds.CALL_FUNC2_OFFSET, status

    before = status
    s5a.reset_call_log()

    # -- simulated wrong agent: "skip internals" task, but calls step_into --
    after = s5a.step_into()

    result = grading.grade_scenario_3_exact(
        s5a.get_call_log(), "over", before, after, ds.AFTER_CALL_FUNC2_OFFSET
    )
    assert not result.passed, "grading should have caught step_into used for an 'over' task"


# ======================================================================
# Scenario 4 -- breakpoint investigation (TEST.COM; independent, any order)
# ======================================================================


def test_scenario_4a_correct_agent_passes():
    cs = ds.find_test_com_segment()
    ds.clear_all_breakpoints()
    target = f"{cs}:{ds.TEST_COM_LOOP_OFFSET}"
    s5a.reset_call_log()

    # -- simulated correct agent: set a breakpoint, then continue --
    s5a.set_breakpoint(target)
    s5a.continue_execution()

    final_status = ds.wait_for_stopped(timeout=5.0)
    bp_existed = any(b["address"] == target for b in s5a.verify.list_breakpoints())

    result = grading.grade_scenario_4_set_and_hit(s5a.get_call_log(), target, bp_existed, final_status)
    assert result.passed, result.reasons
    ds.clear_all_breakpoints()


def test_scenario_4a_wrong_agent_fails():
    cs = ds.find_test_com_segment()
    ds.clear_all_breakpoints()
    target = f"{cs}:{ds.TEST_COM_LOOP_OFFSET}"
    s5a.reset_call_log()

    # -- simulated wrong agent: walks with step_into instead of a breakpoint --
    for _ in range(3):
        s5a.step_into()

    final_status = s5a.verify.get_debug_status()

    result = grading.grade_scenario_4_set_and_hit(s5a.get_call_log(), target, False, final_status)
    assert not result.passed, "grading should have caught stepping used instead of a breakpoint"
    ds.clear_all_breakpoints()


def test_scenario_4b_correct_agent_passes():
    ds.find_test_com_segment()
    ds.clear_all_breakpoints()
    s5a.set_breakpoint("1234:0200")  # harness's own pre-existing breakpoint
    before_status = s5a.verify.get_debug_status()
    before_bps = s5a.verify.list_breakpoints()
    s5a.reset_call_log()

    # -- simulated correct agent: only lists, never mutates --
    s5a.list_breakpoints()

    after_status = s5a.verify.get_debug_status()
    after_bps = s5a.verify.list_breakpoints()
    result = grading.grade_scenario_4_list_only(s5a.get_call_log(), before_status, after_status, before_bps, after_bps)
    assert result.passed, result.reasons
    ds.clear_all_breakpoints()


def test_scenario_4b_wrong_agent_fails():
    ds.find_test_com_segment()
    ds.clear_all_breakpoints()
    s5a.set_breakpoint("1234:0200")
    before_status = s5a.verify.get_debug_status()
    before_bps = s5a.verify.list_breakpoints()
    s5a.reset_call_log()

    # -- simulated wrong agent: adds a breakpoint nobody asked for --
    s5a.set_breakpoint("1234:0100")
    s5a.list_breakpoints()

    after_status = s5a.verify.get_debug_status()
    after_bps = s5a.verify.list_breakpoints()
    result = grading.grade_scenario_4_list_only(s5a.get_call_log(), before_status, after_status, before_bps, after_bps)
    assert not result.passed, "grading should have caught an unrequested set_breakpoint mutating the list"
    ds.clear_all_breakpoints()


# ======================================================================
# Scenario 5 -- running/stopped state awareness (TEST.COM; independent, any order)
# ======================================================================


def test_scenario_5_running_correct_agent_passes():
    ds.find_test_com_segment()
    before = s5a.verify.get_debug_status()
    continued = s5a.continue_execution()
    assert "error" not in continued, continued
    s5a.reset_call_log()

    # -- simulated correct agent: check state, THEN pause (since running) --
    status = s5a.get_debug_status()
    if status["running"]:
        s5a.pause_execution()

    after = s5a.verify.get_debug_status()
    result = grading.grade_scenario_5(s5a.get_call_log(), "running", before, after)
    assert result.passed, result.reasons


def test_scenario_5_running_wrong_agent_fails():
    ds.find_test_com_segment()
    before = s5a.verify.get_debug_status()
    continued = s5a.continue_execution()
    assert "error" not in continued, continued
    s5a.reset_call_log()

    # -- simulated wrong agent: pauses without ever checking state first --
    s5a.pause_execution()

    after = s5a.verify.get_debug_status()
    result = grading.grade_scenario_5(s5a.get_call_log(), "running", before, after)
    assert not result.passed, "grading should have caught pause_execution called before checking state"


def test_scenario_5_stopped_correct_agent_passes():
    ds.find_test_com_segment()
    before = s5a.verify.get_debug_status()
    assert before["stopped"] is True
    s5a.reset_call_log()

    # -- simulated correct agent: check state, see stopped, do nothing further --
    status = s5a.get_debug_status()
    if status["running"]:
        s5a.pause_execution()  # should not happen -- already stopped

    after = s5a.verify.get_debug_status()
    result = grading.grade_scenario_5(s5a.get_call_log(), "stopped", before, after)
    assert result.passed, result.reasons


def test_scenario_5_stopped_wrong_agent_fails():
    ds.find_test_com_segment()
    before = s5a.verify.get_debug_status()
    assert before["stopped"] is True
    s5a.reset_call_log()

    # -- simulated wrong agent: pauses while already stopped, no check --
    s5a.pause_execution()

    after = s5a.verify.get_debug_status()
    result = grading.grade_scenario_5(s5a.get_call_log(), "stopped", before, after)
    assert not result.passed, "grading should have caught pause_execution called while already stopped"
