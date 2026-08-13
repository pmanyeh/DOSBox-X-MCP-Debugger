"""
Shared Phase 5A scenario-setup helpers.

Positions a real, already-running DOSBox-X debugging session (see module
docstrings of tests/test_step_execution.py / tests/test_mcp_native_bridge.py
for how to launch one -- `-break-start drive_c\\STEP.COM` or `-break-start
drive_c\\TEST.COM`, no stdout/stderr redirection per ai/Phase4E-2.md) into
each Phase 5A scenario's documented initial state.

Reuses the SAME deterministic "catch the known program running, confirmed
by matching its real bytes at CS:0100" technique
tests/test_step_execution.py::_find_step_com_segment() and
tests/test_mcp_native_bridge.py::_find_test_com_segment() already
established (Phase 4C/4D) -- not a new mechanism, and talks to DOSBox-X
only through the Phase 5A restricted tool surface (ai/server_phase5a.py),
never a second, parallel debugger implementation.

All setup calls here happen BEFORE a scenario's "agent" (real or, for the
harness self-test, a scripted stand-in) is given control, and are not part
of the graded call trace -- tests/phase5a/grading.py grades only what
happens after `reset_call_log()` is called at the start of each scenario.
"""

import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "ai"))

import server_phase5a as s5a  # noqa: E402

HOST = "127.0.0.1"
PORT = 9876

# Identical byte listings to tests/test_step_execution.py /
# tests/test_mcp_native_bridge.py -- see those files' module docstrings for
# the full annotated assembly.
STEP_COM_BYTES = bytes(
    [
        0xBB, 0x40, 0x00, 0xB9, 0xFF, 0xFF, 0x90, 0xE2, 0xFD, 0x4B, 0x75, 0xF7,
        0xB8, 0x11, 0x11, 0xBB, 0x22, 0x22, 0xE8, 0x0D, 0x00, 0xB9, 0x33, 0x33,
        0xE8, 0x0B, 0x00, 0xBE, 0x55, 0x55, 0xB4, 0x4C, 0xCD, 0x21, 0xBA, 0x44,
        0x44, 0xC3, 0xBF, 0x66, 0x66, 0xC3,
    ]
)
TEST_COM_BYTES = bytes(
    [0xBB, 0x00, 0x10, 0xB9, 0xFF, 0xFF, 0x90, 0xE2, 0xFD, 0x4B, 0x75, 0xF7, 0xB4, 0x4C, 0xCD, 0x21]
)

LANDING_OFFSET = "010C"            # STEP.COM A: MOV AX,1111h
AFTER_A_OFFSET = "010F"            # STEP.COM B: MOV BX,2222h
CALL_FUNC1_OFFSET = "0112"         # STEP.COM CALL func1
FUNC1_ENTRY_OFFSET = "0122"        # STEP.COM func1: MOV DX,4444h
CALL_FUNC2_OFFSET = "0118"         # STEP.COM CALL func2
FUNC2_ENTRY_OFFSET = "0126"        # STEP.COM func2: MOV DI,6666h
AFTER_CALL_FUNC2_OFFSET = "011B"   # STEP.COM: MOV SI,5555h
TEST_COM_LOOP_OFFSET = "0106"      # TEST.COM inner: NOP


def bridge_available() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0):
            return True
    except OSError:
        return False


def wait_for_stopped(timeout: float = 15.0, interval: float = 0.05) -> dict:
    deadline = time.monotonic() + timeout
    status = None
    while time.monotonic() < deadline:
        status = s5a.verify.get_debug_status()
        assert "error" not in status, status
        if status.get("stopped"):
            return status
        time.sleep(interval)
    raise AssertionError(f"debugger did not stop within {timeout}s (last status: {status!r})")


def clear_all_breakpoints() -> None:
    for _ in range(100):
        bps = s5a.verify.list_breakpoints()
        if not bps:
            return
        s5a.delete_breakpoint(bps[0]["id"])
    raise RuntimeError("could not clear all breakpoints -- possible leak")


def find_step_com_segment(max_attempts: int = 25, settle: float = 0.2) -> str:
    for _ in range(max_attempts):
        status = s5a.verify.get_debug_status()
        if not status["stopped"]:
            status = s5a.pause_execution()
        cs = status["location"]["cs"]
        mem = s5a.read_memory(f"{cs}:0100", len(STEP_COM_BYTES))
        assert "error" not in mem, mem
        if bytes(int(b, 16) for b in mem["bytes"]) == STEP_COM_BYTES:
            return cs
        assert "error" not in s5a.continue_execution()
        time.sleep(settle)
    raise AssertionError(
        "drive_c/STEP.COM was never observed running -- was dosbox-x.exe launched as "
        "`dosbox-x.exe -break-start drive_c\\STEP.COM` (no stdout/stderr redirection)?"
    )


def find_test_com_segment(max_attempts: int = 25, settle: float = 0.2) -> str:
    for _ in range(max_attempts):
        status = s5a.verify.get_debug_status()
        if not status["stopped"]:
            status = s5a.pause_execution()
        cs = status["location"]["cs"]
        mem = s5a.read_memory(f"{cs}:0100", len(TEST_COM_BYTES))
        assert "error" not in mem, mem
        if bytes(int(b, 16) for b in mem["bytes"]) == TEST_COM_BYTES:
            return cs
        assert "error" not in s5a.continue_execution()
        time.sleep(settle)
    raise AssertionError(
        "drive_c/TEST.COM was never observed running -- was dosbox-x.exe launched as "
        "`dosbox-x.exe -break-start drive_c\\TEST.COM` (no stdout/stderr redirection)?"
    )


def position_step_com_at_offset(target_offset: str) -> str:
    """Lands on STEP.COM's post-loop entry point (A, LANDING_OFFSET) via
    breakpoint+continue -- the same technique Phase 4E's own acceptance
    test uses -- then walks forward with step_into() (pure setup, not part
    of any scenario's graded trace) until CS:EIP == target_offset. Because
    STEP.COM's control flow is strictly linear/forward (see
    tests/test_step_execution.py's module docstring), any offset from
    LANDING_OFFSET onward is reachable this way, including offsets INSIDE
    func1/func2 if ever needed. Returns STEP.COM's real load segment."""

    cs = find_step_com_segment()
    clear_all_breakpoints()
    target = f"{cs}:{LANDING_OFFSET}"
    bp = s5a.set_breakpoint(target)
    assert "error" not in bp, bp
    continued = s5a.continue_execution()
    assert "error" not in continued, continued
    status = wait_for_stopped(timeout=15.0)
    assert status["location"] == {"cs": cs, "eip": LANDING_OFFSET}, status
    clear_all_breakpoints()

    while status["location"]["eip"] != target_offset:
        status = s5a.step_into()
        assert "error" not in status, status
    return cs
