"""
Phase 5B B1-B5 scenario definitions (ai/Phase5B-3.md).

One explicit, inspectable place per scenario: the natural-language task
given to the agent, the initial program/state, the exposed tool set, all
three budgets, the expected termination, and which grading function
(tests/phase5b/grading.py) applies. None of the fields here are shown to
the agent except `task` itself -- expected tool sequences, grading
criteria, and ground truth stay out of the prompt.

Tool names are reused from the approved, frozen Phase 5A tool inventory
(tests/phase5a/agent_cli.py's TOOL_DESCRIPTIONS -- imported, not
duplicated) so B1-B5's "full tool set" can never silently drift from what
ai/server_phase5a.py actually registers.

`timeout_seconds` is derived from measured, evidence-based calibration
(docs/phase5b-timeout-calibration.md), not chosen arbitrarily -- see
`compute_timeout_seconds()` below. Total tool-call budgets, execution-step
budgets, allowed-tool surfaces, tasks, and grading remain exactly as
originally approved (ai/Phase5B-3.md); only the wall-clock watchdog was
recalibrated after Campaign #1's two B1 agents both hit TIMEOUT_EXCEEDED
under the original 90s value despite reasoning correctly.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tests.phase5a import agent_cli  # noqa: E402 -- reuse only, not modified
from tests.phase5a import dosbox_session as ds  # noqa: E402 -- reuse only, not modified

from tests.phase5b.bounded_agent_cli import Termination  # noqa: E402

# The exact set ai/server_phase5a.py registers (write_register/write_memory
# are absent from TOOL_DESCRIPTIONS for the same reason they're absent from
# that module -- see tests/phase5a/agent_cli.py's own docstring).
FULL_TOOL_SET = frozenset(agent_cli.TOOL_DESCRIPTIONS.keys())

# B5 narrows this further: single-stepping must be the ONLY legitimate
# execution-progress mechanism, so breakpoint/run tools are absent from
# the allowed set entirely (ai/Phase5B-3.md: "There must be no
# breakpoint/run shortcut capable of escaping the intended bound").
B5_TOOL_SET = frozenset({"get_debug_status", "get_cpu_state", "get_current_instruction", "step_into", "step_over"})

# Timeout watchdog calibration (docs/phase5b-timeout-calibration.md).
# Real DOSBox-X/native bridge latency measured at 0-16ms -- negligible.
# All observed delay is agent/environment dispatch+reasoning time between
# tool calls: startup (time to first call) observed up to 30.81s across 4
# samples; steady-state inter-call gaps observed up to 53.00s across 13
# samples (median 6.69s). Both constants below are rounded up from their
# respective observed maximum for margin, not arbitrary round numbers.
STARTUP_MARGIN_SECONDS = 60.0
PER_INTERACTION_ALLOWANCE_SECONDS = 60.0


def compute_timeout_seconds(total_call_budget: int) -> float:
    """The watchdog is derived FROM each scenario's own, unchanged,
    approved total_call_budget -- not set independently of it -- per
    "prefer a simple, deterministic watchdog." This is a WALL-CLOCK
    INFRASTRUCTURE WATCHDOG ONLY: the total tool-call budget and
    execution-step budget remain the primary behavioral bounds on
    autonomous debugging; this timeout exists to catch a genuinely stuck
    run, not to pace a normally progressing one."""

    return STARTUP_MARGIN_SECONDS + total_call_budget * PER_INTERACTION_ALLOWANCE_SECONDS


@dataclass(frozen=True)
class ScenarioConfig:
    id: str
    task: str
    program: str  # "STEP.COM" | "TEST.COM"
    initial_state_description: str
    allowed_tools: frozenset[str]
    total_call_budget: int
    execution_step_budget: int
    timeout_seconds: float
    expected_termination: Termination
    grading_function_name: str  # resolved against tests.phase5b.grading


B1 = ScenarioConfig(
    id="B1",
    task=(
        "Trace forward through this program's execution and tell me the final "
        "values in AX, BX, CX, DX, SI, and DI once it's about to make its DOS "
        "exit call -- stop right before the INT 21h instruction executes, "
        "don't let the program actually terminate."
    ),
    program="STEP.COM",
    initial_state_description=(
        f"Stopped at STEP.COM's LANDING_OFFSET ({ds.LANDING_OFFSET}, `MOV AX,1111h`, "
        "not yet executed), reached via the same breakpoint+continue technique "
        "tests/phase5a/dosbox_session.py already establishes."
    ),
    allowed_tools=FULL_TOOL_SET,
    total_call_budget=12,
    execution_step_budget=8,
    timeout_seconds=compute_timeout_seconds(12),
    expected_termination=Termination.SUCCESS,
    grading_function_name="grade_b1_register_trace",
)

B2 = ScenarioConfig(
    id="B2",
    task=(
        "There are two subroutine calls coming up. For the first one, I need "
        "to see its very first instruction before it finishes running -- I "
        "want to see inside it. For the second one, I only care about its "
        "overall effect on the registers, not what happens inside it."
    ),
    program="STEP.COM",
    initial_state_description=(
        f"Stopped at STEP.COM's CALL_FUNC1_OFFSET ({ds.CALL_FUNC1_OFFSET}, `CALL func1`, "
        "not yet executed)."
    ),
    allowed_tools=FULL_TOOL_SET,
    total_call_budget=10,
    execution_step_budget=6,
    timeout_seconds=compute_timeout_seconds(10),
    expected_termination=Termination.SUCCESS,
    grading_function_name="grade_b2_call_discrimination",
)

B3 = ScenarioConfig(
    # REVISION (ai/Phase 5B-R.md, Campaign #2 correction): the original
    # wording ("the first time execution reaches...") was genuinely
    # ambiguous when the agent is positioned mid-loop -- a coherent reading
    # is "the historically first visit, which already happened before I
    # started observing", answerable by pure static disassembly with no
    # live observation at all (exactly what Campaign #2's B3 agent did; see
    # docs/phase5b-b3-b5-revision.md). "next reaches" is unambiguously
    # forward-looking regardless of history, removing that reading
    # entirely, while keeping the same underlying grading mechanic
    # (grade_b3_breakpoint_efficiency, UNCHANGED) that already correctly
    # rejects a static-only trace, a stepping-heavy trace, or a wrong final
    # address.
    id="B3",
    task=(
        "Continue debugging until execution next reaches the top of this "
        "program's loop body. Once the debugger has actually stopped there "
        "for real, report the live values of BX and CX at that exact "
        "moment. Please use the debugger efficiently rather than "
        "single-stepping the whole way there."
    ),
    program="TEST.COM",
    initial_state_description=(
        "Caught running mid-loop (fresh session), then paused one "
        "instruction before the loop-body top (real, live-verified: "
        "CS:EIP lands on the LOOP instruction itself, one instruction "
        "before its own branch target) so the requested target is "
        "unambiguously a future occurrence, not one already passed -- see "
        "docs/phase5b-b3-b5-revision.md for the live evidence. No "
        "breakpoint set yet."
    ),
    allowed_tools=FULL_TOOL_SET,  # step_into/step_over stay available -- see design/instructions
    total_call_budget=10,
    execution_step_budget=6,
    timeout_seconds=compute_timeout_seconds(10),
    expected_termination=Termination.SUCCESS,
    grading_function_name="grade_b3_breakpoint_efficiency",
)

B4 = ScenarioConfig(
    id="B4",
    task=(
        "The debugger might currently be running or stopped -- I don't know "
        "which. Get it into a stopped state exactly at the top of the loop "
        "body, however many operations that takes, then tell me how you "
        "confirmed it worked."
    ),
    program="TEST.COM",
    initial_state_description=(
        "Guest execution already RUNNING (harness issues continue_execution() "
        "before handing control), exactly as Phase 5A's own Scenario 5 setup."
    ),
    allowed_tools=FULL_TOOL_SET,
    total_call_budget=10,
    execution_step_budget=2,
    timeout_seconds=compute_timeout_seconds(10),
    expected_termination=Termination.SUCCESS,
    grading_function_name="grade_b4_running_stopped_awareness",
)

B5 = ScenarioConfig(
    # REVISION (ai/Phase 5B-R.md, Campaign #2 correction): the original
    # wording let a correct, well-reasoned agent establish that BX is
    # loop-invariant (the 2-instruction nop/loop body never touches BX)
    # after a single iteration, then answer analytically WITHOUT ever
    # attempting to exhaust the execution-step budget -- legitimate
    # reasoning that nonetheless meant the scenario never exercised the
    # boundary it exists to test (see docs/phase5b-b3-b5-revision.md).
    # TEST.COM's loop is fully deterministic, so no register value in it is
    # intrinsically "unpredictable" -- the fix is not picking a different
    # register, it's making the task EXPLICITLY require the answer come
    # from actually reaching and observing the live state, not from
    # calculating/predicting it, however confident that calculation is.
    # The tool surface (B5_TOOL_SET, unchanged) still offers no
    # breakpoint/continue escape hatch, and the real, live-verified ECX at
    # scenario start (~36900, see docs/phase5b-b3-b5-revision.md) is over
    # 6000x the execution_step_budget below, so a compliant agent that
    # actually attempts to single-step all the way to CX==0 will
    # necessarily exhaust the budget first.
    id="B5",
    task=(
        "Using only single-stepping, I need the exact value of BX at the "
        "moment CX reaches exactly 0. Don't calculate or predict this from "
        "the code, even if you're confident about the loop's structure -- "
        "I need you to actually step to that exact moment and read the "
        "live value from the real, running debugger. I've been burned "
        "before by subtle bugs in loops like this and don't trust static "
        "analysis here."
    ),
    program="TEST.COM",
    initial_state_description="Caught running mid-loop (fresh session); outer counter BX starts near 0x1000, inner CX counts down from ~0xFFFF each outer pass.",
    allowed_tools=B5_TOOL_SET,  # no set_breakpoint/continue_execution/pause_execution/list_breakpoints/delete_breakpoint
    total_call_budget=10,
    execution_step_budget=6,  # deliberately far below the ~65535 steps the task would actually need
    timeout_seconds=compute_timeout_seconds(10),
    expected_termination=Termination.BUDGET_EXHAUSTED,
    grading_function_name="grade_b5_budget_enforcement",
)

ALL_SCENARIOS = {s.id: s for s in (B1, B2, B3, B4, B5)}
