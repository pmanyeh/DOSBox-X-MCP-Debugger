"""
Focused configuration tests for Phase 5B's B1-B5 scenario definitions,
added during the timeout-watchdog recalibration
(docs/phase5b-timeout-calibration.md). No live DOSBox-X needed.

Guards two properties:

1. Every scenario's `timeout_seconds` is exactly what the calibrated
   formula (`compute_timeout_seconds`) produces from its OWN, unchanged
   `total_call_budget` -- catches silent drift between the two.
2. Every behavioral bound (total tool-call budget, execution-step budget,
   allowed-tool surface, expected termination) is byte-for-byte identical
   to what Phase 5B-3 originally approved -- catches a future
   "timeout-only" change accidentally also touching the primary
   behavioral bounds, which the calibration task was explicitly NOT
   permitted to do.

Also specifically verifies B5's execution-step budget remains reachable
(BUDGET_EXHAUSTED) before the wall-clock watchdog could fire
(TIMEOUT_EXCEEDED) under the SAME calibrated worst-case per-interaction
latency assumption the timeout itself is derived from -- the property
ai/Phase5B-timeout-recalibration.md requires stay true after any future
change to either the timeout formula or B5's budget.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.phase5b import scenarios  # noqa: E402
from tests.phase5b.bounded_agent_cli import Termination  # noqa: E402

# The exact behavioral configuration ai/Phase5B-3.md approved, before this
# recalibration task touched anything -- used here purely as an immutable
# regression fixture, not re-derived from scenarios.py itself.
_APPROVED_BEHAVIORAL_CONFIG = {
    "B1": {
        "total_call_budget": 12,
        "execution_step_budget": 8,
        "expected_termination": Termination.SUCCESS,
        "allowed_tools": scenarios.FULL_TOOL_SET,
    },
    "B2": {
        "total_call_budget": 10,
        "execution_step_budget": 6,
        "expected_termination": Termination.SUCCESS,
        "allowed_tools": scenarios.FULL_TOOL_SET,
    },
    "B3": {
        "total_call_budget": 10,
        "execution_step_budget": 6,
        "expected_termination": Termination.SUCCESS,
        "allowed_tools": scenarios.FULL_TOOL_SET,
    },
    "B4": {
        "total_call_budget": 10,
        "execution_step_budget": 2,
        "expected_termination": Termination.SUCCESS,
        "allowed_tools": scenarios.FULL_TOOL_SET,
    },
    "B5": {
        "total_call_budget": 10,
        "execution_step_budget": 6,
        "expected_termination": Termination.BUDGET_EXHAUSTED,
        "allowed_tools": scenarios.B5_TOOL_SET,
    },
}


def test_behavioral_config_unchanged_from_phase5b3_approval():
    for scenario_id, expected in _APPROVED_BEHAVIORAL_CONFIG.items():
        s = scenarios.ALL_SCENARIOS[scenario_id]
        assert s.total_call_budget == expected["total_call_budget"], scenario_id
        assert s.execution_step_budget == expected["execution_step_budget"], scenario_id
        assert s.expected_termination == expected["expected_termination"], scenario_id
        assert s.allowed_tools == expected["allowed_tools"], scenario_id


def test_all_timeouts_match_calibrated_formula():
    for scenario_id, s in scenarios.ALL_SCENARIOS.items():
        expected = scenarios.compute_timeout_seconds(s.total_call_budget)
        assert s.timeout_seconds == expected, (
            f"{scenario_id}: timeout_seconds={s.timeout_seconds} does not match "
            f"compute_timeout_seconds({s.total_call_budget})={expected}"
        )


def test_calibration_constants_are_positive_and_evidence_derived():
    # Sanity guard, not a re-assertion of the calibration analysis itself
    # (see docs/phase5b-timeout-calibration.md for the measured evidence):
    # both constants must be positive, and the per-interaction allowance
    # must exceed the largest single steady-state gap actually observed
    # (53.00s) -- if someone edits these constants down below what was
    # measured, this test catches it.
    assert scenarios.STARTUP_MARGIN_SECONDS > 0
    assert scenarios.PER_INTERACTION_ALLOWANCE_SECONDS > 53.00, (
        "PER_INTERACTION_ALLOWANCE_SECONDS must stay above the largest "
        "steady-state inter-call gap actually observed during calibration "
        "(53.00s) -- see docs/phase5b-timeout-calibration.md"
    )


def test_b5_execution_step_budget_binds_before_timeout():
    b5 = scenarios.ALL_SCENARIOS["B5"]

    # Worst-case wall-clock time to exhaust B5's execution-step budget,
    # using the SAME calibrated per-interaction allowance the timeout
    # itself is derived from, plus headroom for a couple of read-only
    # status checks a reasonable agent might make alongside the
    # step_into/step_over calls.
    worst_case_calls_needed = b5.execution_step_budget + 2
    worst_case_seconds = worst_case_calls_needed * scenarios.PER_INTERACTION_ALLOWANCE_SECONDS

    assert worst_case_seconds < b5.timeout_seconds, (
        f"B5's execution-step budget ({b5.execution_step_budget} steps, "
        f"worst-case {worst_case_seconds}s) must be reachable "
        f"(BUDGET_EXHAUSTED) strictly before the wall-clock watchdog "
        f"({b5.timeout_seconds}s, TIMEOUT_EXCEEDED) under the calibrated "
        f"worst-case per-call latency assumption"
    )


def test_b1_through_b4_expect_success_b5_expects_budget_exhausted():
    # Cheap sanity check that the recalibration didn't accidentally touch
    # expected_termination for any scenario (that would be a grading
    # semantics change, explicitly out of scope for this task).
    for scenario_id in ("B1", "B2", "B3", "B4"):
        assert scenarios.ALL_SCENARIOS[scenario_id].expected_termination == Termination.SUCCESS
    assert scenarios.ALL_SCENARIOS["B5"].expected_termination == Termination.BUDGET_EXHAUSTED
