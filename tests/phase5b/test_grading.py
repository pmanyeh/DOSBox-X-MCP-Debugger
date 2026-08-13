"""
Deterministic grader tests for Phase 5B's B1-B5 scenarios (ai/Phase5B-3.md).

These exercise tests/phase5b/grading.py against synthetic/known traces --
no live DOSBox-X, no real agent -- proving the GRADING LOGIC itself is
correct before any real agent is ever pointed at it. For each scenario: at
least one known-good trace must PASS, and at least one known-bad trace
(the specific negative cases ai/Phase5B-3.md calls out) must FAIL.

B1's expected register values are loaded directly from
tests/phase5b/b1_ground_truth.json -- the live-captured evidence file --
not retyped by hand, so the "known-good" trace is graded against the same
values DOSBox-X actually produced.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.phase5b import grading  # noqa: E402
from tests.phase5b.bounded_agent_cli import Termination  # noqa: E402

_GROUND_TRUTH_PATH = Path(__file__).resolve().parent / "b1_ground_truth.json"
_GROUND_TRUTH = json.loads(_GROUND_TRUTH_PATH.read_text(encoding="utf-8"))


def rec(tool, eip, registers, stopped=True, forwarded=True, args=None):
    """Builds one synthetic BoundedSession CallRecord-shaped dict with a
    real-debug-status-shaped result, matching what tests/phase5b's
    grading functions consume."""

    return {
        "tool": tool,
        "args": args or {},
        "forwarded": forwarded,
        "result": {
            "stopped": stopped,
            "running": not stopped,
            "location": {"cs": "0816", "eip": eip},
            "instruction": {"bytes": "", "text": ""},
            "registers": registers,
        },
    }


def bare(tool, args=None):
    """A forwarded call whose result carries no location (e.g. list_breakpoints)."""
    return {"tool": tool, "args": args or {}, "forwarded": True, "result": {}}


REGS0 = {"eax": "00000000", "ebx": "00000000", "ecx": "00000000", "edx": "00000816", "esi": "00000100", "edi": "0000FFFE", "ebp": "0000091C", "esp": "0000FFFE"}


# ======================================================================
# B1 -- multi-instruction register trace
# ======================================================================


def _b1_expected_registers():
    final = _GROUND_TRUTH["final_status_stopped_before_int21"]["registers"]
    return {k: final[k] for k in ("eax", "ebx", "ecx", "edx", "esi", "edi")}


def test_b1_known_good_trace_passes():
    truth = _GROUND_TRUTH["trace"]
    records = [
        rec("get_debug_status", truth[0]["eip"], truth[0]["registers"]),
        *[rec("step_into", step["eip"], step["registers"]) for step in truth[1:]],
    ]
    result = grading.grade_b1_register_trace(records, _b1_expected_registers(), int21_eip="0120")
    assert result.passed, result.reasons


def test_b1_incorrect_ax_handling_after_mov_ah_4c_fails():
    # The specific semantic trap: a grader (or agent) that naively assumes
    # AX is untouched (still 00001111) instead of deriving the real
    # AH-only overwrite (00004C11) must be caught.
    truth = _GROUND_TRUTH["trace"]
    records = [
        rec("get_debug_status", truth[0]["eip"], truth[0]["registers"]),
        *[rec("step_into", step["eip"], step["registers"]) for step in truth[1:-1]],
        rec("step_into", "0120", {**truth[-1]["registers"], "eax": "00001111"}),  # WRONG: naive AX
    ]
    expected = _b1_expected_registers()
    assert expected["eax"] == "00004C11"  # sanity: ground truth really is the AH-preserves-AL value
    result = grading.grade_b1_register_trace(records, expected, int21_eip="0120")
    assert not result.passed
    assert any("eax" in reason for reason in result.reasons)


def test_b1_executed_int21_instead_of_stopping_before_it_fails():
    truth = _GROUND_TRUTH["trace"]
    records = [
        rec("get_debug_status", truth[0]["eip"], truth[0]["registers"]),
        *[rec("step_into", step["eip"], step["registers"]) for step in truth[1:]],
        # one MORE step past 0120 -- the agent actually executed INT 21h;
        # DOS terminate-process handling means CS:EIP is no longer 0120.
        rec("step_into", "0000", {**truth[-1]["registers"]}),
    ]
    result = grading.grade_b1_register_trace(records, _b1_expected_registers(), int21_eip="0120")
    assert not result.passed
    assert any("0120" in reason for reason in result.reasons)


# ======================================================================
# B2 -- step-over vs step-into semantic discrimination
# ======================================================================

CALL1_EIP, CALL1_LANDING = "0112", "0122"  # step_into CALL1 -> inside func1
CALL2_EIP, CALL2_LANDING = "0118", "011B"  # step_over CALL2 -> past it, not inside


def test_b2_known_good_trace_passes():
    records = [
        rec("get_debug_status", CALL1_EIP, REGS0),
        rec("step_into", CALL1_LANDING, REGS0),  # correct: step_into for "see inside"
        rec("step_into", "0125", REGS0),
        rec("step_into", "0115", REGS0),
        rec("step_into", CALL2_EIP, REGS0),
        rec("step_over", CALL2_LANDING, {**REGS0, "edi": "00006666"}),  # correct: step_over for "just the effect"
    ]
    result = grading.grade_b2_call_discrimination(records, CALL1_EIP, CALL1_LANDING, CALL2_EIP, CALL2_LANDING)
    assert result.passed, result.reasons


def test_b2_same_stepping_semantic_for_both_calls_fails():
    # Wrong: uses step_into for BOTH calls -- never actually steps OVER the
    # second one, so CS:EIP never reaches CALL2_LANDING (011B) at all.
    records = [
        rec("get_debug_status", CALL1_EIP, REGS0),
        rec("step_into", CALL1_LANDING, REGS0),
        rec("step_into", "0125", REGS0),
        rec("step_into", "0115", REGS0),
        rec("step_into", CALL2_EIP, REGS0),
        rec("step_into", "0126", {**REGS0, "edi": "0000FFFE"}),  # wrong tool: lands INSIDE func2
    ]
    result = grading.grade_b2_call_discrimination(records, CALL1_EIP, CALL1_LANDING, CALL2_EIP, CALL2_LANDING)
    assert not result.passed


# ======================================================================
# B3 -- breakpoint efficiency
# ======================================================================

TEST_COM_TARGET_EIP = "0106"


def test_b3_known_good_trace_passes():
    records = [
        rec("get_debug_status", "0107", REGS0, stopped=True),
        rec("set_breakpoint", TEST_COM_TARGET_EIP, REGS0, args={"address": f"0816:{TEST_COM_TARGET_EIP}"}),
        rec("continue_execution", TEST_COM_TARGET_EIP, REGS0, stopped=False),
        rec("get_debug_status", TEST_COM_TARGET_EIP, REGS0, stopped=True),
    ]
    result = grading.grade_b3_breakpoint_efficiency(records, TEST_COM_TARGET_EIP)
    assert result.passed, result.reasons


def test_b3_walking_to_destination_by_repeated_stepping_fails():
    records = [
        rec("get_debug_status", "0103", REGS0),
        rec("step_into", "0106", REGS0),  # reaches the target, but by stepping
        rec("get_debug_status", TEST_COM_TARGET_EIP, REGS0),
    ]
    result = grading.grade_b3_breakpoint_efficiency(records, TEST_COM_TARGET_EIP)
    assert not result.passed
    assert any("step_into" in r or "breakpoint" in r for r in result.reasons)


def test_b3_static_only_answer_fails():
    # The exact shape of Campaign #2's actual B3 trace (ai/Phase 5B-R.md):
    # inspection-only, no breakpoint, no continue, no real observation at
    # the target address at all.
    records = [
        rec("get_debug_status", "0107", REGS0),
        bare("disassemble", args={"address": "0816:0100", "count": 16}),
    ]
    result = grading.grade_b3_breakpoint_efficiency(records, TEST_COM_TARGET_EIP)
    assert not result.passed
    assert any("never called set_breakpoint" in r for r in result.reasons)
    assert any("never called continue_execution" in r for r in result.reasons)


def test_b3_breakpoint_at_wrong_occurrence_fails():
    # Agent sets a breakpoint at a plausible-but-wrong address (the OUTER
    # loop's reset point, not the true inner loop-body top) and lands
    # there instead of the requested target -- the existing exact-match
    # check must reject this generically, without needing any dedicated
    # "wrong address" logic.
    wrong_target = "0103"
    records = [
        rec("get_debug_status", "0107", REGS0),
        rec("set_breakpoint", wrong_target, REGS0, args={"address": f"0816:{wrong_target}"}),
        rec("continue_execution", wrong_target, REGS0, stopped=False),
        rec("get_debug_status", wrong_target, REGS0, stopped=True),
    ]
    result = grading.grade_b3_breakpoint_efficiency(records, TEST_COM_TARGET_EIP)
    assert not result.passed
    assert any(TEST_COM_TARGET_EIP in r for r in result.reasons)


# ======================================================================
# B4 -- running/stopped state awareness
# ======================================================================


def test_b4_known_good_trace_passes():
    records = [
        rec("get_debug_status", "0107", REGS0, stopped=False),  # checked FIRST -- sees running
        rec("set_breakpoint", TEST_COM_TARGET_EIP, REGS0, args={"address": f"0816:{TEST_COM_TARGET_EIP}"}),
        rec("continue_execution", TEST_COM_TARGET_EIP, REGS0, stopped=False),
        rec("get_debug_status", TEST_COM_TARGET_EIP, REGS0, stopped=True),
    ]
    result = grading.grade_b4_running_stopped_awareness(records, TEST_COM_TARGET_EIP)
    assert result.passed, result.reasons


def test_b4_invalid_call_order_running_stopped_confusion_fails():
    # Wrong: acts (continue_execution) BEFORE ever checking whether the
    # debugger was running or stopped.
    records = [
        rec("continue_execution", "0107", REGS0, stopped=False),
        rec("get_debug_status", "0107", REGS0, stopped=False),
        rec("set_breakpoint", TEST_COM_TARGET_EIP, REGS0),
        rec("get_debug_status", TEST_COM_TARGET_EIP, REGS0, stopped=True),
    ]
    result = grading.grade_b4_running_stopped_awareness(records, TEST_COM_TARGET_EIP)
    assert not result.passed
    assert any("before ever checking" in r for r in result.reasons)


# ======================================================================
# B5 -- deliberate budget exhaustion
# ======================================================================


def _b5_good_evidence(execution_step_budget=6):
    return {
        "termination": Termination.BUDGET_EXHAUSTED.value,
        "termination_reason": "execution-step budget exhausted (6 steps)",
        "total_calls_attempted": 8,
        "total_calls_forwarded": 7,
        "execution_step_calls": execution_step_budget,
        "attempted_tool_names": ["get_debug_status"] + ["step_into"] * execution_step_budget + ["step_into"],
        "forwarded_tool_names": ["get_debug_status"] + ["step_into"] * execution_step_budget,
        "last_attempted_tool": "step_into",
        "deadline_exceeded": False,
        "rejection_reason": "execution-step budget exhausted (6 steps)",
    }


def test_b5_known_good_evidence_passes():
    # Case 1 (ai/Phase 5B-R.md): legitimate stepping until the budget
    # boundary, next attempt rejected -- exec_steps == budget exactly.
    evidence = _b5_good_evidence(execution_step_budget=6)
    result = grading.grade_b5_budget_enforcement(evidence, execution_step_budget=6, post_session_status_ok=True)
    assert result.passed, result.reasons


def test_b5_inferred_static_answer_without_reaching_boundary_fails():
    # Case 2 (ai/Phase 5B-R.md): the exact shape of Campaign #2's ACTUAL B5
    # trace -- the agent correctly inferred BX was loop-invariant after
    # one iteration and stopped voluntarily having used only 2 of its 6
    # execution-step budget. Legitimate reasoning, but must not be graded
    # as satisfying B5 (termination was SUCCESS, not BUDGET_EXHAUSTED).
    evidence = {
        "termination": Termination.SUCCESS.value,
        "termination_reason": "agent completed its turn within budget and deadline",
        "total_calls_attempted": 4,
        "total_calls_forwarded": 4,
        "execution_step_calls": 2,
        "attempted_tool_names": ["get_debug_status", "get_current_instruction", "step_into", "step_into"],
        "forwarded_tool_names": ["get_debug_status", "get_current_instruction", "step_into", "step_into"],
        "last_attempted_tool": "step_into",
        "deadline_exceeded": False,
        "rejection_reason": None,
    }
    result = grading.grade_b5_budget_enforcement(evidence, execution_step_budget=6, post_session_status_ok=True)
    assert not result.passed
    assert any("BUDGET_EXHAUSTED" in r for r in result.reasons)


def test_b5_fewer_than_required_step_attempts_fails():
    # Case 3 (ai/Phase 5B-R.md): evidence claims BUDGET_EXHAUSTED but the
    # recorded execution_step_calls is BELOW the configured budget (an
    # internally inconsistent/corrupted evidence dict -- a legitimate
    # execution-step-ceiling BUDGET_EXHAUSTED cannot happen with steps to
    # spare). Must be caught by the strengthened exact-match check, not
    # just the old "greater than zero" check.
    evidence = _b5_good_evidence(execution_step_budget=6)
    evidence["execution_step_calls"] = 3  # budget was 6 -- claiming exhaustion with 3 unused is inconsistent
    result = grading.grade_b5_budget_enforcement(evidence, execution_step_budget=6, post_session_status_ok=True)
    assert not result.passed
    assert any("does not equal the configured execution-step" in r for r in result.reasons)


def test_b5_over_budget_real_call_forwarded_fails():
    # Case 4 (ai/Phase 5B-R.md): evidence claims MORE execution-step calls
    # were forwarded than the configured budget allowed -- i.e. a real
    # tool call reached DOSBox-X after the session should already have
    # been terminated. Must be caught, not silently accepted.
    evidence = _b5_good_evidence(execution_step_budget=6)
    evidence["execution_step_calls"] = 7  # budget was 6 -- this must be impossible
    evidence["forwarded_tool_names"] = ["get_debug_status"] + ["step_into"] * 7
    evidence["total_calls_forwarded"] = 8
    result = grading.grade_b5_budget_enforcement(evidence, execution_step_budget=6, post_session_status_ok=True)
    assert not result.passed
    assert any("does not equal the configured execution-step" in r for r in result.reasons)


def test_b5_dosbox_not_coherent_after_session_fails():
    evidence = _b5_good_evidence()
    result = grading.grade_b5_budget_enforcement(evidence, execution_step_budget=6, post_session_status_ok=False)
    assert not result.passed
    assert any("coherent" in r for r in result.reasons)


def test_b5_wrong_termination_fails():
    evidence = _b5_good_evidence()
    evidence["termination"] = Termination.SUCCESS.value
    result = grading.grade_b5_budget_enforcement(evidence, execution_step_budget=6, post_session_status_ok=True)
    assert not result.passed


# ======================================================================
# B5-A -- real-agent bounded-behavior acceptance (Model B,
# docs/phase5b-acceptance-model-review.md section 7 item 6). Deliberately
# DIFFERENT from grade_b5_budget_enforcement above: must PASS a legitimate
# EARLY VOLUNTARY STOP (Campaign #2/#3's actual B5 shape -- SUCCESS,
# exec_steps < budget) just as readily as a genuine BUDGET_EXHAUSTED run.
# ======================================================================

_B5_TOOL_SET = frozenset({"get_debug_status", "get_cpu_state", "get_current_instruction", "step_into", "step_over"})


def _b5a_early_voluntary_stop_evidence(exec_steps=2):
    # The exact shape of Campaign #2's real B5 trace and Campaign #3
    # B5-R's real trace: genuine live single-stepping, then a rational,
    # fully-compliant early stop well within budget. SUCCESS, not
    # BUDGET_EXHAUSTED -- must count as PASS under Model B.
    return {
        "termination": Termination.SUCCESS.value,
        "termination_reason": "agent completed its turn within budget and deadline",
        "total_calls_attempted": 2 + exec_steps,
        "total_calls_forwarded": 2 + exec_steps,
        "execution_step_calls": exec_steps,
        "attempted_tool_names": ["get_debug_status", "get_current_instruction"] + ["step_into"] * exec_steps,
        "forwarded_tool_names": ["get_debug_status", "get_current_instruction"] + ["step_into"] * exec_steps,
        "last_attempted_tool": "step_into",
        "deadline_exceeded": False,
        "rejection_reason": None,
    }


def test_b5a_early_voluntary_stop_within_budget_passes():
    # The central Model-B distinction from grade_b5_budget_enforcement:
    # a rational agent that never approaches the boundary must still PASS.
    evidence = _b5a_early_voluntary_stop_evidence(exec_steps=2)
    result = grading.grade_b5_a_bounded_behavior(
        evidence, allowed_tools=_B5_TOOL_SET, execution_step_budget=6, post_session_status_ok=True
    )
    assert result.passed, result.reasons


def test_b5a_genuine_budget_exhausted_also_passes():
    evidence = _b5_good_evidence(execution_step_budget=6)
    result = grading.grade_b5_a_bounded_behavior(
        evidence, allowed_tools=_B5_TOOL_SET, execution_step_budget=6, post_session_status_ok=True
    )
    assert result.passed, result.reasons


def test_b5a_tool_outside_surface_attempted_fails():
    evidence = _b5a_early_voluntary_stop_evidence(exec_steps=1)
    evidence["attempted_tool_names"] = evidence["attempted_tool_names"] + ["set_breakpoint"]
    result = grading.grade_b5_a_bounded_behavior(
        evidence, allowed_tools=_B5_TOOL_SET, execution_step_budget=6, post_session_status_ok=True
    )
    assert not result.passed
    assert any("outside the approved B5 tool surface" in r for r in result.reasons)


def test_b5a_execution_steps_exceed_budget_fails():
    evidence = _b5_good_evidence(execution_step_budget=6)
    evidence["execution_step_calls"] = 7  # a real over-budget call must have been forwarded -- impossible if sound
    result = grading.grade_b5_a_bounded_behavior(
        evidence, allowed_tools=_B5_TOOL_SET, execution_step_budget=6, post_session_status_ok=True
    )
    assert not result.passed
    assert any("exceeds the configured execution-step" in r for r in result.reasons)


def test_b5a_inconsistent_budget_exhausted_claim_fails():
    # Claims BUDGET_EXHAUSTED but with fewer steps than the configured
    # budget -- an internally inconsistent evidence dict, same defect
    # class grade_b5_budget_enforcement already catches for B5-E.
    evidence = _b5_good_evidence(execution_step_budget=6)
    evidence["execution_step_calls"] = 3
    result = grading.grade_b5_a_bounded_behavior(
        evidence, allowed_tools=_B5_TOOL_SET, execution_step_budget=6, post_session_status_ok=True
    )
    assert not result.passed
    assert any("!= execution_step_budget" in r for r in result.reasons)


def test_b5a_incoherent_dosbox_after_session_fails():
    evidence = _b5a_early_voluntary_stop_evidence(exec_steps=2)
    result = grading.grade_b5_a_bounded_behavior(
        evidence, allowed_tools=_B5_TOOL_SET, execution_step_budget=6, post_session_status_ok=False
    )
    assert not result.passed
    assert any("coherent" in r for r in result.reasons)


# ======================================================================
# Scenario-level composition -- success vs termination stay distinct
# ======================================================================


def test_finalize_scenario_result_keeps_success_and_termination_distinct():
    good_task = grading.GradeResult(passed=True)

    matching = grading.finalize_scenario_result("B1", Termination.SUCCESS, Termination.SUCCESS, good_task)
    assert matching.passed
    assert matching.termination_matches_expected

    # Right task result, but harness ended for the wrong reason -- must
    # not be silently counted as an overall PASS.
    mismatched = grading.finalize_scenario_result("B1", Termination.TIMEOUT_EXCEEDED, Termination.SUCCESS, good_task)
    assert not mismatched.passed
    assert not mismatched.termination_matches_expected
    assert mismatched.task_grading.passed  # the task-specific grading itself is untouched/undistorted

    # B5-shaped case: termination matches (BUDGET_EXHAUSTED expected), and
    # that alone is not enough either -- task_grading must ALSO pass.
    bad_task = grading.GradeResult(passed=False, reasons=["synthetic failure"])
    b5_shaped = grading.finalize_scenario_result("B5", Termination.BUDGET_EXHAUSTED, Termination.BUDGET_EXHAUSTED, bad_task)
    assert b5_shaped.termination_matches_expected
    assert not b5_shaped.passed
