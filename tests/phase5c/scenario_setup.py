"""
Phase 5C -- C4 scenario positioning (orchestrator-side setup only, never
part of any C4-B* scenario's graded trace -- the same convention
tests/phase5a/real_agent_setup.py and docs/phase5b-b3-b5-revision.md's own
"Positioning for the revised scenario" section already establish).

Positions a real, live DOSBox-X instance into each C4-B* scenario's
documented `initial_state_description` (tests/phase5b/scenarios.py,
unchanged) BEFORE a fresh agent process is spawned, reusing
tests/phase5a/dosbox_session.py's existing primitives -- never a second,
parallel debugger implementation. Every position here also launches a
genuinely FRESH DOSBox-X process first (STEP.COM's and TEST.COM's control
flow are strictly linear/forward -- tests/phase5a/dosbox_session.py's own
module docstring -- so B1/B2 cannot share one running STEP.COM instance,
and neither can B3/B4 share one TEST.COM instance, without one scenario's
positioning consuming forward progress another scenario also needs), the
same "separate live launches per scenario" convention
tests/phase5b/test_bounded_agent_cli_real_dosbox.py's own module docstring
and every real-agent campaign before it already used.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "ai"))
sys.path.insert(0, str(_ROOT))

import server_phase5a as s5a  # noqa: E402 -- unrecorded positioning only

from tests.phase5a import dosbox_session as ds  # noqa: E402

DOSBOX_EXE = _ROOT / "dosbox-src" / "bin" / "x64" / "Release" / "dosbox-x.exe"
DOSBOX_CONF = _ROOT / "dosbox-src" / "bin" / "x64" / "Release" / "dosbox-x.conf"

# Observed startup-timing flake (this session's own diagnosis): a short
# wait after launch can catch DOSBox-X mid-BIOS-POST (CS:EIP = F000:FFF0,
# the real-mode reset vector) before DOS/the .COM has even loaded, which
# then drives find_step_com_segment()/find_test_com_segment()'s own
# bounded retry loop past the program entirely. 12s was sufficient every
# time in this session's own testing; kept as a fixed, generous margin
# rather than a tuned minimum.
_BOOT_WAIT_SECONDS = 15.0
_BRIDGE_POLL_SECONDS = 20.0

# The flake can also manifest AFTER the bridge is up (BIOS POST/DOS boot
# genuinely still in progress despite a TCP-level connection succeeding),
# observed in this session as find_step_com_segment()/find_test_com_segment()
# exhausting their own 25-attempt retry loop. Each retry here is a full,
# fresh dosbox-x.exe relaunch -- an infrastructure retry, never a silent
# re-use of a half-booted process.
_MAX_LAUNCH_ATTEMPTS = 3


def _bridge_up() -> bool:
    try:
        with socket.create_connection((ds.HOST, ds.PORT), timeout=1.0):
            return True
    except OSError:
        return False


def _kill_dosbox() -> None:
    subprocess.run(
        ["taskkill", "/F", "/IM", "dosbox-x.exe"],
        shell=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # give the OS a moment to release the TCP port before rebinding.
    deadline = time.monotonic() + 5.0
    while _bridge_up() and time.monotonic() < deadline:
        time.sleep(0.5)


def launch_fresh_dosbox(program: str) -> None:
    """Kills any existing dosbox-x.exe, launches a genuinely fresh instance
    with `-break-start drive_c\\<program>` (no stdout/stderr redirection,
    matching every prior live test in this project), and waits for both
    the boot flake margin and the native bridge to come up."""

    _kill_dosbox()
    # A direct subprocess.Popen([DOSBOX_EXE, ...]) launch was observed in
    # this session to exit immediately (returncode 8, no window, no bridge)
    # for reasons not fully diagnosed -- Start-Process (via a real,
    # non-shell-string argument list of its own) is the mechanism already
    # proven reliable, repeatedly, earlier in this same session, so it is
    # used here rather than continuing to chase the direct-Popen path.
    # This still launches dosbox-x.exe with a literal argument array (no
    # shell interpretation of the DOSBox-X command line itself); only the
    # launcher-of-the-launcher is PowerShell.
    ps_command = (
        f"Start-Process -FilePath '{DOSBOX_EXE}' "
        f"-ArgumentList '-conf','{DOSBOX_CONF}','-break-start','drive_c\\{program}' "
        f"-WorkingDirectory '{_ROOT}'"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_command],
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30.0,
    )
    time.sleep(_BOOT_WAIT_SECONDS)
    deadline = time.monotonic() + _BRIDGE_POLL_SECONDS
    while not _bridge_up():
        if time.monotonic() > deadline:
            raise AssertionError(f"native DOSBox-X AI bridge never came up at {ds.HOST}:{ds.PORT} after launch")
        time.sleep(1.0)


def _with_relaunch_retry(program: str, body):
    """Runs `body()` against a genuinely fresh dosbox-x.exe launch,
    retrying the WHOLE launch (never reusing a half-booted process) up to
    _MAX_LAUNCH_ATTEMPTS times if the known `-break-start` startup flake
    (docs/phase5b-b3-b5-revision.md's own live testing already encountered
    this class of timing flake; this session's own diagnosis: DOS/the .COM
    not yet loaded despite the TCP bridge already accepting connections)
    prevents `body` from ever identifying the expected program. Each
    attempt is a distinct, reported infrastructure retry -- never a silent
    reuse of prior (possibly corrupted) state."""

    last_error: Exception | None = None
    for attempt in range(1, _MAX_LAUNCH_ATTEMPTS + 1):
        launch_fresh_dosbox(program)
        try:
            return body()
        except Exception as e:
            # Deliberately broad: this session's own campaign4 run hit the
            # SAME underlying flake (DOS/the .COM not genuinely ready
            # despite the TCP bridge already accepting connections)
            # surfacing as a KeyError inside find_step_com_segment() (a
            # native-bridge error envelope lacking "stopped", read via
            # s5a.verify.get_debug_status()), not only as an
            # AssertionError -- narrowing this to one exception type
            # already proved insufficient once. Bounded to
            # _MAX_LAUNCH_ATTEMPTS, and every attempt is a full, fresh
            # dosbox-x.exe relaunch, never a silent retry against
            # possibly-corrupted state.
            last_error = e
            continue
    raise AssertionError(
        f"positioning for {program!r} failed after {_MAX_LAUNCH_ATTEMPTS} fresh dosbox-x.exe launches "
        f"(known -break-start startup flake) -- last error: {last_error!r}"
    )


def position_c4_b1() -> dict:
    """B1: STEP.COM stopped at LANDING_OFFSET (010C, `MOV AX,1111h`, not
    yet executed) -- same technique
    tests/phase5a/real_agent_setup.py::setup_1_inspection() already uses."""

    return _with_relaunch_retry("STEP.COM", _position_c4_b1_body)


def _position_c4_b1_body() -> dict:
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
    return s5a.verify.get_debug_status()


def position_c4_b2() -> dict:
    """B2: STEP.COM stopped at CALL_FUNC1_OFFSET (0112, `CALL func1`, not
    yet executed) -- lands at LANDING_OFFSET first (same technique as B1,
    on its OWN fresh STEP.COM launch), then walks forward with step_into()
    (unrecorded setup, not part of any scenario's graded trace) --
    identical technique tests/phase5a/real_agent_setup.py::
    setup_2_identification() already uses."""

    return _with_relaunch_retry("STEP.COM", _position_c4_b2_body)


def _position_c4_b2_body() -> dict:
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

    while status["location"]["eip"] != ds.CALL_FUNC1_OFFSET:
        status = s5a.step_into()
        assert "error" not in status, status
    return s5a.verify.get_debug_status()


def position_c4_b3(max_attempts: int = 25) -> dict:
    """B3: TEST.COM caught running, paused exactly ONE instruction before
    the loop-body top -- CS:EIP on the LOOP instruction itself (0107), one
    instruction before its own branch target (0106, TEST_COM_LOOP_OFFSET).
    Exact live-verified technique from docs/phase5b-b3-b5-revision.md
    ("Positioning for the revised scenario"): catch TEST.COM running,
    pause; if landed exactly at the target already, one more
    continue+pause cycle lands one instruction earlier -- otherwise the
    task would be trivially satisfied by reading the already-current
    state. Bounded-retried here (the doc's own single-cycle description
    empirically lands on 0107, but a tight two-instruction loop can also
    be paused elsewhere in it) rather than assuming one cycle always
    suffices."""

    def body() -> dict:
        ds.find_test_com_segment()
        ds.clear_all_breakpoints()

        status = s5a.verify.get_debug_status()
        for _ in range(max_attempts):
            if not status["stopped"]:
                status = s5a.pause_execution()
                assert "error" not in status, status
            if status["location"]["eip"] == "0107":
                return status
            continued = s5a.continue_execution()
            assert "error" not in continued, continued
            status = s5a.pause_execution()
            assert "error" not in status, status
        raise AssertionError(
            f"could not position TEST.COM at CS:EIP=0107 (LOOP instruction) after {max_attempts} attempts; last status: {status!r}"
        )

    return _with_relaunch_retry("TEST.COM", body)


def position_c4_b4() -> dict:
    """B4: guest execution already RUNNING when the agent is handed
    control (harness issues continue_execution() before positioning ends)
    -- exactly as Phase 5A's own Scenario 5 setup
    (tests/phase5a/real_agent_setup.py::setup_5_running())."""

    def body() -> dict:
        ds.find_test_com_segment()
        ds.clear_all_breakpoints()
        continued = s5a.continue_execution()
        assert "error" not in continued, continued
        return s5a.verify.get_debug_status()

    return _with_relaunch_retry("TEST.COM", body)


POSITIONERS = {
    "C4-B1": position_c4_b1,
    "C4-B2": position_c4_b2,
    "C4-B3": position_c4_b3,
    "C4-B4": position_c4_b4,
}
