from mcp.server.mcpserver import MCPServer

from dosbox_client import DOSBoxClient, DOSBoxClientError
from protocol import error as protocol_error

mcp = MCPServer(
    "DOSBox-X AI Debugger"
)

# Every debugger tool talks to the actual running DOSBox-X instance through
# the native AI bridge (dosbox-src/src/debug/debug_ai.cpp). FakeDOSBoxDebugger
# (ai/debugger.py) is no longer wired into the MCP tool layer -- it remains
# available for unit tests that don't require a live DOSBox-X instance
# (tests/test_debugger.py).
dosbox = DOSBoxClient()


def _guarded_native(func, *args):
    """Run a DOSBoxClient call against the real DOSBox-X instance, turning
    any DOSBoxClientError into a structured error response instead of
    letting a raw socket/protocol exception reach the MCP client. Uses
    e.code directly -- DOSBoxClient always preserves the exact native
    error code (e.g. "INVALID_PARAMETER"), even when the exception class
    itself is the generic DOSBoxProtocolError catch-all, so the AI agent
    always sees the specific, actionable code rather than a vague one."""

    try:
        return func(*args)
    except DOSBoxClientError as e:
        return protocol_error(e.code, str(e))


@mcp.tool()
def ping() -> str:
    """
    Test whether the DOSBox-X AI Debugger MCP server is alive.
    """

    return "DOSBox-X AI Debugger is alive."


@mcp.tool()
def get_project_status() -> dict:
    """
    Return the current development status.
    """

    return {
        "project": "DOSBox-X AI Debugger",
        "phase": "P6B",
        "dosbox_bridge": f"native ({dosbox.host}:{dosbox.port})",
        "debugger": "native",
        "mcp": "online",
    }


@mcp.tool()
def get_cpu_state() -> dict:
    """
    Return the current CPU registers and segment state from the real,
    running DOSBox-X instance via the native AI bridge.
    """

    return _guarded_native(dosbox.get_cpu_state)


@mcp.tool()
def get_debug_status() -> dict:
    """
    Return one coherent debugger snapshot from the real, running DOSBox-X
    instance via the native AI bridge: stop state, location, current
    instruction, registers, segments, and flags.
    """

    return _guarded_native(dosbox.get_debug_status)


@mcp.tool()
def get_current_instruction() -> dict:
    """
    Return the instruction at the current CS:EIP from the real, running
    DOSBox-X instance via the native AI bridge.
    """

    return _guarded_native(dosbox.get_current_instruction)


@mcp.tool()
def read_memory(address: str, length: int) -> dict:
    """
    Read `length` bytes starting at a "SEG:OFF" address (e.g. "1234:0100")
    from the real, running DOSBox-X instance via the native AI bridge.
    """

    return _guarded_native(dosbox.read_memory, address, length)


@mcp.tool()
def disassemble(address: str, count: int) -> list:
    """
    Disassemble `count` instructions starting at a "SEG:OFF" address from
    the real, running DOSBox-X instance via the native AI bridge.
    """

    return _guarded_native(dosbox.disassemble, address, count)


@mcp.tool()
def write_memory(address: str, data: list) -> dict:
    """
    Write bytes (list of ints 0-255 and/or 2-digit hex strings, e.g.
    [0xB8, "34", "12"]) starting at a "SEG:OFF" address, on the real,
    running DOSBox-X instance via the native AI bridge.
    """

    return _guarded_native(dosbox.write_memory, address, data)


@mcp.tool()
def write_register(register: str, value: str) -> dict:
    """
    Write one general-purpose register on the real, running DOSBox-X
    instance via the native AI bridge. `value` is a hex string (e.g.
    "0000ABCD"). Only eax/ebx/ecx/edx/esi/edi/ebp may be written -- EIP,
    segment registers, ESP, and EFLAGS are rejected with
    REGISTER_NOT_WRITABLE to avoid desyncing execution.
    """

    return _guarded_native(dosbox.write_register, register, value)


@mcp.tool()
def set_breakpoint(address: str) -> dict:
    """
    Set a breakpoint at a "SEG:OFF" address, on the real, running DOSBox-X
    instance via the native AI bridge -- the SAME breakpoint mechanism
    (CBreakpoint/BPoints) the debugger GUI's BP command uses. Fails with
    BREAKPOINT_ALREADY_EXISTS if a breakpoint is already set at that
    address.
    """

    return _guarded_native(dosbox.set_breakpoint, address)


@mcp.tool()
def set_real_memory_breakpoint(address: str) -> dict:
    """
    Watch one byte at a real-mode "SEG:OFFSET" address on the real, running
    DOSBox-X instance -- execution stops after the byte's value changes.
    Uses the native debugger's BPPM mechanism; available only on
    heavy-debug builds (INTERNAL_ERROR otherwise). Only meaningful while
    the debugger is stopped when you create it (like set_breakpoint); the
    watch itself then fires on a later continue_execution()/step, whenever
    the byte's value actually changes.
    """

    return _guarded_native(dosbox.set_real_memory_breakpoint, address)


@mcp.tool()
def set_protected_memory_breakpoint(address: str) -> dict:
    """
    Watch one byte at a protected-mode "SELECTOR:OFFSET" address on the
    real, running DOSBox-X instance -- execution stops after the byte's
    value changes. Uses the native debugger's BPPM mechanism; available
    only on heavy-debug builds (INTERNAL_ERROR otherwise).
    """

    return _guarded_native(dosbox.set_protected_memory_breakpoint, address)


@mcp.tool()
def delete_breakpoint(breakpoint_id: int) -> dict:
    """
    Delete a breakpoint by its id (as returned by set_breakpoint/
    list_breakpoints), on the real, running DOSBox-X instance. Ids are
    positions in DOSBox-X's own breakpoint list (the same ids the
    debugger GUI's BPLIST/BPDEL commands use) and shift when breakpoints
    are added or removed -- call list_breakpoints() again if unsure an id
    is still current. Fails with BREAKPOINT_NOT_FOUND otherwise.
    """

    return _guarded_native(dosbox.delete_breakpoint, breakpoint_id)


@mcp.tool()
def list_breakpoints() -> list:
    """
    List all code and memory breakpoints currently set on the real,
    running DOSBox-X instance -- the same breakpoints the debugger GUI's
    BPLIST command would show. Each entry's "type" is "code",
    "memory" (real-mode watch), or "protected_memory".
    """

    return _guarded_native(dosbox.list_breakpoints)


@mcp.tool()
def continue_execution() -> dict:
    """
    Resume real guest CPU execution on the real, running DOSBox-X instance
    via the native AI bridge -- the SAME transition the debugger GUI's RUN
    command makes. Only valid while the debugger is stopped; fails with
    ALREADY_RUNNING otherwise. The guest CPU is genuinely resumed by the
    time this call returns (not merely acknowledged) -- call
    get_debug_status() afterward to see it running, or set a breakpoint
    first with set_breakpoint() to stop again at a known point.
    """

    return _guarded_native(dosbox.continue_execution)


@mcp.tool()
def pause_execution() -> dict:
    """
    Stop real guest CPU execution on the real, running DOSBox-X instance
    via the native AI bridge -- the SAME transition Ctrl+Pause makes. Only
    valid while guest code is running; fails with ALREADY_STOPPED
    otherwise. Blocks until the CPU has genuinely stopped and returns a
    real debug status snapshot (location, instruction, registers,
    segments, flags) taken after it stopped -- not merely an
    acknowledgement that the request was received.
    """

    return _guarded_native(dosbox.pause_execution)


@mcp.tool()
def step_into() -> dict:
    """
    Execute exactly one guest instruction on the real, running DOSBox-X
    instance via the native AI bridge -- the SAME transition the debugger
    GUI's F11 ("trace into") key makes. Only valid while the debugger is
    stopped; fails with ALREADY_RUNNING otherwise. Blocks until the real
    DOSBox-X CPU decoder has genuinely executed the instruction and returns
    a real debug status snapshot (location, instruction, registers,
    segments, flags) taken after it stopped again.
    """

    return _guarded_native(dosbox.step_into)


@mcp.tool()
def step_over() -> dict:
    """
    Step over the current instruction on the real, running DOSBox-X
    instance via the native AI bridge -- the SAME transition the debugger
    GUI's F10 ("step over") key makes. For an ordinary instruction this
    behaves exactly like step_into(). For a call/int/loop/rep instruction,
    the real subroutine/interrupt/loop runs to completion (using DOSBox-X's
    own one-shot-breakpoint mechanism) and this call blocks until execution
    stops again at the instruction after it. Only valid while the debugger
    is stopped; fails with ALREADY_RUNNING otherwise. Fails with
    EXECUTION_TIMEOUT if the stepped-over instruction does not return
    within the timeout -- call get_debug_status() afterward to check
    whether it completed shortly after.
    """

    return _guarded_native(dosbox.step_over)


@mcp.tool()
def key_down(key: str) -> dict:
    """
    Press and hold a keyboard key on the real, running DOSBox-X instance,
    through the SAME internal path DOSBox-X's own SDL keyboard handler
    uses (KEYBOARD_AddKey()) -- never OS-level key injection or window
    automation. `key` is a name from a fixed whitelist covering the
    standard US 104-key layout (e.g. "a", "1", "f1", "enter", "space",
    "leftshift", "leftctrl", "up", "kp5") -- an unrecognized name fails
    with INVALID_PARAMETER. Only valid while guest execution is running;
    fails with DEBUGGER_STOPPED otherwise (call continue_execution()
    first). Held keys are tracked per MCP session and automatically
    released if the connection is lost before key_up() is called -- see
    release_all_input().
    """

    return _guarded_native(dosbox.key_down, key)


@mcp.tool()
def key_up(key: str) -> dict:
    """
    Release a keyboard key previously pressed with key_down(). Same key
    name whitelist and running-only precondition as key_down().
    """

    return _guarded_native(dosbox.key_up, key)


@mcp.tool()
def key_tap(key: str) -> dict:
    """
    Press and immediately release a keyboard key on the real, running
    DOSBox-X instance -- the common case for advancing dialogue/menus
    (e.g. key_tap("enter")). Same key name whitelist and running-only
    precondition as key_down().
    """

    return _guarded_native(dosbox.key_tap, key)


@mcp.tool()
def move_mouse_relative(dx: float, dy: float) -> dict:
    """
    Move the guest mouse cursor by a relative (dx, dy) delta, through the
    SAME internal path DOSBox-X's own SDL mouse handler uses
    (Mouse_CursorMoved()). Only valid while guest execution is running;
    fails with DEBUGGER_STOPPED otherwise. Only reaches the guest if
    DOSBox-X's mouse is currently captured (Ctrl+F10) and the guest is
    running a driver that reads relative motion -- this call does not
    itself toggle mouse capture.
    """

    return _guarded_native(dosbox.move_mouse_relative, dx, dy)


@mcp.tool()
def set_mouse_button(button: int, pressed: bool) -> dict:
    """
    Press/hold (pressed=true) or release (pressed=false) a mouse button on
    the real, running DOSBox-X instance. `button` is 0 (left), 1 (right),
    or 2 (middle). Only valid while guest execution is running; fails with
    DEBUGGER_STOPPED otherwise. Like key_down(), held buttons are tracked
    per MCP session and auto-released if the connection is lost.
    """

    return _guarded_native(dosbox.set_mouse_button, button, pressed)


@mcp.tool()
def click_mouse(button: int) -> dict:
    """
    Press and immediately release a mouse button on the real, running
    DOSBox-X instance. `button` is 0 (left), 1 (right), or 2 (middle).
    Only valid while guest execution is running; fails with
    DEBUGGER_STOPPED otherwise.
    """

    return _guarded_native(dosbox.click_mouse, button)


@mcp.tool()
def release_all_input() -> dict:
    """
    Release every key/mouse button this MCP session currently holds down
    on the real, running DOSBox-X instance. Call this at the end of a
    session that used key_down()/set_mouse_button(pressed=true) as a good
    citizen -- the native bridge also does this automatically if the
    connection is lost without it ever being called.
    """

    return _guarded_native(dosbox.release_all_input)


if __name__ == "__main__":
    mcp.run()
