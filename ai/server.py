import base64

from mcp.server.mcpserver import Image, MCPServer

import analysis
from dosbox_client import DOSBoxClient, DOSBoxClientError
from knowledge import KnowledgeStore
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

# Agent-side symbol/annotation store (Phase 8C, item 2) -- see
# ai/knowledge.py. Never touches DOSBox-X or the native bridge; persists to
# ai/knowledge.local.json (git-ignored) by default.
knowledge = KnowledgeStore()


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
        "phase": "P7E",
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
def memory_search(
    start_address: str,
    length: int,
    pattern: list = None,
    text: str = None,
    case_sensitive: bool = True,
    max_matches: int = 1000,
) -> dict:
    """
    Scan real, running DOSBox-X guest memory for a byte pattern or ASCII
    string, starting at a "SEG:OFF" address, over `length` bytes (1 to
    0x100000 -- the entire real-mode address space). Built entirely out of
    repeated read_memory() calls -- no new native bridge method and no
    second memory-reading mechanism.

    Give exactly one of `pattern` (a list of byte specs: an int 0-255, a
    2-digit hex string, or "??"/"?"/None for "match any byte" -- e.g.
    ["B8", "??", "12"]) or `text` (matched as raw ASCII bytes;
    `case_sensitive=False` matches either letter case).

    Guest memory the native bridge reports as unmapped/inaccessible while
    scanning is skipped and reported under "unreadable_regions" -- never
    silently treated as zero bytes or fabricated as a match.
    `max_matches` (default 1000) bounds the result size; hitting it sets
    "truncated": true and stops scanning early.

    Result: {"matches": ["SEG:OFF", ...], "scanned_bytes": int,
    "unreadable_regions": [{"address": "SEG:OFF", "length": int}],
    "truncated": bool}. Match addresses are canonicalized
    (segment = linear_address >> 4, offset = linear_address & 0xF) so
    every match is expressible in "SEG:OFF" form even when it spans a
    segment boundary.
    """

    return _guarded_native(
        analysis.search_memory, dosbox, start_address, length, pattern, text, case_sensitive, max_matches
    )


@mcp.tool()
def disassemble(address: str, count: int) -> list:
    """
    Disassemble `count` instructions starting at a "SEG:OFF" address from
    the real, running DOSBox-X instance via the native AI bridge.
    """

    return _guarded_native(dosbox.disassemble, address, count)


@mcp.tool()
def get_call_stack(max_frames: int = 32) -> dict:
    """
    Walk the real-mode SS:BP frame-pointer chain from the debugger's
    current stopped position on the real, running DOSBox-X instance.
    Built entirely out of get_cpu_state() plus repeated read_memory()
    calls -- no new native bridge method.

    Assumes a standard PUSH BP / MOV BP,SP prologue and NEAR (same-
    segment) CALLs, matching this project's own DOS test programs; a FAR
    call's return address would be misread. Stops once a saved BP is not
    strictly greater than the current frame's BP (real-mode stacks grow
    downward) or on unmapped stack memory.

    Result: {"frames": [{"bp": "SS:BP", "return_address": "CS:offset"},
    ...], "truncated": bool}. `return_address`'s segment is always the
    current CS -- a near return address carries no segment of its own.
    """

    return _guarded_native(analysis.get_call_stack, dosbox, max_frames)


@mcp.tool()
def build_control_flow_graph(
    start_address: str, max_blocks: int = 64, max_instructions_per_block: int = 64
) -> dict:
    """
    Build a control-flow graph on the real, running DOSBox-X instance by
    recursively walking disassemble() from `start_address`, splitting a
    new block at every resolvable near JMP/Jcc/CALL/LOOP*/JCXZ and
    following its target(s). No second disassembler -- entirely reuses
    the native bridge's own disassembly output.

    Only NEAR, same-segment branches are followed. A block ending in a
    far/indirect JMP or CALL, or in RET/IRET/INT, has no followed
    successor -- its "unresolved_transfer" field names which kind of
    transfer stopped the walk there, never a guessed target. Only
    explores code already loaded into guest memory; never changes
    execution state.

    Result: {"blocks": {"SEG:OFF": {"instructions": [...],
    "successors": ["SEG:OFF", ...], "unresolved_transfer": str|None},
    ...}, "truncated": bool}. Addresses are canonicalized (segment =
    linear_address >> 4, offset = linear_address & 0xF), matching
    memory_search()'s convention.
    """

    return _guarded_native(
        analysis.build_control_flow_graph, dosbox, start_address, max_blocks, max_instructions_per_block
    )


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
def write_io_port(port: str, value: str, width: int = 1) -> dict:
    """
    Write to one whitelisted VGA I/O port on the real, running DOSBox-X
    instance via the native AI bridge. `port` and `value` are hex strings
    (e.g. port "3CE", value "04"); `width` is the write size in bytes (1,
    2, or 4) and defaults to 1. Only the standard VGA CRTC/Sequencer/
    Graphics Controller/Attribute Controller/DAC/Misc Output/Feature
    Control ports may be written -- any other port is rejected with
    PORT_NOT_WRITABLE. Useful e.g. for switching the VGA read plane
    (Graphics Controller index 4) while stopped at a breakpoint, which
    memory.write cannot do since it only reaches guest RAM, not I/O space.
    """

    return _guarded_native(dosbox.write_io_port, port, value, width)


@mcp.tool()
def vga_snapshot(regions: list) -> dict:
    """
    Read raw VGA VRAM directly -- one or more (plane, offset, length)
    regions, plus the VGA latch and the Sequencer/Graphics Controller/CRTC
    register files -- in one atomic snapshot from the real, running
    DOSBox-X instance, via the native AI bridge. Only valid while the
    debugger is stopped (like every other memory/register tool here).

    Unlike read_memory, this never goes through the CPU's A000:xxxx read
    path, so it cannot itself change the VGA latch, any VGA register, CPU
    state, guest memory, or execution position, and it never requires
    switching the VGA read plane first (write_io_port to 3CE/3CF) -- all
    four planes are visible in the same call regardless of which plane was
    last selected. This is exactly what makes it safe for diagnosing
    whether something else (not the diagnostic call itself) changed the
    screen.

    `regions` is a list of dicts, each {"plane": 0-3, "offset": <int or hex
    string, a per-plane byte offset -- NOT multiplied by 4>, "length": <int,
    bytes to read from that plane>}. The response's plane_size_bytes tells
    you each plane's real size; a region's returned_length can be less than
    its requested length (never more, never an error) if offset+length ran
    past that. Only EGA/VGA-family machines are supported -- any other
    machine type is rejected with VGA_SNAPSHOT_UNSUPPORTED, since their
    video memory is not laid out as 4-plane interleaved VRAM.

    Example: to read the bottom 30 lines of two Mode X pages (each plane's
    byte offsets 0x3520/0x7520, 2,400 bytes) across all four planes in one
    call: regions=[{"plane": p, "offset": off, "length": 2400}
    for p in range(4) for off in ("3520", "7520")].
    """

    return _guarded_native(dosbox.snapshot_vga, regions)


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


@mcp.tool()
def capture_frame(format: str = "png", max_width: int = None, max_height: int = None):
    """
    Capture exactly the guest's own rendered frame on the real, running
    DOSBox-X instance -- never the DOSBox-X window, the host desktop, or
    any other host window -- through the SAME internal hook DOSBox-X's
    own screenshot/AVI recording already use (never written to disk
    here). `format` is "png" (default, returned as a directly viewable
    image) or "rgba" (raw rgba8888 bytes, base64-encoded, for precise
    pixel-level inspection rather than viewing). Optional
    max_width/max_height downscale (nearest-neighbor, aspect ratio
    preserved) if the native frame would exceed them.

    Meaningful whether the debugger is stopped or running, but a fully
    halted guest is not producing new rendered frames -- expect
    EXECUTION_TIMEOUT more often than not in that case; call
    continue_execution() first for reliable captures. Fails with
    FRAME_TOO_LARGE (with a suggested smaller max_width/max_height in the
    error) if the encoded frame exceeds the bridge's payload cap.
    """

    result = _guarded_native(dosbox.capture_frame, format, max_width, max_height)
    if isinstance(result, dict) and "error" in result:
        return result

    if format == "png":
        metadata = {k: v for k, v in result.items() if k != "png_base64"}
        return [metadata, Image(data=base64.b64decode(result["png_base64"]), format="png")]

    return result


@mcp.tool()
def capture_composite(
    format: str = "png",
    crop: str = None,
    game_rect: dict = None,
    rect: dict = None,
    max_width: int = None,
    max_height: int = None,
    include_source: bool = False,
):
    """
    Capture the FINAL composed image DOSBox-X is about to present on the
    real, running instance -- the output backend's back buffer after
    scaling, filtering, pixel shaders and letterboxing -- plus the
    geometry needed to map guest coordinates onto it. Never reads the
    Windows window or desktop, so other windows covering DOSBox-X do not
    affect it; the host mouse cursor is never included.

    How it differs from capture_frame():

    | | capture_frame | capture_composite |
    |---|---|---|
    | Layer | Guest image before the scaler | Final image before present |
    | Resolution | Guest render size (mode 13h: 640x400) | Back buffer (window/fullscreen) size |
    | Shaders, filtering, letterbox | No | Yes |
    | Future Modern overlays | No | Yes |
    | Use for | DOS framebuffer checks, CRC, finding pixels | What the player actually sees: overlay position, sharpness |

    `format` is "png" (default, returned as a viewable image) or "rgba".
    Give at most one of: `crop` ("viewport" -- the default, just the
    game image -- or "full" for the whole back buffer including
    letterbox bars), `game_rect` ({"x","y","w","h"} in the guest's
    native grid, e.g. 320x200 for mode 13h -- the bridge converts it
    using geometry.viewport; prefer this for checking a specific on-screen
    element), or `rect` ({"x","y","w","h"} in back-buffer pixels).
    `max_width`/`max_height` downscale nearest-neighbor. With
    `include_source=True`, the capture_frame() image of the SAME
    emulated frame is returned as a second image
    (metadata.source_frame_match tells whether both came from one frame).

    Result metadata includes backend, target/presented render_seq,
    crop_rect, and geometry {backbuffer, viewport, draw, render_src,
    guest_native, scale, aspect_correction, fullscreen, pixel_shader}.

    Only output=direct3d and output=surface are supported; other
    backends fail with COMPOSITE_UNSUPPORTED_BACKEND (never a silent
    fallback to capture_frame). Needs a frame to be presented within the
    timeout: a guest stopped at a breakpoint or a minimized window gives
    EXECUTION_TIMEOUT -- call continue_execution() first. Out-of-range
    crops fail with CROP_OUT_OF_BOUNDS; oversized payloads with
    FRAME_TOO_LARGE (use png, a crop, or max_width/max_height).
    """

    result = _guarded_native(
        dosbox.capture_composite, format, crop, rect, game_rect, max_width, max_height, include_source
    )
    if isinstance(result, dict) and "error" in result:
        return result

    if format == "png":
        metadata = {k: v for k, v in result.items() if k not in ("png_base64", "source")}
        images = [Image(data=base64.b64decode(result["png_base64"]), format="png")]
        source = result.get("source")
        if source:
            metadata["source"] = {"width": source["width"], "height": source["height"]}
            images.append(Image(data=base64.b64decode(source["png_base64"]), format="png"))
        return [metadata, *images]

    return result


@mcp.tool()
def get_mouse_capture() -> dict:
    """
    Read DOSBox-X's own mouse-capture state on the real, running DOSBox-X
    instance (whether Ctrl+F10 is currently "on") and whether absolute
    positioning is currently usable, without touching the host cursor or
    window focus. Meaningful whether the debugger is stopped or running.

    Result includes "guest_width"/"guest_height" -- these match
    capture_frame()'s own reported width/height for the current video
    mode, so a pixel picked from a capture_frame() screenshot can be
    passed straight to click_at() in "guest_pixels" space.

    IMPORTANT: "guest_width"/"guest_height" are the RENDERED (screenshot)
    size, not necessarily the guest video mode's nominal/native
    resolution -- DOSBox-X pixel-doubles low-resolution modes for
    on-screen viewing (e.g. Mode 13h is nominally 320x200 but reports/
    renders as 640x400 here). Coordinates computed against a native
    resolution (not an actual capture_frame() screenshot) must be scaled
    up to this call's actual guest_width/guest_height before being used
    with move_mouse_absolute()/click_at() -- otherwise they land at half
    the intended position on both axes for a doubled mode like this.
    """

    return _guarded_native(dosbox.get_mouse_capture)


@mcp.tool()
def set_mouse_capture(captured: bool) -> dict:
    """
    Toggle DOSBox-X's own mouse capture on the real, running DOSBox-X
    instance -- the exact same effect as the user pressing Ctrl+F10.
    Never moves the host cursor, changes window focus, or affects any
    other program. Meaningful whether the debugger is stopped or
    running. Fails with CAPTURE_UNAVAILABLE if the current video backend
    has no safely controllable capture state.
    """

    return _guarded_native(dosbox.set_mouse_capture, captured)


@mcp.tool()
def move_mouse_absolute(
    x: float, y: float, coordinate_space: str = "guest_pixels", clamp: bool = False
) -> dict:
    """
    Move the guest mouse cursor to an absolute position on the real,
    running DOSBox-X instance, through the SAME internal path DOSBox-X's
    own seamless/integrated mouse positioning uses -- unlike
    move_mouse_relative(), this does not require mouse capture to be on.
    Only valid while guest execution is running; fails with
    DEBUGGER_STOPPED otherwise.

    `coordinate_space` is "guest_pixels" (origin top-left, matching
    capture_frame()'s reported width/height -- see get_mouse_capture(),
    including its important caveat that this is screenshot-pixel space,
    not necessarily the guest video mode's nominal resolution) or
    "normalized" ([0.0, 1.0] x [0.0, 1.0]). Out-of-range coordinates
    fail with INVALID_PARAMETER unless clamp=true, in which case they
    are clamped to the guest's bounds and the result's "clamped" field
    is true. Fails with ABSOLUTE_MOUSE_UNAVAILABLE if absolute
    positioning is not currently usable in the guest's mode -- check
    get_mouse_capture()'s "mode" field first if unsure.
    """

    return _guarded_native(dosbox.move_mouse_absolute, x, y, coordinate_space, clamp)


@mcp.tool()
def click_at(
    x: float, y: float, button: int = 0, coordinate_space: str = "guest_pixels", clamp: bool = False
) -> dict:
    """
    Move to an absolute position and click on the real, running DOSBox-X
    instance, in a single emulator-thread dispatch -- nothing else can
    insert between the move and the click. `button` is 0 (left), 1
    (right), or 2 (middle). See move_mouse_absolute() for
    `coordinate_space`, `clamp`, and error conditions.
    """

    return _guarded_native(dosbox.click_at, x, y, button, coordinate_space, clamp)


@mcp.tool()
def get_input_receipt(input_sequence: int) -> dict:
    """
    Look up an earlier key/mouse dispatch on the real, running DOSBox-X
    instance by the "input_sequence" one of the input tools above
    returned (key_down/up/tap, move_mouse_relative, set_mouse_button,
    click_mouse, move_mouse_absolute, click_at) -- whether the debugger
    is currently stopped or running. Fails with INPUT_RECEIPT_EXPIRED if
    that sequence is not in the bridge's ring buffer (at least the most
    recent 4096 dispatches or 10 minutes' worth, whichever bound is hit
    first) -- indistinguishable from a sequence that was never issued.
    """

    return _guarded_native(dosbox.get_input_receipt, input_sequence)


@mcp.tool()
def configure_execution_trace(
    enabled: bool,
    before_instructions: int = 0,
    after_instructions: int = 0,
    registers: list = None,
    include_disassembly: bool = True,
    max_trace_bytes: int = 65536,
) -> dict:
    """
    Turn automatic execution tracing on/off for the real, running
    DOSBox-X instance. While enabled, every time the debugger genuinely
    stops (a code/memory breakpoint, a manual pause_execution(), or
    -break-start) a trace is captured automatically -- the
    `before_instructions` leading up to (and including) the stop, and,
    if `after_instructions` > 0, that many instructions executed
    immediately afterward (the debugger's own visible stop position
    moves to reflect this). Meaningful whether the debugger is stopped
    or running.

    `before_instructions`/`after_instructions` are each 0..4096.
    `registers` restricts which of ax/bx/cx/dx/si/di/bp/sp/cs/ip/flags
    each instruction reports (omit for all). `max_trace_bytes`
    (65536..4194304) bounds one trace's size -- see
    list_execution_traces()/get_execution_trace()'s
    dropped_instruction_count if exceeded.

    Turning this off (the default) leaves breakpoint behavior/
    performance completely unchanged from before this feature existed.
    Fails with INTERNAL_ERROR on a build without heavy-debug support.
    """

    return _guarded_native(
        dosbox.configure_execution_trace,
        enabled, before_instructions, after_instructions, registers, include_disassembly, max_trace_bytes,
    )


@mcp.tool()
def list_execution_traces(limit: int = 100, after_trace_id: int = None) -> dict:
    """
    List captured execution traces from the real, running DOSBox-X
    instance (summaries only -- call get_execution_trace() for the full
    before/after instruction detail). `after_trace_id` restricts to
    traces newer than a given id. Meaningful whether the debugger is
    stopped or running. The bridge retains at most the 100 most recent
    traces.
    """

    return _guarded_native(dosbox.list_execution_traces, limit, after_trace_id)


@mcp.tool()
def get_execution_trace(trace_id: int) -> dict:
    """
    Fetch one execution trace's full detail (from
    list_execution_traces()) from the real, running DOSBox-X instance --
    the instructions before and after a breakpoint hit, with
    disassembly and registers. Fails with TRACE_NOT_FOUND if that
    trace_id isn't currently retained.
    """

    return _guarded_native(dosbox.get_execution_trace, trace_id)


@mcp.tool()
def configure_dos_io_log(
    enabled: bool,
    operations: list = None,
    path_globs: list = None,
    include_failed: bool = True,
    max_events: int = 10000,
) -> dict:
    """
    Turn DOS file I/O event logging on/off for the real, running
    DOSBox-X instance. While enabled, every completed INT 21h
    open/close/read/write/seek call is recorded with its real result
    (actual bytes transferred, AX, carry). Meaningful whether the
    debugger is stopped or running.

    `operations` restricts which of "open"/"close"/"read"/"write"/"seek"
    are logged (omit for all five). `path_globs` (e.g. ["*.GFF",
    "SAVE-*"], case-insensitive) restricts to matching DOS paths --
    non-matching events are never recorded at all. `max_events`
    (100..100000) bounds the ring buffer.
    """

    return _guarded_native(
        dosbox.configure_dos_io_log, enabled, operations, path_globs, include_failed, max_events
    )


@mcp.tool()
def list_dos_io_events(
    limit: int = 1000, after_event_id: int = None, operation: str = None, path_glob: str = None
) -> dict:
    """
    List recorded DOS file I/O events from the real, running DOSBox-X
    instance. `after_event_id` restricts to events newer than a given
    id; `operation`/`path_glob` filter further. `buffer.linear` in each
    event lets you correlate a read with a later memory watchpoint on
    that same address. Meaningful whether the debugger is stopped or
    running.
    """

    return _guarded_native(dosbox.list_dos_io_events, limit, after_event_id, operation, path_glob)


@mcp.tool()
def clear_dos_io_log() -> dict:
    """
    Discard every currently recorded DOS file I/O event on the real,
    running DOSBox-X instance (does not change the current
    configure_dos_io_log() configuration or stop logging).
    """

    return _guarded_native(dosbox.clear_dos_io_log)


# -- persistent symbol/annotation knowledge store (Phase 8C, item 2) --
#
# Agent-side only: never touches DOSBox-X or the native bridge, so none
# of these tools need _guarded_native -- invalid input raises a plain
# ValueError, matching this file's existing convention for other
# purely-parameter-validation failures (e.g. write_io_port's width check).


@mcp.tool()
def set_symbol(address: str, name: str) -> dict:
    """
    Give `address` ("SEG:OFF") a name in the agent-side knowledge store
    (persisted across sessions, never sent to DOSBox-X). Addresses are
    canonicalized, so any "SEG:OFF" representation of the same linear
    address finds the same symbol. Result: {"address", "name"}.
    """

    return knowledge.set_symbol(address, name)


@mcp.tool()
def get_symbol(address: str) -> dict:
    """
    Look up the name previously given to `address` via set_symbol().
    Result: {"address", "name"} -- "name" is null if none was set.
    """

    return knowledge.get_symbol(address)


@mcp.tool()
def delete_symbol(address: str) -> dict:
    """
    Remove the name given to `address`, if any. Result: {"address",
    "deleted": bool}.
    """

    return knowledge.delete_symbol(address)


@mcp.tool()
def list_symbols() -> dict:
    """
    List every symbol currently in the agent-side knowledge store.
    Result: {"symbols": [{"address", "name"}, ...]}.
    """

    return knowledge.list_symbols()


@mcp.tool()
def set_comment(address: str, text: str) -> dict:
    """
    Attach a free-text comment to `address` in the agent-side knowledge
    store (overwrites any existing comment at that address). Result:
    {"address", "text"}.
    """

    return knowledge.set_comment(address, text)


@mcp.tool()
def get_comment(address: str) -> dict:
    """
    Look up the comment previously set on `address` via set_comment().
    Result: {"address", "text"} -- "text" is null if none was set.
    """

    return knowledge.get_comment(address)


@mcp.tool()
def add_xref(from_address: str, to_address: str, kind: str = "call") -> dict:
    """
    Record a cross-reference from `from_address` to `to_address` in the
    agent-side knowledge store. `kind` is one of "call", "jump", "data",
    "other". Idempotent -- adding the same (from, to, kind) triple again
    is a no-op. Result: {"from", "to", "kind"} (canonicalized addresses).
    """

    return knowledge.add_xref(from_address, to_address, kind)


@mcp.tool()
def list_xrefs(address: str, direction: str = "to") -> dict:
    """
    List cross-references involving `address`. `direction` is "to"
    (xrefs pointing at `address`), "from" (xrefs originating at
    `address`), or "both". Result: {"address", "xrefs": [{"from", "to",
    "kind"}, ...]}.
    """

    return knowledge.list_xrefs(address, direction)


if __name__ == "__main__":
    mcp.run()
