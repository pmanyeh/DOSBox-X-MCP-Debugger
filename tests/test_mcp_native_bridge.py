"""
Integration test: MCP tool layer -> DOSBoxClient -> native AI bridge ->
real, running DOSBox-X (Phase 3C).

Unlike tests/test_debugger.py (which exercises FakeDOSBoxDebugger only)
and tests/test_native_bridge.py (which talks to the native bridge's raw
TCP protocol directly), this file calls the actual ai/server.py MCP tool
functions -- the same functions an AI agent would invoke over MCP -- and
requires a real DOSBox-X instance with the native AI bridge listening on
127.0.0.1:9876. FakeDOSBoxDebugger is intentionally not used here.

Start DOSBox-X before running this file:

    dosbox-src\\bin\\x64\\Release\\dosbox-x.exe -break-start

If the bridge isn't reachable, every test in this file is skipped rather
than hanging or failing with a confusing socket error.
"""

import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

import pytest

import server as mcp_server  # noqa: E402  (import after sys.path insert)
from dosbox_client import DOSBoxClient  # noqa: E402

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
        f"start dosbox-x.exe -break-start before running this integration test"
    ),
)


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


def test_get_debug_status_returns_real_state():
    status = mcp_server.get_debug_status()
    assert "error" not in status, status
    assert isinstance(status["stopped"], bool)
    assert is_hex(status["location"]["cs"], 4)
    assert is_hex(status["location"]["eip"], 4)
    assert status["instruction"]["text"]
    assert is_hex(status["registers"]["eax"], 8)
    assert is_hex(status["segments"]["ss"], 4)


def test_get_cpu_state_returns_real_registers():
    cpu = mcp_server.get_cpu_state()
    assert "error" not in cpu, cpu
    for key in ("eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp", "eflags"):
        assert is_hex(cpu[key], 8), f"{key} = {cpu.get(key)!r}"
    for key in ("cs", "ds", "es", "ss", "fs", "gs", "eip"):
        assert is_hex(cpu[key], 4), f"{key} = {cpu.get(key)!r}"


def test_get_current_instruction_matches_known_reset_state():
    # This asserts against DOSBox-X's well-known CPU reset state
    # (CS:EIP = F000:FFF0, a far JMP to F000:E05B) as a TEST EXPECTATION
    # for that known startup condition when launched with -break-start --
    # it is not something the implementation hard-codes. See
    # docs/dosbox-ai-bridge.md and AGENTS.md section 9 for this value.
    instr = mcp_server.get_current_instruction()
    assert "error" not in instr, instr
    assert instr["address"] == "F000:FFF0"
    assert "f000:e05b" in instr["instruction"].lower()


def test_read_memory_reads_real_bytes():
    result = mcp_server.read_memory("F000:FFF0", 16)
    assert "error" not in result, result
    assert result["address"] == "F000:FFF0"
    assert result["length"] == 16
    assert len(result["bytes"]) == 16
    assert all(is_hex(b, 2) for b in result["bytes"])
    # The reset vector is a far JMP: opcode EA followed by offset:segment.
    assert result["bytes"][0] == "EA"


def test_disassemble_matches_known_reset_state():
    listing = mcp_server.disassemble("F000:FFF0", 1)
    assert isinstance(listing, list) and len(listing) == 1
    assert listing[0]["address"] == "F000:FFF0"
    assert "jmp" in listing[0]["instruction"].lower()


def test_debug_status_and_cpu_state_agree_on_live_registers():
    # Cross-check two independently-implemented native methods (debug.status
    # and cpu.get) against each other -- if either returned fabricated data
    # instead of live cpu_regs/Segs, these would very likely disagree.
    status = mcp_server.get_debug_status()
    cpu = mcp_server.get_cpu_state()
    assert status["location"]["cs"] == cpu["cs"]
    assert status["location"]["eip"] == cpu["eip"]
    assert status["registers"]["eax"] == cpu["eax"]
    assert status["registers"]["esp"] == cpu["esp"]
    assert status["segments"]["ss"] == cpu["ss"]


# ======================================================================
# Phase 4A: memory.write / register.write (real write access)
# ======================================================================


def test_memory_write_read_round_trip():
    # Use a scratch address well away from the reset vector/BIOS date
    # string other tests in this file read, so tests can run in any order.
    address = "2000:0100"
    written = mcp_server.write_memory(address, [0xDE, 0xAD, 0xBE, 0xEF])
    assert "error" not in written, written
    assert written["address"] == address
    assert written["length"] == 4

    read_back = mcp_server.read_memory(address, 4)
    assert "error" not in read_back, read_back
    assert read_back["bytes"] == ["DE", "AD", "BE", "EF"]


def test_memory_write_accepts_hex_strings_too():
    address = "2000:0200"
    written = mcp_server.write_memory(address, ["12", "34", "56"])
    assert "error" not in written, written

    read_back = mcp_server.read_memory(address, 3)
    assert read_back["bytes"] == ["12", "34", "56"]


def test_register_write_read_round_trip():
    original = mcp_server.get_cpu_state()["ebx"]
    try:
        written = mcp_server.write_register("ebx", "0000ABCD")
        assert "error" not in written, written
        assert written["register"] == "ebx"
        assert written["value"] == "0000ABCD"

        cpu = mcp_server.get_cpu_state()
        assert cpu["ebx"] == "0000ABCD"
    finally:
        mcp_server.write_register("ebx", original)


def test_register_write_is_case_insensitive():
    original = mcp_server.get_cpu_state()["ecx"]
    try:
        written = mcp_server.write_register("ECX", "00000042")
        assert "error" not in written, written
        assert mcp_server.get_cpu_state()["ecx"] == "00000042"
    finally:
        mcp_server.write_register("ecx", original)


def test_memory_write_invalid_address_returns_error():
    result = mcp_server.write_memory("not-an-address", [0x00])
    assert result.get("ok") is False, result
    assert result["error"]["code"] == "INVALID_PARAMETER"


def test_register_write_invalid_register_name_returns_error():
    result = mcp_server.write_register("zzz", "00000000")
    assert result.get("ok") is False, result
    assert result["error"]["code"] == "INVALID_PARAMETER"


@pytest.mark.parametrize("blocked", ["eip", "cs", "ds", "es", "ss", "fs", "gs", "esp", "eflags"])
def test_register_write_blocked_register_returns_error(blocked):
    # These registers are deliberately excluded from Phase 4A's write
    # whitelist (Phase4A.md) because writing them could desync execution.
    result = mcp_server.write_register(blocked, "00000000")
    assert result.get("ok") is False, result
    assert result["error"]["code"] == "REGISTER_NOT_WRITABLE"


def test_memory_write_invalid_data_returns_error():
    # 256 is out of byte range (0-255).
    result = mcp_server.write_memory("2000:0300", [256])
    assert result.get("ok") is False, result
    assert result["error"]["code"] == "INVALID_PARAMETER"


def test_register_write_invalid_value_returns_error():
    result = mcp_server.write_register("eax", "not-hex")
    assert result.get("ok") is False, result
    assert result["error"]["code"] == "INVALID_PARAMETER"


def test_concurrent_writes_on_separate_connections_do_not_cross_talk():
    # Not a proof of the C++ implementation's thread safety, but the
    # practical, testable proxy for it at this layer: hammer the bridge
    # with interleaved requests from several independent connections at
    # once and confirm every response still matches its own request (no
    # id cross-talk) and every write actually lands correctly.
    #
    # Each thread is given its OWN dedicated register (there are 7
    # writable registers -- see WRITABLE_REGISTERS in debug_ai.cpp -- and
    # we use 5 of them here). This deliberately avoids the invalid
    # assumption that one thread's write to a register would still be
    # there when it reads back after other threads have also been
    # writing that SAME shared register concurrently -- with only one set
    # of registers in the whole emulator, "last writer wins" on a shared
    # register is correct, expected behavior, not a bug. Per-thread
    # dedicated registers isolate what's actually being tested here: the
    # request queue's ability to serialize many concurrent connections'
    # requests onto the emulator thread without corrupting or
    # misdelivering any of them.
    registers = ["eax", "ebx", "ecx", "edx", "esi"]
    writes_per_register = 20
    errors = []

    def worker(register):
        try:
            client = DOSBoxClient()
            for value in range(writes_per_register):
                result = client.write_register(register, value)
                assert result["register"] == register
                assert result["value"] == f"{value:08X}"

                status = client.get_debug_status()
                assert status["registers"][register] == f"{value:08X}"
            client.close()
        except Exception as e:  # noqa: BLE001 -- surfaced via `errors` below
            errors.append((register, e))

    threads = [threading.Thread(target=worker, args=(r,)) for r in registers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    assert all(not t.is_alive() for t in threads)

    # Final sanity check: every register landed on the last value its own
    # (and only its own) thread wrote -- no cross-register corruption.
    final_cpu = mcp_server.get_cpu_state()
    expected_final = f"{writes_per_register - 1:08X}"
    for register in registers:
        assert final_cpu[register] == expected_final, register


# ======================================================================
# Phase 4B: breakpoint.set / breakpoint.delete / breakpoint.list
# ======================================================================


def _clear_all_breakpoints():
    # No native "delete all" is wired up for the bridge (Phase 4B only
    # exposes set/delete/list) -- repeatedly delete whatever is first in
    # the current list until none remain. Safe regardless of id shifting
    # since we always re-fetch the current list before each delete.
    for _ in range(100):
        bps = mcp_server.list_breakpoints()
        if not bps:
            return
        mcp_server.delete_breakpoint(bps[0]["id"])
    raise RuntimeError("could not clear all breakpoints -- possible leak")


@pytest.fixture(autouse=True)
def _clean_breakpoints():
    # Keeps every test in this file isolated from breakpoints left behind
    # by another test (or a human poking the same live DOSBox-X instance
    # through the GUI during this session).
    _clear_all_breakpoints()
    yield
    _clear_all_breakpoints()


def test_list_breakpoints_initially_empty():
    assert mcp_server.list_breakpoints() == []


def test_set_breakpoint_returns_address_and_enabled():
    result = mcp_server.set_breakpoint("1234:0100")
    assert "error" not in result, result
    assert result["address"] == "1234:0100"
    assert result["enabled"] is True
    assert isinstance(result["id"], int)


def test_set_then_list_breakpoint():
    created = mcp_server.set_breakpoint("1234:0200")
    listing = mcp_server.list_breakpoints()
    assert len(listing) == 1
    assert listing[0]["id"] == created["id"]
    assert listing[0]["address"] == "1234:0200"
    assert listing[0]["enabled"] is True


def test_set_delete_then_list_again():
    created = mcp_server.set_breakpoint("1234:0300")
    assert len(mcp_server.list_breakpoints()) == 1

    deleted = mcp_server.delete_breakpoint(created["id"])
    assert "error" not in deleted, deleted
    assert deleted["deleted"] is True

    assert mcp_server.list_breakpoints() == []


def test_delete_nonexistent_breakpoint_returns_error():
    result = mcp_server.delete_breakpoint(9999)
    assert result.get("ok") is False, result
    assert result["error"]["code"] == "BREAKPOINT_NOT_FOUND"


def test_set_breakpoint_invalid_address_returns_error():
    result = mcp_server.set_breakpoint("not-an-address")
    assert result.get("ok") is False, result
    assert result["error"]["code"] == "INVALID_ADDRESS"


def test_duplicate_breakpoint_rejected():
    # Defines Phase4B.md's "duplicate breakpoint behavior" test item: the
    # bridge rejects a second breakpoint.set at an address that already
    # has one (a deliberate bridge-level policy choice reusing the
    # existing IsBreakpoint() check -- see docs/dosbox-ai-bridge.md; the
    # GUI's own BP command has no such guard and permits duplicates).
    first = mcp_server.set_breakpoint("1234:0400")
    assert "error" not in first, first

    second = mcp_server.set_breakpoint("1234:0400")
    assert second.get("ok") is False, second
    assert second["error"]["code"] == "BREAKPOINT_ALREADY_EXISTS"

    assert len(mcp_server.list_breakpoints()) == 1


def test_multiple_breakpoints_independent_addresses():
    mcp_server.set_breakpoint("2000:0010")
    mcp_server.set_breakpoint("2000:0020")
    mcp_server.set_breakpoint("2000:0030")

    listing = mcp_server.list_breakpoints()
    addresses = {bp["address"] for bp in listing}
    assert addresses == {"2000:0010", "2000:0020", "2000:0030"}

    target = next(bp for bp in listing if bp["address"] == "2000:0020")
    mcp_server.delete_breakpoint(target["id"])

    remaining = {bp["address"] for bp in mcp_server.list_breakpoints()}
    assert remaining == {"2000:0010", "2000:0030"}


# ======================================================================
# Phase 4C: execution.continue / execution.pause (real execution control)
#
# Every test above this point relies on DOSBox-X sitting untouched at its
# post-reset breakpoint (CS:EIP = F000:FFF0, per -break-start) -- nothing
# before Phase 4C ever resumed the guest CPU. The tests below are the
# first to actually call continue_execution(), which permanently moves
# CS:EIP for the rest of this process's lifetime -- hence they are ordered
# last in this file, after every test that depends on the pristine reset
# state (e.g. test_get_current_instruction_matches_known_reset_state).
#
# The breakpoint+continue test below additionally requires dosbox-x.exe to
# have been launched as:
#
#     dosbox-x.exe -break-start drive_c\TEST.COM
#
# (still stopped at F000:FFF0 initially -- -break-start's normal behavior,
# so every test above this point is unaffected -- but with TEST.COM queued
# to auto-run once the reset vector is continued past.) This matters
# because DOSBox-X's BIOS ROM (segment F000, and likely other ROM
# segments) silently discards writes -- confirmed empirically: writing to
# F000:E05B (the reset vector's own jump target) via write_memory()
# reports success but a follow-up read_memory() shows the byte unchanged.
# ActivateBreakpoints()'s 0xCC trap patch is therefore a no-op anywhere in
# ROM, so a physical breakpoint can only ever fire in genuine, writable
# guest RAM -- exactly the same limitation the debugger GUI's own BP
# command has (it patches memory the same way). Simply continuing from
# F000:FFF0 with no auto-run program configured was also observed to
# settle into a ROM "wait for input" idle loop (repeatedly sampled at
# F000:D186, an IRET) rather than ever reaching DOS -- -break-start enters
# the debugger at the raw CPU reset vector, a lower-level entry point than
# DOSBox-X's internal-DOS boot shortcut, so a real, writable-RAM breakpoint
# target requires actually running a program, per AGENTS.md section 26/27.
#
# drive_c/TEST.COM (created for Phase 4C) is the hand-assembled machine
# code for:
#
#     ORG 100h
#             MOV BX, 1000h
#     outer:  MOV CX, 0FFFFh
#     inner:  NOP                 ; breakpoint target below: CS:0106
#             LOOP inner
#             DEC BX
#             JNZ outer
#             MOV AH, 4Ch
#             INT 21h
#
# i.e. bytes BB 00 10 B9 FF FF 90 E2 FD 4B 75 F7 B4 4C CD 21 -- roughly
# 0x1000 * 0xFFFF (~268 million) NOP/LOOP iterations, deliberately long so
# there is always a wide, easily-hit window for a breakpoint placed at the
# loop body (CS:0106) regardless of exact timing.
# ======================================================================

TEST_COM_BYTES = bytes(
    [0xBB, 0x00, 0x10, 0xB9, 0xFF, 0xFF, 0x90, 0xE2, 0xFD, 0x4B, 0x75, 0xF7, 0xB4, 0x4C, 0xCD, 0x21]
)
TEST_COM_LOOP_OFFSET = "0106"  # CS:0106 -- the "inner:" NOP, see module docstring above


def _wait_for_stopped(timeout=5.0, interval=0.05):
    """Poll get_debug_status() until it reports stopped, rather than
    assuming a fixed sleep was long enough (Phase4C.md section 9: "Do not
    rely only on a timeout")."""

    deadline = time.monotonic() + timeout
    status = None
    while time.monotonic() < deadline:
        status = mcp_server.get_debug_status()
        assert "error" not in status, status
        if status.get("stopped"):
            return status
        time.sleep(interval)
    raise AssertionError(f"debugger did not stop within {timeout}s (last status: {status!r})")


def _find_test_com_segment(max_attempts=25, settle=0.2):
    """Repeatedly continue/pause until the CPU is caught inside
    drive_c/TEST.COM's own busy loop, confirmed by matching the real bytes
    at CS:0100 against TEST_COM_BYTES (not merely "CS looks plausible") --
    proving TEST.COM genuinely auto-ran, and returning its real, DOS-
    assigned load segment, which varies run to run and is therefore
    discovered here rather than hardcoded anywhere."""

    for _ in range(max_attempts):
        status = mcp_server.get_debug_status()
        if not status["stopped"]:
            status = mcp_server.pause_execution()
        cs = status["location"]["cs"]
        mem = mcp_server.read_memory(f"{cs}:0100", len(TEST_COM_BYTES))
        assert "error" not in mem, mem
        if bytes(int(b, 16) for b in mem["bytes"]) == TEST_COM_BYTES:
            return cs
        assert "error" not in mcp_server.continue_execution()
        time.sleep(settle)
    raise AssertionError(
        "drive_c/TEST.COM was never observed running -- was dosbox-x.exe launched as "
        "`dosbox-x.exe -break-start drive_c\\TEST.COM`?"
    )


def test_pause_while_already_stopped_returns_error():
    assert mcp_server.get_debug_status()["stopped"] is True
    result = mcp_server.pause_execution()
    assert result.get("ok") is False, result
    assert result["error"]["code"] == "ALREADY_STOPPED"


def test_debug_status_running_field_is_inverse_of_stopped_while_stopped():
    status = mcp_server.get_debug_status()
    assert status["stopped"] is True
    assert status["running"] is False


def test_breakpoint_continue_hits_known_program_loop():
    # Phase4C.md section 9's "deterministic test program... where a known
    # instruction address can be executed" -- see the module-level comment
    # above for why drive_c/TEST.COM (a real, writable-RAM DOS program) is
    # used instead of a ROM address.
    cs = _find_test_com_segment()
    target = f"{cs}:{TEST_COM_LOOP_OFFSET}"

    bp = mcp_server.set_breakpoint(target)
    assert "error" not in bp, bp

    continued = mcp_server.continue_execution()
    assert "error" not in continued, continued
    assert continued["stopped"] is False
    assert continued["running"] is True

    status = _wait_for_stopped(timeout=5.0)
    assert status["location"]["cs"] == cs
    assert status["location"]["eip"] == TEST_COM_LOOP_OFFSET
    assert status["instruction"]["text"].strip().lower() == "nop"
    assert is_hex(status["registers"]["eax"], 8)

    # Cross-check against two independently-implemented native methods,
    # exactly as test_debug_status_and_cpu_state_agree_on_live_registers()
    # does above -- proves the breakpoint genuinely stopped real DOSBox-X
    # execution rather than the response being fabricated.
    instr = mcp_server.get_current_instruction()
    assert "error" not in instr, instr
    assert instr["address"] == target

    cpu = mcp_server.get_cpu_state()
    assert "error" not in cpu, cpu
    assert cpu["cs"] == cs and cpu["eip"] == TEST_COM_LOOP_OFFSET


def test_continue_while_already_running_returns_error():
    continued = mcp_server.continue_execution()
    assert "error" not in continued, continued
    try:
        second = mcp_server.continue_execution()
        assert second.get("ok") is False, second
        assert second["error"]["code"] == "ALREADY_RUNNING"
    finally:
        # Leave the debugger stopped again for every test after this one.
        paused = mcp_server.pause_execution()
        assert "error" not in paused, paused


def test_continue_then_pause_reaches_running_then_stopped():
    assert mcp_server.get_debug_status()["stopped"] is True

    continued = mcp_server.continue_execution()
    assert "error" not in continued, continued
    assert continued["running"] is True

    # DEBUG_AI_DoContinue() already resumed the guest CPU synchronously by
    # the time continue_execution() returned above -- confirm with an
    # independent status read rather than assuming the RPC's own "ok"
    # implied the CPU state, per Phase4C.md section 8: "Do not assume that
    # receiving a successful RPC response means the CPU stopped" (the same
    # discipline applies symmetrically to "started").
    running_status = mcp_server.get_debug_status()
    assert running_status["stopped"] is False
    assert running_status["running"] is True

    paused = mcp_server.pause_execution()
    assert "error" not in paused, paused
    assert paused["stopped"] is True
    assert is_hex(paused["registers"]["eax"], 8)

    stopped_status = mcp_server.get_debug_status()
    assert stopped_status["stopped"] is True
    assert is_hex(stopped_status["registers"]["eax"], 8)


def test_concurrent_continue_and_status_do_not_deadlock():
    # Phase4C.md section 10: connection A calls continue while connection B
    # concurrently polls status. Must not deadlock, crash, corrupt state,
    # or lose either request -- exact interleaving/ordering between the two
    # connections is not guaranteed by the protocol and is deliberately
    # not asserted here (mirroring Phase4B.md section 8's guidance not to
    # assume a particular ordering the protocol doesn't promise).
    assert mcp_server.get_debug_status()["stopped"] is True

    client_a = DOSBoxClient()
    client_b = DOSBoxClient()
    results = {}
    errors = []

    def do_continue():
        try:
            results["continue"] = client_a.continue_execution()
        except Exception as e:  # noqa: BLE001 -- surfaced via `errors` below
            errors.append(("continue", e))

    def do_status():
        try:
            results["status"] = client_b.get_debug_status()
        except Exception as e:  # noqa: BLE001
            errors.append(("status", e))

    try:
        t_a = threading.Thread(target=do_continue)
        t_b = threading.Thread(target=do_status)
        t_a.start()
        t_b.start()
        t_a.join(timeout=10)
        t_b.join(timeout=10)

        assert not errors, errors
        assert not t_a.is_alive() and not t_b.is_alive()
        assert "continue" in results and "status" in results
        assert isinstance(results["status"]["stopped"], bool)
    finally:
        client_a.close()
        client_b.close()
        # Regardless of how the race above resolved, leave the debugger
        # stopped again for every test after this one.
        if mcp_server.get_debug_status()["stopped"] is False:
            mcp_server.pause_execution()


def test_concurrent_pause_and_status_do_not_deadlock():
    # Phase4C.md section 10, second scenario: connection A calls pause
    # while connection B concurrently polls status.
    assert mcp_server.get_debug_status()["stopped"] is True
    continued = mcp_server.continue_execution()
    assert "error" not in continued, continued

    client_a = DOSBoxClient()
    client_b = DOSBoxClient()
    results = {}
    errors = []

    def do_pause():
        try:
            results["pause"] = client_a.pause_execution()
        except Exception as e:  # noqa: BLE001
            errors.append(("pause", e))

    def do_status():
        try:
            results["status"] = client_b.get_debug_status()
        except Exception as e:  # noqa: BLE001
            errors.append(("status", e))

    try:
        t_a = threading.Thread(target=do_pause)
        t_b = threading.Thread(target=do_status)
        t_a.start()
        t_b.start()
        t_a.join(timeout=10)
        t_b.join(timeout=10)

        assert not errors, errors
        assert not t_a.is_alive() and not t_b.is_alive()
        assert "pause" in results and "status" in results
        assert results["pause"]["stopped"] is True
    finally:
        client_a.close()
        client_b.close()

    assert mcp_server.get_debug_status()["stopped"] is True


def test_concurrent_breakpoint_set_no_corruption():
    # Practical, testable proxy for thread safety at this layer (per
    # Phase4B.md section 8): have several independent connections set
    # breakpoints at distinct addresses AT THE SAME TIME and verify the
    # final list contains exactly what was requested -- no lost updates,
    # no duplicate/corrupted entries, no crash, and a deterministic
    # response shape from every connection.
    #
    # This deliberately does NOT interleave concurrent set+delete
    # round trips on the same breakpoint from multiple connections: an
    # earlier version of this test did, and it failed -- not because of
    # data corruption or a crash, but because it assumed
    # set -> list -> delete was atomic per connection. It isn't: because
    # breakpoint ids are positions in ONE list shared by every connection
    # (see docs/dosbox-ai-bridge.md "Breakpoint management (Phase 4B)"),
    # another connection's set/delete can shift positions in between this
    # connection's own list and delete calls, same as it would for a
    # human re-using a stale BPLIST number after someone else changes the
    # list. That's exactly the "particular ordering the protocol doesn't
    # guarantee" Phase4B.md section 8 says not to test for. Cleanup here
    # is single-threaded, via the _clean_breakpoints fixture, after the
    # concurrent phase completes.
    n_threads = 8
    errors = []
    addresses = [f"4000:{i:02X}00" for i in range(n_threads)]

    def worker(thread_index):
        try:
            client = DOSBoxClient()
            address = addresses[thread_index]
            created = client.set_breakpoint(address)
            assert created["address"] == address
            assert created["enabled"] is True
            assert isinstance(created["id"], int)
            client.close()
        except Exception as e:  # noqa: BLE001 -- surfaced via `errors` below
            errors.append((thread_index, e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    assert all(not t.is_alive() for t in threads)

    listing = mcp_server.list_breakpoints()
    assert {bp["address"] for bp in listing} == set(addresses)
    assert len({bp["id"] for bp in listing}) == n_threads  # every id unique -- no corruption
