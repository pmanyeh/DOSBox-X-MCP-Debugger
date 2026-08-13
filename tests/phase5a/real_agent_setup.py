"""
Orchestrator-only setup for the Phase 5A real-agent acceptance run
(ai/Phase5A-2.md). NOT shown to, and not invoked by, the subagent under
test -- this positions each scenario's documented initial state and prints
the ground-truth "before" snapshot as JSON, using the unrecorded `verify`
path plus real tool calls exactly like tests/phase5a/dosbox_session.py's
existing helpers (reused directly, not reimplemented).

Usage: python real_agent_setup.py <scenario_id>

scenario_id one of:
    1_inspection        (STEP.COM, stopped at LANDING_OFFSET)
    2_identification     (STEP.COM, stopped at CALL_FUNC1_OFFSET)
    3_call_over          (STEP.COM, stopped at CALL_FUNC2_OFFSET)
    4_breakpoint         (TEST.COM, stopped mid-loop, no breakpoint set)
    5_running            (TEST.COM, guest execution already running)
"""

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "ai"))
sys.path.insert(0, str(_ROOT))

import server_phase5a as s5a  # noqa: E402

from tests.phase5a import dosbox_session as ds  # noqa: E402


def setup_1_inspection():
    cs = ds.find_step_com_segment()
    ds.clear_all_breakpoints()
    target = f"{cs}:{ds.LANDING_OFFSET}"
    s5a.set_breakpoint(target)
    s5a.continue_execution()
    status = ds.wait_for_stopped(timeout=15.0)
    assert status["location"] == {"cs": cs, "eip": ds.LANDING_OFFSET}, status
    ds.clear_all_breakpoints()
    return s5a.verify.get_debug_status()


def setup_2_identification():
    before = setup_1_inspection()
    # walk forward (unrecorded setup) from LANDING to CALL_FUNC1_OFFSET
    status = before
    while status["location"]["eip"] != ds.CALL_FUNC1_OFFSET:
        status = s5a.step_into()
    return s5a.verify.get_debug_status()


def setup_3_call_over():
    before = setup_2_identification()
    status = before
    while status["location"]["eip"] != ds.CALL_FUNC2_OFFSET:
        status = s5a.step_into()
    return s5a.verify.get_debug_status()


def setup_4_breakpoint():
    ds.find_test_com_segment()
    ds.clear_all_breakpoints()
    return s5a.verify.get_debug_status()


def setup_5_running():
    ds.find_test_com_segment()
    ds.clear_all_breakpoints()
    continued = s5a.continue_execution()
    assert "error" not in continued, continued
    return s5a.verify.get_debug_status()


SETUPS = {
    "1_inspection": setup_1_inspection,
    "2_identification": setup_2_identification,
    "3_call_over": setup_3_call_over,
    "4_breakpoint": setup_4_breakpoint,
    "5_running": setup_5_running,
}


if __name__ == "__main__":
    scenario_id = sys.argv[1]
    trace_file = sys.argv[2] if len(sys.argv) > 2 else None
    before = SETUPS[scenario_id]()
    print(json.dumps(before, indent=2))
    if trace_file:
        Path(trace_file + ".before.json").write_text(json.dumps(before))
