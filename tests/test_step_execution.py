"""
Integration test: MCP tool layer -> DOSBoxClient -> native AI bridge ->
real, running DOSBox-X (Phase 4D: execution.step_into / execution.step_over).

Like tests/test_mcp_native_bridge.py, this calls the actual ai/server.py MCP
tool functions against a real, running DOSBox-X instance with the native AI
bridge listening on 127.0.0.1:9876. FakeDOSBoxDebugger is intentionally not
used here.

Unlike test_mcp_native_bridge.py (which relies on drive_c/TEST.COM, a long
busy loop used to exercise breakpoints/execution control), this file
requires drive_c/STEP.COM -- a short, deterministic program built
specifically to exercise step_into()/step_over() against ordinary
instructions, two independent CALLs, and the instructions after/inside
them, per Phase4D.md section 5. Start DOSBox-X with STEP.COM queued to
auto-run before running this file:

    dosbox-src\\bin\\x64\\Release\\dosbox-x.exe -break-start drive_c\\STEP.COM

If the bridge isn't reachable, every test in this file is skipped rather
than hanging or failing with a confusing socket error.

drive_c/STEP.COM (created for Phase 4D) is the hand-assembled machine code
for:

    ORG 100h
            MOV BX, 0040h        ; busy-loop warm-up -- same SHAPE as
    outer:  MOV CX, 0FFFFh       ; drive_c/TEST.COM's own loop (see
    inner:  NOP                  ; AGENTS.md section 26 / Phase4C.md), just a
            LOOP inner            ; much SMALLER outer count. TEST.COM's own
            DEC BX                ; breakpoint sits INSIDE this loop (hit on
            JNZ outer              ; the loop's very first pass, regardless of
    landing:                       ; outer count) -- but LANDING_OFFSET below
            MOV AX, 1111h         ; sits AFTER the loop, so reaching it needs
            MOV BX, 2222h         ; the ENTIRE loop to finish. At this
            CALL func1                    ; project's default emulated CPU
            MOV CX, 3333h         ; speed (3000 cycles/ms), TEST.COM's own
            CALL func2                    ; 0x1000-outer loop takes on the
            MOV SI, 5555h                 ; order of a minute or more to run
            MOV AH, 4Ch                    ; to completion -- fine for a
            INT 21h                        ; breakpoint hit on its first pass,
    func1:                                 ; impractical to wait out fully, so
            MOV DX, 4444h                 ; this file's own warm-up loop uses
            RET                             ; a much smaller outer count
    func2:                                 ; (0x40) that still runs long
            MOV DI, 6666h                 ; enough to be reliably caught by
            RET                             ; the continue/pause polling
                                            ; technique below (empirically
                                            ; ~2s total), while completing
                                            ; well within this file's wait
                                            ; timeouts.

i.e. bytes BB 40 00 B9 FF FF 90 E2 FD 4B 75 F7 B8 11 11 BB 22 22 E8 0D 00
B9 33 33 E8 0B 00 BE 55 55 B4 4C CD 21 BA 44 44 C3 BF 66 66 C3 (42 bytes).
The busy loop's structure (register/opcode choices, relative displacements)
mirrors TEST.COM's own loop exactly, just with a smaller iteration count --
deliberate, so this file's "catch STEP.COM auto-running" technique below
rests on the same reasoning Phase4C.md's TEST.COM section already
established, not a new, separately-trusted mechanism.

STEP.COM's control flow is strictly linear/forward after the busy loop --
it never loops back to an earlier address -- so, unlike TEST.COM, there is
no way to "re-land" on an already-passed instruction within one run. Every
test function below therefore assumes the CUMULATIVE state left by the
tests before it in this file (pytest preserves file/declaration order by
default, with no parallelism here) and advances strictly forward, exactly
mirroring how the real program only ever executes once, start to finish.
Do not reorder these tests.
"""

import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

import pytest

import server as mcp_server  # noqa: E402  (import after sys.path insert)

HOST = "127.0.0.1"
PORT = 9876


def _bridge_available() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _bridge_available(),
    reason=(
        f"native DOSBox-X AI bridge not reachable at {HOST}:{PORT} -- "
        f"start dosbox-x.exe -break-start drive_c\\STEP.COM before running this integration test"
    ),
)

STEP_COM_BYTES = bytes(
    [
        0xBB, 0x40, 0x00, 0xB9, 0xFF, 0xFF, 0x90, 0xE2, 0xFD, 0x4B, 0x75, 0xF7,
        0xB8, 0x11, 0x11, 0xBB, 0x22, 0x22, 0xE8, 0x0D, 0x00, 0xB9, 0x33, 0x33,
        0xE8, 0x0B, 0x00, 0xBE, 0x55, 0x55, 0xB4, 0x4C, 0xCD, 0x21, 0xBA, 0x44,
        0x44, 0xC3, 0xBF, 0x66, 0x66, 0xC3,
    ]
)
LANDING_OFFSET = "010C"    # A: MOV AX,1111h -- first instruction after the busy loop
CALL_FUNC1_OFFSET = "0112"  # CALL func1 (step_over() target)
AFTER_CALL_FUNC1_OFFSET = "0115"  # C: MOV CX,3333h -- instruction after CALL func1
CALL_FUNC2_OFFSET = "0118"  # CALL func2 (step_into() target)
FUNC2_ENTRY_OFFSET = "0126"  # func2: MOV DI,6666h
FUNC2_RET_OFFSET = "0129"   # func2's RET
AFTER_CALL_FUNC2_OFFSET = "011B"  # MOV SI,5555h -- instruction after CALL func2


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


def _wait_for_stopped(timeout=5.0, interval=0.05):
    deadline = time.monotonic() + timeout
    status = None
    while time.monotonic() < deadline:
        status = mcp_server.get_debug_status()
        assert "error" not in status, status
        if status.get("stopped"):
            return status
        time.sleep(interval)
    raise AssertionError(f"debugger did not stop within {timeout}s (last status: {status!r})")


def _find_step_com_segment(max_attempts=25, settle=0.2):
    """Repeatedly continue/pause until the CPU is caught inside
    drive_c/STEP.COM's busy-loop warm-up, confirmed by matching the real
    bytes at CS:0100 against STEP_COM_BYTES -- the same technique
    test_mcp_native_bridge.py's _find_test_com_segment() uses for
    drive_c/TEST.COM, applied here to STEP.COM's own (different) program.
    Returns STEP.COM's real, DOS-assigned load segment."""

    for _ in range(max_attempts):
        status = mcp_server.get_debug_status()
        if not status["stopped"]:
            status = mcp_server.pause_execution()
        cs = status["location"]["cs"]
        mem = mcp_server.read_memory(f"{cs}:0100", len(STEP_COM_BYTES))
        assert "error" not in mem, mem
        if bytes(int(b, 16) for b in mem["bytes"]) == STEP_COM_BYTES:
            return cs
        assert "error" not in mcp_server.continue_execution()
        time.sleep(settle)
    raise AssertionError(
        "drive_c/STEP.COM was never observed running -- was dosbox-x.exe launched as "
        "`dosbox-x.exe -break-start drive_c\\STEP.COM`?"
    )


@pytest.fixture(scope="module")
def cs():
    """STEP.COM's real, DOS-assigned load segment -- discovered once for
    the whole module (see _find_step_com_segment()) and then reused, since
    it does not change for the lifetime of this dosbox-x.exe process."""

    return _find_step_com_segment()


# ======================================================================
# Every test below advances strictly forward through STEP.COM's one and
# only run. See the module docstring: do not reorder.
# ======================================================================


def test_step_00_lands_at_instruction_a(cs):
    # Catch STEP.COM inside its busy loop (via the `cs` fixture), then use
    # the SAME continue+breakpoint mechanism Phase 4C's own TEST.COM loop
    # test already proved (test_mcp_native_bridge.py::
    # test_breakpoint_continue_hits_known_program_loop) to land exactly on
    # instruction A, deterministically.
    #
    # Unlike that TEST.COM test (whose breakpoint sits INSIDE the loop body,
    # hit within the loop's very first pass), LANDING_OFFSET sits AFTER the
    # entire busy loop -- reaching it requires the loop to run to genuine
    # completion. `cs` may have caught us anywhere from the loop's first
    # iteration to its last, so the wait below budgets generously (this
    # file's own, much smaller warm-up loop -- see the module docstring --
    # empirically completes in well under 5s from a cold start at this
    # project's default emulated CPU speed).
    target = f"{cs}:{LANDING_OFFSET}"
    bp = mcp_server.set_breakpoint(target)
    assert "error" not in bp, bp
    try:
        continued = mcp_server.continue_execution()
        assert "error" not in continued, continued
        status = _wait_for_stopped(timeout=15.0)
    finally:
        # list_breakpoints() itself requires the debugger to be stopped
        # (like every other bridge request) -- if the wait above timed out
        # with the debugger still running, it returns an {"ok": False, ...}
        # error dict rather than a list; guard against that so this cleanup
        # never masks the real failure with an unrelated TypeError from
        # iterating a dict's string keys as if they were breakpoint entries.
        existing_breakpoints = mcp_server.list_breakpoints()
        if isinstance(existing_breakpoints, list):
            for existing in existing_breakpoints:
                if existing["address"] == target:
                    mcp_server.delete_breakpoint(existing["id"])

    assert status["location"] == {"cs": cs, "eip": LANDING_OFFSET}
    assert "mov" in status["instruction"]["text"].lower()
    assert "1111" in status["instruction"]["text"]


def test_step_01_into_ordinary_instruction(cs):
    # A ("MOV AX,1111h") -> step_into() -> B ("MOV BX,2222h").
    result = mcp_server.step_into()
    assert "error" not in result, result
    assert result["stopped"] is True
    assert result["location"] == {"cs": cs, "eip": "010F"}
    assert "mov" in result["instruction"]["text"].lower()
    assert "2222" in result["instruction"]["text"]
    # AX was genuinely set by the real CPU decoder executing A, not
    # fabricated -- only the low 16 bits are defined by a 16-bit MOV.
    assert result["registers"]["eax"][-4:] == "1111"

    # Cross-check against an independently-implemented native method.
    cpu = mcp_server.get_cpu_state()
    assert cpu["eip"] == "010F"
    assert cpu["eax"][-4:] == "1111"


def test_step_02_into_reaches_call_func1(cs):
    # B ("MOV BX,2222h") -> step_into() -> CALL func1.
    result = mcp_server.step_into()
    assert "error" not in result, result
    assert result["location"] == {"cs": cs, "eip": CALL_FUNC1_OFFSET}
    assert "call" in result["instruction"]["text"].lower()
    assert result["registers"]["ebx"][-4:] == "2222"


def test_step_03_over_call_executes_subroutine_and_stops_after_it(cs):
    # Phase4D.md section 3: "execute the call/subroutine, stop at the
    # instruction after CALL" -- must NOT stop inside func1.
    result = mcp_server.step_over()
    assert "error" not in result, result
    assert result["stopped"] is True
    assert result["location"] == {"cs": cs, "eip": AFTER_CALL_FUNC1_OFFSET}, (
        "step_over() should stop at the instruction after CALL func1, "
        f"not inside func1 -- got {result['location']}"
    )
    assert "mov" in result["instruction"]["text"].lower()
    assert "3333" in result["instruction"]["text"]

    # The real proof the subroutine actually ran (not merely a disguised
    # step-into that happened to land past the call): func1's own
    # instruction ("MOV DX,4444h") only executes if RET was reached and
    # returned control here, so EDX must carry its real effect.
    assert result["registers"]["edx"][-4:] == "4444"


def test_step_04_debug_status_matches_cpu_state_and_current_instruction(cs):
    # Phase4D.md section 4: get_debug_status()/get_cpu_state()/
    # get_current_instruction() must all describe the SAME position after a
    # step -- cross-checking three independently-implemented native methods
    # against each other, without advancing execution any further.
    status = mcp_server.get_debug_status()
    cpu = mcp_server.get_cpu_state()
    instr = mcp_server.get_current_instruction()

    assert status["location"]["cs"] == cpu["cs"] == cs
    assert status["location"]["eip"] == cpu["eip"] == AFTER_CALL_FUNC1_OFFSET
    assert instr["address"] == f"{cs}:{AFTER_CALL_FUNC1_OFFSET}"
    assert status["instruction"]["text"] == instr["instruction"]
    assert is_hex(status["registers"]["eax"], 8)


def test_step_05_into_reaches_call_func2(cs):
    # C ("MOV CX,3333h") -> step_into() -> CALL func2.
    result = mcp_server.step_into()
    assert "error" not in result, result
    assert result["location"] == {"cs": cs, "eip": CALL_FUNC2_OFFSET}
    assert "call" in result["instruction"]["text"].lower()
    assert result["registers"]["ecx"][-4:] == "3333"


def test_step_06_into_the_call_enters_function_body(cs):
    # Contrast case for test_03 above: step_INTO (not step_over) on a CALL
    # must stop INSIDE the function, at its first instruction -- proving
    # step_into() and step_over() are genuinely different operations, not
    # aliases of each other.
    result = mcp_server.step_into()
    assert "error" not in result, result
    assert result["location"] == {"cs": cs, "eip": FUNC2_ENTRY_OFFSET}
    assert "mov" in result["instruction"]["text"].lower()
    assert "6666" in result["instruction"]["text"]
    # func2's own instruction has NOT executed yet -- we are stopped BEFORE
    # it, unlike step_03's post-call state where func1's effect was already
    # visible. EDI was never touched anywhere earlier in this test file.
    assert result["registers"]["edi"][-4:] != "6666"


def test_step_07_over_ordinary_instruction_behaves_like_step_into(cs):
    # step_over() on a non-call/int/loop/rep instruction (func2's own "MOV
    # DI,6666h") must behave exactly like step_into() -- StepOver()
    # (debug.cpp) falls through to a plain single step for anything that
    # isn't call/int/loop/rep.
    result = mcp_server.step_over()
    assert "error" not in result, result
    assert result["location"] == {"cs": cs, "eip": FUNC2_RET_OFFSET}
    assert "ret" in result["instruction"]["text"].lower()
    assert result["registers"]["edi"][-4:] == "6666"


def test_step_08_returns_from_function_to_after_call_func2(cs):
    # func2's RET is not call/int/loop/rep either, so step_into() here is
    # just an ordinary step -- but because it's a RET, that "ordinary step"
    # pops the real return address and resumes exactly after CALL func2,
    # proving func2 returned for real rather than the bridge fabricating a
    # position.
    result = mcp_server.step_into()
    assert "error" not in result, result
    assert result["location"] == {"cs": cs, "eip": AFTER_CALL_FUNC2_OFFSET}
    assert "mov" in result["instruction"]["text"].lower()
    assert "5555" in result["instruction"]["text"]


def test_step_09_into_while_already_running_returns_error():
    continued = mcp_server.continue_execution()
    assert "error" not in continued, continued
    try:
        result = mcp_server.step_into()
        assert result.get("ok") is False, result
        assert result["error"]["code"] == "ALREADY_RUNNING"
    finally:
        paused = mcp_server.pause_execution()
        assert "error" not in paused, paused


def test_step_10_over_while_already_running_returns_error():
    continued = mcp_server.continue_execution()
    assert "error" not in continued, continued
    try:
        result = mcp_server.step_over()
        assert result.get("ok") is False, result
        assert result["error"]["code"] == "ALREADY_RUNNING"
    finally:
        paused = mcp_server.pause_execution()
        assert "error" not in paused, paused
