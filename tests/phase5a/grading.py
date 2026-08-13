"""
Phase 5A grading engine (docs/phase5a-tool-awareness-design.md section 3.1
item 4): mechanical PASS/FAIL checks matching each of the 5 scenarios'
documented criteria, evaluated against a recorded tool-call trace
(ai/server_phase5a.py's get_call_log()) plus independently-observed
DOSBox-X state -- never against an agent's own prose summary.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class GradeResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)

    def fail(self, reason: str) -> None:
        self.passed = False
        self.reasons.append(reason)

    def note(self, reason: str) -> None:
        self.reasons.append(reason)


def call_names(call_log: list[dict[str, Any]]) -> list[str]:
    return [c["name"] for c in call_log]


def first_call_index(call_log: list[dict[str, Any]], name: str) -> Optional[int]:
    for i, c in enumerate(call_log):
        if c["name"] == name:
            return i
    return None


def check_no_prohibited_calls(result: GradeResult, call_log, prohibited: set[str]) -> None:
    used = set(call_names(call_log)) & prohibited
    if used:
        result.fail(f"prohibited tool(s) called: {sorted(used)}")


def check_at_least_one_of(result: GradeResult, call_log, allowed_any: set[str], purpose: str) -> None:
    if not (set(call_names(call_log)) & allowed_any):
        result.fail(f"no tool call evidencing '{purpose}' -- expected at least one of {sorted(allowed_any)}")


def check_states_equal(result: GradeResult, before: dict, after: dict, label: str) -> None:
    if before.get("location") != after.get("location") or before.get("registers") != after.get("registers"):
        result.fail(
            f"{label}: state changed when it should not have "
            f"(before={before.get('location')}, after={after.get('location')})"
        )


# ======================================================================
# Scenario 1 -- current-state inspection
# ======================================================================

SCENARIO_1_PROHIBITED = {
    "write_register", "write_memory", "set_breakpoint", "delete_breakpoint",
    "continue_execution", "pause_execution", "step_into", "step_over",
}
SCENARIO_1_ALLOWED_EVIDENCE = {
    "get_debug_status", "get_cpu_state", "get_current_instruction", "read_memory", "disassemble",
}


def grade_scenario_1(call_log, before_status: dict, after_status: dict, reported_cs: str, reported_eip: str) -> GradeResult:
    result = GradeResult(passed=True)
    check_no_prohibited_calls(result, call_log, SCENARIO_1_PROHIBITED)
    check_at_least_one_of(result, call_log, SCENARIO_1_ALLOWED_EVIDENCE, "inspecting current state")
    check_states_equal(result, before_status, after_status, "scenario 1")
    ground_truth = before_status["location"]
    if not (reported_cs == ground_truth["cs"] and reported_eip == ground_truth["eip"]):
        result.fail(f"reported CS:EIP {reported_cs}:{reported_eip} != ground truth {ground_truth}")
    return result


# ======================================================================
# Scenario 2 -- instruction identification
# ======================================================================

SCENARIO_2_PROHIBITED = SCENARIO_1_PROHIBITED  # identification must not execute anything
SCENARIO_2_ALLOWED_EVIDENCE = {"get_current_instruction", "disassemble", "get_debug_status"}


def grade_scenario_2(call_log, before_status: dict, after_status: dict, reported_mnemonic: str) -> GradeResult:
    result = GradeResult(passed=True)
    check_no_prohibited_calls(result, call_log, SCENARIO_2_PROHIBITED)
    check_at_least_one_of(result, call_log, SCENARIO_2_ALLOWED_EVIDENCE, "identifying the instruction")
    check_states_equal(result, before_status, after_status, "scenario 2")
    real_text = before_status["instruction"]["text"].lower()
    if reported_mnemonic.lower() not in real_text:
        result.fail(f"reported mnemonic {reported_mnemonic!r} not found in real instruction text {real_text!r}")
    return result


# ======================================================================
# Scenario 3 -- CALL step-into vs. step-over reasoning
# ======================================================================


def grade_scenario_3(call_log, variant: str, before_status: dict, after_status: dict) -> GradeResult:
    result = GradeResult(passed=True)
    names = call_names(call_log)

    if variant == "into":
        required, forbidden = "step_into", "step_over"
    elif variant == "over":
        required, forbidden = "step_over", "step_into"
    else:
        raise ValueError(f"unknown variant {variant!r}")

    if forbidden in names:
        result.fail(f"used {forbidden} for a '{variant}' task -- wrong tool for the requested reasoning")
    if required not in names:
        result.fail(f"never called {required} -- task was not accomplished")
    if "continue_execution" in names:
        result.fail("used continue_execution -- too coarse, does not stop at the point of interest")
    prohibited_writes = {"write_register", "write_memory", "set_breakpoint", "delete_breakpoint"}
    used_writes = set(names) & prohibited_writes
    if used_writes:
        result.fail(f"unnecessary state-modifying tool(s) used: {sorted(used_writes)}")

    before_eip = before_status["location"]["eip"]
    after_eip = after_status["location"]["eip"]

    if variant == "into":
        # Entering the callee must land STRICTLY inside it (a later address
        # than the CALL itself, and not the well-known "after the call"
        # return point) -- checked precisely by the caller via expected_eip.
        if after_eip == before_eip:
            result.fail("CS:EIP did not move at all")
    else:  # "over"
        if after_eip == before_eip:
            result.fail("CS:EIP did not move at all")

    return result


def grade_scenario_3_exact(call_log, variant: str, before_status: dict, after_status: dict, expected_eip: str) -> GradeResult:
    """Stricter variant used by the harness self-test, where the exact
    expected landing offset is known in advance (STEP.COM is fully
    deterministic) -- checks the precise transition documented in
    docs/phase5a-tool-awareness-design.md Scenario 3, not just "it moved"."""

    result = grade_scenario_3(call_log, variant, before_status, after_status)
    if after_status["location"]["eip"] != expected_eip:
        result.fail(f"landed at {after_status['location']['eip']}, expected exactly {expected_eip}")
    return result


# ======================================================================
# Scenario 4 -- breakpoint investigation
# ======================================================================


def grade_scenario_4_set_and_hit(call_log, target: str, harness_confirmed_bp_existed: bool, final_status: dict) -> GradeResult:
    result = GradeResult(passed=True)
    names = call_names(call_log)
    prohibited = {"write_register", "write_memory", "step_into", "step_over", "pause_execution"}
    check_no_prohibited_calls(result, call_log, prohibited)

    if "set_breakpoint" not in names:
        result.fail("never called set_breakpoint")
    if "continue_execution" not in names:
        result.fail("never called continue_execution")
    if not harness_confirmed_bp_existed:
        result.fail("breakpoint was never independently confirmed to exist in DOSBox-X's own breakpoint list")

    idx_set = first_call_index(call_log, "set_breakpoint")
    idx_continue = first_call_index(call_log, "continue_execution")
    if idx_set is not None and idx_continue is not None and idx_set > idx_continue:
        result.fail("continue_execution was called before set_breakpoint")

    if final_status["location"]["eip"] != target.split(":")[1]:
        result.fail(f"final stop address {final_status['location']} does not exactly match target {target}")

    return result


def grade_scenario_4_list_only(call_log, before_status: dict, after_status: dict, before_breakpoints: list, after_breakpoints: list) -> GradeResult:
    result = GradeResult(passed=True)
    names = call_names(call_log)
    prohibited = {"write_register", "write_memory", "set_breakpoint", "delete_breakpoint", "step_into", "step_over", "continue_execution", "pause_execution"}
    check_no_prohibited_calls(result, call_log, prohibited)
    if "list_breakpoints" not in names:
        result.fail("never called list_breakpoints")
    check_states_equal(result, before_status, after_status, "scenario 4b")
    if before_breakpoints != after_breakpoints:
        result.fail(f"breakpoint list mutated: {before_breakpoints} -> {after_breakpoints}")
    return result


# ======================================================================
# Scenario 5 -- running/stopped state awareness
# ======================================================================

SCENARIO_5_STATE_CHECK_TOOLS = {"get_debug_status", "get_cpu_state"}
SCENARIO_5_NEVER = {
    "write_register", "write_memory", "set_breakpoint", "delete_breakpoint",
    "step_into", "step_over", "continue_execution",
}


def grade_scenario_5(call_log, variant: str, before_status: dict, after_status: dict) -> GradeResult:
    result = GradeResult(passed=True)
    names = call_names(call_log)

    check_no_prohibited_calls(result, call_log, SCENARIO_5_NEVER)

    idx_check = None
    for tool in SCENARIO_5_STATE_CHECK_TOOLS:
        i = first_call_index(call_log, tool)
        if i is not None and (idx_check is None or i < idx_check):
            idx_check = i
    idx_pause = first_call_index(call_log, "pause_execution")

    if idx_check is None:
        result.fail("never checked debugger state before acting")
    if idx_pause is not None and idx_check is not None and idx_pause < idx_check:
        result.fail("called pause_execution before checking state -- did not reason about state first")

    if variant == "running":
        if idx_pause is None:
            result.fail("debugger was running but pause_execution was never called")
        if not after_status["stopped"]:
            result.fail("debugger is still running after the scenario -- pause did not take effect")
    elif variant == "stopped":
        if idx_pause is not None:
            result.fail("debugger was already stopped but pause_execution was called anyway")
        check_states_equal(result, before_status, after_status, "scenario 5 (stopped variant)")
    else:
        raise ValueError(f"unknown variant {variant!r}")

    return result
