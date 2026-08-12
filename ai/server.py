from mcp.server.mcpserver import MCPServer

from debugger import FakeDOSBoxDebugger
from dosbox_client import DOSBoxClient, DOSBoxClientError
from protocol import DebuggerError, error as protocol_error

mcp = MCPServer(
    "DOSBox-X AI Debugger"
)

# Real debugger tools (get_debug_status/get_cpu_state/read_memory/
# get_current_instruction/disassemble/write_memory/write_register/
# set_breakpoint/delete_breakpoint/list_breakpoints/continue_execution/
# pause_execution) talk to the actual running DOSBox-X instance through the
# native AI bridge (dosbox-src/src/debug/debug_ai.cpp).
dosbox = DOSBoxClient()

# step_into is not yet implemented by the native bridge (Phase 4D) and
# still runs against the in-process fake, which also remains available for
# unit tests (tests/test_debugger.py).
fake_debugger = FakeDOSBoxDebugger()


def _guarded(func, *args):
    """Run a FakeDOSBoxDebugger call, turning DebuggerError into a
    structured error response instead of letting an exception reach the
    MCP client."""

    try:
        return func(*args)
    except DebuggerError as e:
        return protocol_error(e.code, e.message)


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
        "phase": "P4C",
        "dosbox_bridge": f"native ({dosbox.host}:{dosbox.port})",
        "debugger": "native+fake",
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
    List all breakpoints currently set on the real, running DOSBox-X
    instance -- the same breakpoints the debugger GUI's BPLIST command
    would show.
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


# -- Not yet implemented by the native bridge (Phase 4D): still runs
# against FakeDOSBoxDebugger so the MCP tool surface stays complete and
# testable. --


@mcp.tool()
def step_into() -> dict:
    """
    Execute exactly one instruction and return the new debug status. Not
    yet backed by the native bridge (Phase 4D); runs against the in-process
    fake debugger.
    """

    return _guarded(fake_debugger.step_into)


if __name__ == "__main__":
    mcp.run()
