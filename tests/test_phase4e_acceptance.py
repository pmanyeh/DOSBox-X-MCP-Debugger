"""
Phase 4E end-to-end acceptance test (ai/Phase4E.md section 2 / ai/Phase4E-3.md).

Exercises the full production path -- MCP tool layer (ai/server.py) ->
DOSBoxClient (ai/dosbox_client.py) -> native AI bridge
(dosbox-src/src/debug/debug_ai.cpp) -> real, running DOSBox-X -- in ONE
continuous debugging session against drive_c/STEP.COM (the same
deterministic program tests/test_step_execution.py already validates
piece by piece; this file combines the full Phase4E.md section 2 sequence
into one acceptance run and prints before/after evidence for every
state-changing operation, per Phase4E.md section 3's "do not merely assert
success" requirement).

Requires DOSBox-X launched WITHOUT redirecting stdout/stderr (ai/Phase4E-2.md
found that redirection trips an unrelated, pre-existing undefined-behavior
path in DOSBox-X's own WIN32_Console()/ResizeConsole(), unrelated to this
project's AI bridge):

    dosbox-src\\bin\\x64\\Release\\dosbox-x.exe -break-start drive_c\\STEP.COM

launched with its normal interactive console/window, e.g. via PowerShell's
Start-Process with no -RedirectStandardOutput/-RedirectStandardError.

If the bridge isn't reachable, every test in this file is skipped rather
than hanging or failing with a confusing socket error.
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
        f"native DOSBox-X AI bridge not reachable at {HOST}:{PORT} -- start "
        f"dosbox-x.exe -break-start drive_c\\STEP.COM (no stdout/stderr "
        f"redirection) before running this acceptance test"
    ),
)

# Same STEP.COM layout as tests/test_step_execution.py (Phase 4D) -- see
# that file's module docstring for the full annotated assembly listing.
STEP_COM_BYTES = bytes(
    [
        0xBB, 0x40, 0x00, 0xB9, 0xFF, 0xFF, 0x90, 0xE2, 0xFD, 0x4B, 0x75, 0xF7,
        0xB8, 0x11, 0x11, 0xBB, 0x22, 0x22, 0xE8, 0x0D, 0x00, 0xB9, 0x33, 0x33,
        0xE8, 0x0B, 0x00, 0xBE, 0x55, 0x55, 0xB4, 0x4C, 0xCD, 0x21, 0xBA, 0x44,
        0x44, 0xC3, 0xBF, 0x66, 0x66, 0xC3,
    ]
)
LANDING_OFFSET = "010C"            # A: MOV AX,1111h -- first instr after the busy loop
AFTER_A_OFFSET = "010F"            # B: MOV BX,2222h
CALL_FUNC1_OFFSET = "0112"         # CALL func1 (E8 0D 00 -> target 0115+0x0D=0122)
FUNC1_ENTRY_OFFSET = "0122"        # func1: MOV DX,4444h
FUNC1_RET_OFFSET = "0125"          # func1's RET
AFTER_CALL_FUNC1_OFFSET = "0115"   # C: MOV CX,3333h -- instruction after CALL func1
CALL_FUNC2_OFFSET = "0118"         # CALL func2
AFTER_CALL_FUNC2_OFFSET = "011B"   # MOV SI,5555h -- instruction after CALL func2

SCRATCH_ADDRESS = "3000:0100"      # well away from STEP.COM's own load segment


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


def _evidence(step, expected, observed, ok):
    print(f"\n{step}\n  expected: {expected}\n  observed: {observed}\n  {'PASS' if ok else 'FAIL'}")
    assert ok, f"{step}: expected {expected!r}, observed {observed!r}"


def _wait_for_stopped(timeout=15.0, interval=0.05):
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


def test_phase4e_full_acceptance_workflow():
    # ---- 1-5: initial read-only inspection (pristine reset state) --------
    status = mcp_server.get_debug_status()
    _evidence("1. get_debug_status()", "stopped=True, real CS:EIP", status,
              "error" not in status and status["stopped"] is True)

    cpu = mcp_server.get_cpu_state()
    _evidence("2. get_cpu_state()", "real 32/16-bit register fields", cpu,
              "error" not in cpu and is_hex(cpu["eax"], 8) and is_hex(cpu["cs"], 4))

    instr = mcp_server.get_current_instruction()
    _evidence("3. get_current_instruction()", "non-empty real instruction", instr,
              "error" not in instr and bool(instr.get("instruction")))

    mem = mcp_server.read_memory(status["location"]["cs"] + ":" + status["location"]["eip"], 16)
    _evidence("4. read_memory()", "16 real bytes", mem,
              "error" not in mem and len(mem["bytes"]) == 16)

    disasm = mcp_server.disassemble(status["location"]["cs"] + ":" + status["location"]["eip"], 1)
    _evidence("5. disassemble()", "1 real instruction", disasm,
              isinstance(disasm, list) and len(disasm) == 1 and "address" in disasm[0])

    # ---- catch STEP.COM running (same technique as test_step_execution.py) ----
    cs = _find_step_com_segment()

    # ---- 6-14: breakpoint -> continue -> real breakpoint hit -------------
    target = f"{cs}:{LANDING_OFFSET}"
    bp = mcp_server.set_breakpoint(target)
    _evidence("6. set_breakpoint()", f"address={target}, enabled=True", bp,
              "error" not in bp and bp["address"] == target and bp["enabled"] is True)

    listing = mcp_server.list_breakpoints()
    _evidence("7. list_breakpoints()", f"[{target}]", listing,
              isinstance(listing, list) and any(b["address"] == target for b in listing))

    continued = mcp_server.continue_execution()
    _evidence("8. continue_execution()", "running=True, stopped=False", continued,
              "error" not in continued and continued["running"] is True)

    stopped_status = _wait_for_stopped()
    _evidence("9. real breakpoint hit (CPU execution, not fabricated)",
              f"CS:EIP == {target}",
              f"CS:EIP == {stopped_status['location']['cs']}:{stopped_status['location']['eip']}",
              stopped_status["location"] == {"cs": cs, "eip": LANDING_OFFSET})

    status2 = mcp_server.get_debug_status()
    _evidence("10. get_debug_status() after breakpoint", "stopped=True at landing", status2,
              status2["stopped"] is True and status2["location"]["eip"] == LANDING_OFFSET)

    cpu2 = mcp_server.get_cpu_state()
    _evidence("11. get_cpu_state() after breakpoint", f"eip={LANDING_OFFSET}", cpu2,
              cpu2["eip"] == LANDING_OFFSET)

    _evidence("12. CS:EIP matches expected breakpoint location",
              f"{cs}:{LANDING_OFFSET}", f"{cpu2['cs']}:{cpu2['eip']}",
              cpu2["cs"] == cs and cpu2["eip"] == LANDING_OFFSET)

    # ---- 13-15: write_register -> get_cpu_state confirms real change -----
    # ebp is never touched by STEP.COM itself, so any observed change is
    # unambiguously this write, not a coincidental program side effect.
    before_ebp = cpu2["ebp"]
    written = mcp_server.write_register("ebp", "0000BEEF")
    _evidence("13. write_register('ebp', '0000BEEF')", "register=ebp, value=0000BEEF", written,
              "error" not in written and written["value"] == "0000BEEF")

    cpu3 = mcp_server.get_cpu_state()
    _evidence("14. get_cpu_state() after write_register", "ebp=0000BEEF", cpu3,
              cpu3["ebp"] == "0000BEEF")
    _evidence("15. register change independently observed via get_cpu_state",
              f"ebp changed from {before_ebp} to 0000BEEF", cpu3["ebp"],
              cpu3["ebp"] == "0000BEEF" and cpu3["ebp"] != before_ebp)

    # ---- 16-18: write_memory -> read_memory confirms real change ---------
    written_mem = mcp_server.write_memory(SCRATCH_ADDRESS, [0xDE, 0xAD, 0xBE, 0xEF])
    _evidence("16. write_memory()", f"address={SCRATCH_ADDRESS}, length=4", written_mem,
              "error" not in written_mem and written_mem["length"] == 4)

    read_back = mcp_server.read_memory(SCRATCH_ADDRESS, 4)
    _evidence("17. read_memory()", "['DE','AD','BE','EF']", read_back,
              "error" not in read_back and read_back["bytes"] == ["DE", "AD", "BE", "EF"])
    _evidence("18. memory change independently observed via read_memory",
              "guest memory now DE AD BE EF", read_back["bytes"],
              read_back["bytes"] == ["DE", "AD", "BE", "EF"])

    # ---- 19-21: step_into on an ordinary instruction ----------------------
    step1 = mcp_server.step_into()
    _evidence("19-20. step_into() (A -> B, ordinary instruction) + get_cpu_state",
              f"CS:EIP={cs}:{AFTER_A_OFFSET}, eax ends 1111 (A's real effect)", step1,
              "error" not in step1 and step1["location"] == {"cs": cs, "eip": AFTER_A_OFFSET}
              and step1["registers"]["eax"][-4:] == "1111")
    _evidence("21. native state transition confirmed (real CPU decoder executed A)",
              "eax[-4:]=1111", step1["registers"]["eax"][-4:],
              step1["registers"]["eax"][-4:] == "1111")

    step2 = mcp_server.step_into()
    _evidence("step_into() (B -> CALL func1)", f"CS:EIP={cs}:{CALL_FUNC1_OFFSET}", step2,
              step2["location"] == {"cs": cs, "eip": CALL_FUNC1_OFFSET}
              and "call" in step2["instruction"]["text"].lower())

    # ---- 22-23: step_into on a CALL enters the callee ---------------------
    step3 = mcp_server.step_into()
    _evidence("22-23. step_into() on CALL func1 -> enters callee body",
              f"CS:EIP={cs}:{FUNC1_ENTRY_OFFSET} (inside func1, not past it)", step3,
              step3["location"] == {"cs": cs, "eip": FUNC1_ENTRY_OFFSET})

    step4 = mcp_server.step_into()  # func1's own MOV DX,4444h
    _evidence("step_into() executes func1's own instruction",
              "edx ends 4444", step4["registers"]["edx"][-4:],
              step4["location"] == {"cs": cs, "eip": FUNC1_RET_OFFSET}
              and step4["registers"]["edx"][-4:] == "4444")

    step5 = mcp_server.step_into()  # func1's RET -> back after CALL func1
    _evidence("step_into() on RET returns to caller (real return address popped)",
              f"CS:EIP={cs}:{AFTER_CALL_FUNC1_OFFSET}", step5,
              step5["location"] == {"cs": cs, "eip": AFTER_CALL_FUNC1_OFFSET})

    step6 = mcp_server.step_into()  # C: MOV CX,3333h -> CALL func2
    _evidence("24. position at another CALL (CALL func2)",
              f"CS:EIP={cs}:{CALL_FUNC2_OFFSET}", step6,
              step6["location"] == {"cs": cs, "eip": CALL_FUNC2_OFFSET}
              and "call" in step6["instruction"]["text"].lower()
              and step6["registers"]["ecx"][-4:] == "3333")

    # ---- 25-28: step_over on a CALL runs the callee for real, stops after -
    before_edi = step6["registers"]["edi"][-4:]
    step7 = mcp_server.step_over()
    _evidence("25-26. step_over() on CALL func2 + get_cpu_state",
              f"CS:EIP={cs}:{AFTER_CALL_FUNC2_OFFSET} (after the call, not inside it)", step7,
              "error" not in step7 and step7["location"] == {"cs": cs, "eip": AFTER_CALL_FUNC2_OFFSET})
    _evidence("27. CALL genuinely executed and execution stopped after it",
              "stopped=True, past func2", step7,
              step7["stopped"] is True and step7["location"]["eip"] == AFTER_CALL_FUNC2_OFFSET)
    _evidence("28. callee side effect observable (func2's own MOV DI,6666h really ran)",
              "edi ends 6666 (was %r before the call)" % before_edi, step7["registers"]["edi"][-4:],
              step7["registers"]["edi"][-4:] == "6666" and before_edi != "6666")

    # ---- 29-32: continue -> pause -> stopped ------------------------------
    continued2 = mcp_server.continue_execution()
    _evidence("29. continue_execution()", "running=True", continued2,
              "error" not in continued2 and continued2["running"] is True)

    paused = mcp_server.pause_execution()
    _evidence("30. pause_execution()", "stopped=True (genuine post-pause snapshot)", paused,
              "error" not in paused and paused["stopped"] is True)

    final_status = mcp_server.get_debug_status()
    _evidence("31-32. get_debug_status() final state", "stopped=True", final_status,
              final_status["stopped"] is True)


# ======================================================================
# Error propagation (Phase4E.md section 6 / Phase4E-3.md)
# ======================================================================


def test_error_propagation_already_running():
    assert mcp_server.get_debug_status()["stopped"] is True
    continued = mcp_server.continue_execution()
    assert "error" not in continued, continued
    try:
        result = mcp_server.continue_execution()
        _evidence("continue_execution() while already running",
                  "ok=False, error.code=ALREADY_RUNNING", result,
                  result.get("ok") is False and result["error"]["code"] == "ALREADY_RUNNING")
    finally:
        paused = mcp_server.pause_execution()
        assert "error" not in paused, paused


def test_error_propagation_already_stopped():
    assert mcp_server.get_debug_status()["stopped"] is True
    result = mcp_server.pause_execution()
    _evidence("pause_execution() while already stopped",
              "ok=False, error.code=ALREADY_STOPPED", result,
              result.get("ok") is False and result["error"]["code"] == "ALREADY_STOPPED")


def test_error_propagation_register_not_writable():
    result = mcp_server.write_register("eip", "00000000")
    _evidence("write_register('eip', ...) -- protected register",
              "ok=False, error.code=REGISTER_NOT_WRITABLE", result,
              result.get("ok") is False and result["error"]["code"] == "REGISTER_NOT_WRITABLE")


def test_error_propagation_memory_error_if_deterministic_case_exists():
    # Exploratory: try a handful of addresses likely to be outside mapped
    # guest RAM/ROM/UMB. This does not assert a specific address is
    # unmapped (that would be inventing an assumption the test program
    # doesn't establish) -- it only records what was observed, per
    # Phase4E.md section 9's "if a real deterministic case exists, use
    # it; otherwise report the gap" guidance applied to MEMORY_ERROR.
    candidates = ["D000:0000", "E000:0000", "9000:0000", "FFFF:FFFF"]
    found = None
    for addr in candidates:
        result = mcp_server.read_memory(addr, 1)
        if isinstance(result, dict) and result.get("ok") is False and result["error"]["code"] == "MEMORY_ERROR":
            found = addr
            break
    if found:
        _evidence(f"read_memory('{found}') -- unmapped guest memory",
                  "ok=False, error.code=MEMORY_ERROR", found, True)
    else:
        print(
            "\nNo MEMORY_ERROR deterministic case found among candidate addresses "
            f"{candidates} on this run (all were mapped guest memory) -- "
            "known test gap, not a failure; MEMORY_ERROR's code path itself "
            "(debug_ai.cpp mem_readb_checked() fault handling) is documented "
            "but not exercised by this acceptance run."
        )
