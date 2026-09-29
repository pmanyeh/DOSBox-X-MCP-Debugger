"""
DOSBoxClient: Python client for the native DOSBox-X AI bridge
(dosbox-src/src/debug/debug_ai.cpp), connecting over TCP to
127.0.0.1:9876 using newline-delimited JSON (see
docs/dosbox-ai-bridge.md).

This replaces FakeDOSBoxDebugger for production MCP tool execution.
FakeDOSBoxDebugger remains available (ai/debugger.py) for unit tests that
don't require a live DOSBox-X instance.
"""

import itertools
import json
import socket
from typing import Optional

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_REQUEST_TIMEOUT = 5.0


class DOSBoxClientError(Exception):
    """Base class for all DOSBoxClient errors. `code` is a stable,
    machine-readable error code -- for errors that originated as a native
    bridge error response, this is always the exact code the bridge sent
    (e.g. "INVALID_PARAMETER"), even when the exception class itself is
    the generic DOSBoxProtocolError catch-all. Never collapse `code` away
    when reporting an error to a caller -- it's the specific, actionable
    part of the message."""

    code: str = "DOSBOX_CLIENT_ERROR"


class DOSBoxNotConnected(DOSBoxClientError):
    """Could not connect to, or lost connection to, the DOSBox-X AI bridge."""

    code = "DOSBOX_NOT_CONNECTED"


class DOSBoxTimeout(DOSBoxClientError):
    """The DOSBox-X AI bridge did not respond within the request timeout."""

    code = "DOSBOX_TIMEOUT"


class DOSBoxProtocolError(DOSBoxClientError):
    """The DOSBox-X AI bridge returned malformed data, or a native error
    code this client does not have a more specific exception class for
    (e.g. INVALID_PARAMETER, INVALID_REQUEST, UNKNOWN_METHOD, INVALID_JSON).
    `code` is set to the exact native error code when there was one."""

    code = "DOSBOX_PROTOCOL_ERROR"


class DOSBoxDebuggerNotStopped(DOSBoxClientError):
    """The DOSBox-X debugger is not currently active, so the request could
    not be serviced (see native error code DEBUGGER_NOT_STOPPED)."""

    code = "DEBUGGER_NOT_STOPPED"


class DOSBoxMemoryError(DOSBoxClientError):
    """The requested guest memory is unmapped or inaccessible (see native
    error code MEMORY_ERROR)."""

    code = "MEMORY_ERROR"


class DOSBoxRegisterNotWritable(DOSBoxClientError):
    """The requested register is not in the Phase 4A write whitelist (see
    native error code REGISTER_NOT_WRITABLE). EIP, segment registers, ESP,
    and EFLAGS are deliberately protected -- only EAX/EBX/ECX/EDX/ESI/EDI/
    EBP can be written."""

    code = "REGISTER_NOT_WRITABLE"


class DOSBoxPortNotWritable(DOSBoxClientError):
    """The requested I/O port is not in the io.write whitelist (see native
    error code PORT_NOT_WRITABLE). Only the standard VGA CRTC/Sequencer/
    Graphics Controller/Attribute Controller/DAC/Misc Output/Feature
    Control ports are writable -- see WRITABLE_IO_PORTS in debug_ai.cpp."""

    code = "PORT_NOT_WRITABLE"


class DOSBoxVgaSnapshotUnsupported(DOSBoxClientError):
    """vga.snapshot requires an EGA/VGA-family machine (see native error
    code VGA_SNAPSHOT_UNSUPPORTED) -- the current machine's video memory is
    not laid out as 4-plane interleaved VRAM (CGA/Hercules/Tandy/PCjr/
    PC-98 all use a different layout this tool does not support)."""

    code = "VGA_SNAPSHOT_UNSUPPORTED"


class DOSBoxBreakpointNotFound(DOSBoxClientError):
    """No breakpoint exists with the given id (see native error code
    BREAKPOINT_NOT_FOUND). Breakpoint ids are positions in DOSBox-X's own
    breakpoint list (the same ids the debugger GUI's BPLIST/BPDEL commands
    use) and shift when breakpoints are added/removed -- re-run
    list_breakpoints() to get current ids before deleting."""

    code = "BREAKPOINT_NOT_FOUND"


class DOSBoxBreakpointAlreadyExists(DOSBoxClientError):
    """A breakpoint already exists at the requested address (see native
    error code BREAKPOINT_ALREADY_EXISTS). This is a bridge-level policy
    choice, not a DOSBox-X debugger limitation -- see
    docs/dosbox-ai-bridge.md."""

    code = "BREAKPOINT_ALREADY_EXISTS"


class DOSBoxAlreadyRunning(DOSBoxClientError):
    """continue_execution()/step_into()/step_over() was called while guest
    execution is already running -- the debugger is not currently stopped
    (see native error code ALREADY_RUNNING, Phase 4C/4D). Call
    get_debug_status() first if unsure of the current state."""

    code = "ALREADY_RUNNING"


class DOSBoxAlreadyStopped(DOSBoxClientError):
    """pause_execution() was called while the debugger is already stopped
    (see native error code ALREADY_STOPPED, Phase 4C). Call
    get_debug_status() first if unsure of the current state."""

    code = "ALREADY_STOPPED"


class DOSBoxDebuggerStopped(DOSBoxClientError):
    """A key/mouse input injection method (input.key.*, input.mouse.*) was
    called while the DOSBox-X debugger is currently stopped (see native
    error code DEBUGGER_STOPPED, Phase 6B). Input injection only reaches
    the guest while Normal_Loop() has control, i.e. while execution is not
    paused/breakpointed -- call continue_execution() first."""

    code = "DEBUGGER_STOPPED"


class DOSBoxExecutionTimeout(DOSBoxClientError):
    """pause_execution() or step_over() was requested but did not complete
    within the native bridge's timeout (see native error code
    EXECUTION_TIMEOUT, Phase 4C/4D). For step_over(), this means the
    stepped-over call/int/loop/rep instruction had not returned within the
    timeout -- it does not necessarily mean the step failed; call
    get_debug_status() to check whether it has completed since."""

    code = "EXECUTION_TIMEOUT"


class DOSBoxFrameTooLarge(DOSBoxClientError):
    """capture_frame() produced an encoded frame larger than the native
    bridge's payload cap (see native error code FRAME_TOO_LARGE, Phase
    7A). The error's message includes the native bridge's
    suggested_max_width/suggested_max_height -- retry capture_frame()
    with those (or smaller) max_width/max_height values rather than
    assuming any fixed size works for every guest video mode."""

    code = "FRAME_TOO_LARGE"


class DOSBoxCaptureUnavailable(DOSBoxClientError):
    """set_mouse_capture() was called but the current video backend/
    platform has no safely controllable capture state (see native error
    code CAPTURE_UNAVAILABLE, Phase 7B). Not currently produced by any
    known build configuration in this fork -- reserved for forward
    compatibility rather than removed."""

    code = "CAPTURE_UNAVAILABLE"


class DOSBoxAbsoluteMouseUnavailable(DOSBoxClientError):
    """move_mouse_absolute()/click_at() was called but absolute
    positioning is not currently usable in the guest's mode (see native
    error code ABSOLUTE_MOUSE_UNAVAILABLE, Phase 7B) -- e.g. a booted
    guest OS, protected mode without virtual-8086, or a video mode that
    has not yet established a mouse coordinate range. Check
    get_mouse_capture()'s "mode" field ("absolute" vs "relative") before
    relying on absolute positioning."""

    code = "ABSOLUTE_MOUSE_UNAVAILABLE"


class DOSBoxInputReceiptExpired(DOSBoxClientError):
    """get_input_receipt() was called with an input_sequence that is not
    currently in the bridge's receipt ring buffer (see native error code
    INPUT_RECEIPT_EXPIRED, Phase 7C). The bridge keeps at least the most
    recent 4096 receipts or 10 minutes' worth, whichever bound is hit
    first, and does not distinguish "evicted" from "never issued" --
    both report this same error."""

    code = "INPUT_RECEIPT_EXPIRED"


class DOSBoxTraceNotFound(DOSBoxClientError):
    """get_execution_trace() was called with a trace_id that is not
    currently retained (see native error code TRACE_NOT_FOUND, Phase
    7D). The bridge keeps at most the 100 most recent traces, evicting
    the oldest -- does not distinguish "evicted" from "never issued"."""

    code = "TRACE_NOT_FOUND"


_NATIVE_ERROR_MAP = {
    "DEBUGGER_NOT_STOPPED": DOSBoxDebuggerNotStopped,
    "MEMORY_ERROR": DOSBoxMemoryError,
    "REGISTER_NOT_WRITABLE": DOSBoxRegisterNotWritable,
    "PORT_NOT_WRITABLE": DOSBoxPortNotWritable,
    "VGA_SNAPSHOT_UNSUPPORTED": DOSBoxVgaSnapshotUnsupported,
    "BREAKPOINT_NOT_FOUND": DOSBoxBreakpointNotFound,
    "BREAKPOINT_ALREADY_EXISTS": DOSBoxBreakpointAlreadyExists,
    "ALREADY_RUNNING": DOSBoxAlreadyRunning,
    "ALREADY_STOPPED": DOSBoxAlreadyStopped,
    "DEBUGGER_STOPPED": DOSBoxDebuggerStopped,
    "EXECUTION_TIMEOUT": DOSBoxExecutionTimeout,
    "FRAME_TOO_LARGE": DOSBoxFrameTooLarge,
    "CAPTURE_UNAVAILABLE": DOSBoxCaptureUnavailable,
    "ABSOLUTE_MOUSE_UNAVAILABLE": DOSBoxAbsoluteMouseUnavailable,
    "INPUT_RECEIPT_EXPIRED": DOSBoxInputReceiptExpired,
    "TRACE_NOT_FOUND": DOSBoxTraceNotFound,
}


class DOSBoxClient:
    """Thin client for the native AI bridge. Not thread-safe -- each MCP
    server process should use one client from one thread at a time, matching
    the bridge's one-in-flight-request-per-connection design."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ):
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout
        self._sock: Optional[socket.socket] = None
        self._buf = b""
        self._id_counter = itertools.count(1)

    def connect(self) -> None:
        if self._sock is not None:
            return
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
        except OSError as e:
            raise DOSBoxNotConnected(
                f"could not connect to the DOSBox-X AI bridge at {self.host}:{self.port}: {e}"
            ) from e
        sock.settimeout(self.request_timeout)
        self._sock = sock
        self._buf = b""

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
                self._buf = b""

    def __enter__(self) -> "DOSBoxClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _read_line(self) -> bytes:
        while b"\n" not in self._buf:
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout as e:
                raise DOSBoxTimeout(
                    f"the DOSBox-X AI bridge at {self.host}:{self.port} did not respond in time"
                ) from e
            except OSError as e:
                self.close()
                raise DOSBoxNotConnected(f"lost connection to the DOSBox-X AI bridge: {e}") from e
            if not chunk:
                self.close()
                raise DOSBoxNotConnected("the DOSBox-X AI bridge closed the connection")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line

    def request(self, method: str, params: Optional[dict] = None) -> object:
        """Send one request and return its "result" on success. Raises a
        DOSBoxClientError subclass on any failure -- callers never see raw
        socket exceptions or malformed data."""

        if self._sock is None:
            self.connect()

        request_id = next(self._id_counter)
        payload = {"id": request_id, "method": method}
        if params is not None:
            payload["params"] = params

        try:
            self._sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        except OSError as e:
            self.close()
            raise DOSBoxNotConnected(f"lost connection to the DOSBox-X AI bridge: {e}") from e

        line = self._read_line()

        try:
            response = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise DOSBoxProtocolError(f"malformed JSON response from the DOSBox-X AI bridge: {e}") from e

        if not isinstance(response, dict) or "ok" not in response:
            raise DOSBoxProtocolError(f"malformed response from the DOSBox-X AI bridge: {response!r}")

        if response.get("id") != request_id:
            raise DOSBoxProtocolError(
                f"response id {response.get('id')!r} does not match request id {request_id!r}"
            )

        if not response["ok"]:
            error = response.get("error") or {}
            code = error.get("code", "UNKNOWN_ERROR")
            message = error.get("message", "no message")
            exc_class = _NATIVE_ERROR_MAP.get(code, DOSBoxProtocolError)
            exc = exc_class(f"{code}: {message}")
            exc.code = code  # always the exact native code, even under the generic catch-all
            raise exc

        return response.get("result")

    # -- high-level typed methods, matching the native bridge's Phase 3B API --

    def get_debug_status(self) -> dict:
        return self.request("debug.status")

    def get_cpu_state(self) -> dict:
        return self.request("cpu.get")

    def read_memory(self, address: str, length: int) -> dict:
        return self.request("memory.read", {"address": address, "length": length})

    def get_current_instruction(self) -> dict:
        return self.request("code.current")

    def disassemble(self, address: str, count: int) -> list:
        return self.request("code.disassemble", {"address": address, "count": count})

    def write_memory(self, address: str, data: list) -> dict:
        """Write bytes (list of ints 0-255 and/or 2-digit hex strings, e.g.
        [0xB8, "34", "12"]) starting at a "SEG:OFF" address."""

        return self.request("memory.write", {"address": address, "data": list(data)})

    def write_register(self, register: str, value) -> dict:
        """Write one general-purpose register (eax/ebx/ecx/edx/esi/edi/ebp
        only -- EIP, segment registers, ESP, and EFLAGS are rejected by the
        native bridge with DOSBoxRegisterNotWritable). `value` may be an
        int or an up-to-8-digit hex string."""

        if isinstance(value, int):
            if not (0 <= value <= 0xFFFFFFFF):
                raise ValueError(f"register value out of 32-bit range: {value!r}")
            value_str = f"{value:08X}"
        elif isinstance(value, str):
            value_str = value
        else:
            raise TypeError(f"register value must be int or str, got {type(value).__name__}")

        return self.request("register.write", {"register": register, "value": value_str})

    def write_io_port(self, port, value, width: int = 1) -> dict:
        """Write to one whitelisted VGA I/O port (CRTC/Sequencer/Graphics
        Controller/Attribute Controller/DAC/Misc Output/Feature Control --
        see WRITABLE_IO_PORTS in debug_ai.cpp; any other port is rejected
        by the native bridge with DOSBoxPortNotWritable). `port` and
        `value` may each be an int or a hex string; `width` is the write
        size in bytes (1, 2, or 4) and defaults to a single byte."""

        if width not in (1, 2, 4):
            raise ValueError(f"width must be 1, 2, or 4, got {width!r}")
        max_value = (1 << (width * 8)) - 1

        if isinstance(port, int):
            if not (0 <= port <= 0xFFFF):
                raise ValueError(f"port out of 16-bit range: {port!r}")
            port_str = f"{port:04X}"
        elif isinstance(port, str):
            port_str = port
        else:
            raise TypeError(f"port must be int or str, got {type(port).__name__}")

        if isinstance(value, int):
            if not (0 <= value <= max_value):
                raise ValueError(f"value out of {width}-byte range: {value!r}")
            value_str = f"{value:0{width * 2}X}"
        elif isinstance(value, str):
            value_str = value
        else:
            raise TypeError(f"value must be int or str, got {type(value).__name__}")

        return self.request("io.write", {"port": port_str, "value": value_str, "width": width})

    def snapshot_vga(self, regions: list) -> dict:
        """Read raw VGA VRAM -- one or more (plane, offset, length)
        regions, plus the VGA latch and the Sequencer/Graphics Controller/
        CRTC register files -- in one atomic snapshot, entirely bypassing
        the CPU's A000:xxxx read path (see docs/phase8a-vga-snapshot-design.md).

        Unlike memory.read, this never touches vga.latch as a side effect
        and never requires switching the GC's read plane first -- all four
        planes are visible in one call regardless of which plane
        write_io_port most recently selected. Only valid on an EGA/VGA-
        family machine (raises DOSBoxVgaSnapshotUnsupported otherwise).

        `regions` is a list of dicts, each ``{"plane": 0-3, "offset":
        <int or hex str, per-plane byte offset>, "length": <int, bytes>}``.
        The response's ``regions[]`` entries include ``returned_length``,
        which can be less than the requested length (never more) if the
        region ran past ``plane_size_bytes`` -- never an error by itself."""

        if not regions:
            raise ValueError("regions must be a non-empty list")

        params_regions = []
        for r in regions:
            plane = r["plane"]
            if not isinstance(plane, int) or not (0 <= plane <= 3):
                raise ValueError(f"plane must be an int 0-3, got {plane!r}")

            offset = r["offset"]
            if isinstance(offset, int):
                if offset < 0:
                    raise ValueError(f"offset must be non-negative: {offset!r}")
                offset_str = f"{offset:X}"
            elif isinstance(offset, str):
                offset_str = offset
            else:
                raise TypeError(f"offset must be int or str, got {type(offset).__name__}")

            length = r["length"]
            if not isinstance(length, int) or length <= 0:
                raise ValueError(f"length must be a positive int, got {length!r}")

            params_regions.append({"plane": plane, "offset": offset_str, "length": length})

        return self.request("vga.snapshot", {"regions": params_regions})

    def set_breakpoint(self, address: str) -> dict:
        """Set a breakpoint at a "SEG:OFF" address, using DOSBox-X's own
        breakpoint mechanism (CBreakpoint/BPoints -- the same one the
        debugger GUI's BP command uses). Raises DOSBoxBreakpointAlreadyExists
        if a breakpoint already exists at that address."""

        return self.request("breakpoint.set", {"address": address})

    def set_protected_memory_breakpoint(self, address: str) -> dict:
        """Watch one byte at a protected-mode ``SELECTOR:OFFSET`` address.

        Execution stops after the byte's value changes. This uses the native
        debugger's BPPM mechanism and is available only in heavy-debug builds.
        """

        return self.request("breakpoint.memory.set", {"address": address})

    def set_real_memory_breakpoint(self, address: str) -> dict:
        """Watch one byte at a real-mode ``SEGMENT:OFFSET`` address."""

        return self.request("breakpoint.memory.real.set", {"address": address})

    def delete_breakpoint(self, breakpoint_id: int) -> dict:
        """Delete a breakpoint by id (as returned by set_breakpoint/
        list_breakpoints). Ids are positions in DOSBox-X's own breakpoint
        list and shift when breakpoints are added/removed -- call
        list_breakpoints() again if unsure an id is still current. Raises
        DOSBoxBreakpointNotFound if no breakpoint has that id."""

        return self.request("breakpoint.delete", {"id": breakpoint_id})

    def list_breakpoints(self) -> list:
        """List code and memory breakpoints in DOSBox-X's own list."""

        result = self.request("breakpoint.list")
        return result.get("breakpoints", []) if isinstance(result, dict) else []

    def continue_execution(self) -> dict:
        """Resume real guest CPU execution -- the SAME transition the
        debugger GUI's "RUN" command makes (DEBUG_Run()/
        DOSBOX_SetNormalLoop()). Only valid while the debugger is stopped;
        raises DOSBoxAlreadyRunning (native ALREADY_RUNNING) otherwise.
        Returns {"stopped": False, "running": True} -- the guest CPU is
        genuinely running by the time this call returns; it does not wait
        for (or fabricate) a subsequent breakpoint hit."""

        return self.request("execution.continue")

    def pause_execution(self) -> dict:
        """Stop real guest CPU execution and enter the debugger -- the SAME
        transition Ctrl+Pause makes (DEBUG_Enable_Handler()). Only valid
        while guest code is running; raises DOSBoxAlreadyStopped (native
        ALREADY_STOPPED) if the debugger is already stopped. Blocks (on the
        native bridge side) until the pause has genuinely happened -- the
        returned dict is a real debug.status snapshot (location,
        instruction, registers, segments, flags) taken after the CPU
        actually stopped, not merely an acknowledgement that the request
        was received. Raises DOSBoxExecutionTimeout (native
        EXECUTION_TIMEOUT) if it didn't complete in time."""

        return self.request("execution.pause")

    def step_into(self) -> dict:
        """Execute exactly one guest instruction -- the SAME transition the
        debugger GUI's F11 ("trace into") key makes (DEBUG_Run(1,true)).
        Only valid while the debugger is stopped; raises DOSBoxAlreadyRunning
        (native ALREADY_RUNNING) otherwise. Always synchronous: blocks until
        the real DOSBox-X CPU decoder has genuinely executed the instruction,
        and returns a real debug.status snapshot (location, instruction,
        registers, segments, flags) taken after it stopped again -- the
        same shape pause_execution() returns."""

        return self.request("execution.step_into")

    def step_over(self) -> dict:
        """Step over the current instruction -- the SAME transition the
        debugger GUI's F10 ("step over") key makes (StepOver()+DEBUG_Run()).
        For an ordinary instruction this behaves exactly like step_into().
        For a call/int/loop/rep instruction, DOSBox-X's own StepOver()
        places a one-shot breakpoint just past it and lets the subroutine
        run for real; this call blocks (on the native bridge side) until
        that breakpoint (or any other event) re-enters the debugger, then
        returns the real post-step debug.status snapshot, exactly like
        step_into(). Only valid while the debugger is stopped; raises
        DOSBoxAlreadyRunning (native ALREADY_RUNNING) otherwise. Raises
        DOSBoxExecutionTimeout (native EXECUTION_TIMEOUT) if the
        stepped-over call/int/loop/rep does not return within the
        timeout -- call get_debug_status() afterward to check whether it
        completed shortly after."""

        return self.request("execution.step_over")

    # -- guest input injection (Phase 6B) --
    #
    # These inject keyboard/mouse input through the SAME internal path
    # DOSBox-X's own SDL event handlers use (KEYBOARD_AddKey(), Mouse_*())
    # -- never Windows SendKeys, window focus/handle manipulation, or GUI
    # automation of the DOSBox-X window itself. Only valid while guest
    # execution is running (i.e. NOT stopped in the debugger): raises
    # DOSBoxDebuggerStopped (native DEBUGGER_STOPPED) otherwise -- call
    # continue_execution() first.
    #
    # `key` names are a fixed, auditable whitelist covering the standard
    # US 104-key layout (see ParseKeyName() in debug_ai.cpp) -- e.g. "a",
    # "1", "f1", "enter", "leftshift", "kp5". Arbitrary text/scan codes are
    # not accepted in this v1.
    #
    # Every method below (key_down/up/tap, move_mouse_relative,
    # set_mouse_button, click_mouse -- and move_mouse_absolute()/click_at()
    # further down) also returns "queued": true, "dispatched": true,
    # "dispatched_at_emulated_ms": int, "input_sequence": int, and
    # "guest_observed": "not_supported" alongside its own result field
    # (Phase 7C). "input_sequence" is a single shared, monotonically
    # increasing space across ALL of these methods -- pass it to
    # get_input_receipt() later to look the dispatch back up. release_all_input()
    # does NOT get these fields: it releases an arbitrary number of keys/
    # buttons at once, so no single input_sequence would describe it.

    def key_down(self, key: str) -> dict:
        """Press and hold `key`. The bridge tracks held keys per
        connection and releases anything still held if this connection
        disconnects (client crash or session timeout) -- see
        release_all_input()."""

        return self.request("input.key.down", {"key": key})

    def key_up(self, key: str) -> dict:
        """Release `key` (previously pressed with key_down())."""

        return self.request("input.key.up", {"key": key})

    def key_tap(self, key: str) -> dict:
        """Press and immediately release `key` -- the common case for
        advancing dialogue/menus (e.g. key_tap("enter"))."""

        return self.request("input.key.tap", {"key": key})

    def move_mouse_relative(self, dx: float, dy: float) -> dict:
        """Move the guest mouse cursor by a relative (dx, dy) delta, the
        same way real relative mouse motion does. Only affects the guest
        if DOSBox-X's mouse is currently captured/locked (Ctrl+F10) and the
        guest is running a mouse driver that reads relative motion -- this
        does not itself toggle mouse capture."""

        return self.request("input.mouse.move_relative", {"dx": dx, "dy": dy})

    def set_mouse_button(self, button: int, pressed: bool) -> dict:
        """Press or hold (pressed=True) / release (pressed=False) a mouse
        button. `button` is 0 (left), 1 (right), or 2 (middle). Like
        key_down(), held buttons are tracked per connection and
        auto-released on disconnect."""

        return self.request("input.mouse.button.set", {"button": button, "pressed": pressed})

    def click_mouse(self, button: int) -> dict:
        """Press and immediately release a mouse button. `button` is 0
        (left), 1 (right), or 2 (middle)."""

        return self.request("input.mouse.button.click", {"button": button})

    def release_all_input(self) -> dict:
        """Release every key/mouse button this connection currently holds
        down. Call this at the end of a session as a good citizen -- the
        bridge also does this automatically if the connection is lost
        (client crash, session timeout) without it ever being called."""

        return self.request("input.release_all")

    # -- guest framebuffer capture (Phase 7A) --

    def capture_frame(
        self,
        format: str = "png",
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
    ) -> dict:
        """Capture exactly the guest's own rendered frame -- never the
        DOSBox-X window, the host desktop, or any other host window --
        through the SAME internal hook DOSBox-X's own Host+P screenshot
        and AVI recording already use (RENDER_EndUpdate(), never written
        to disk here). `format` is "png" or "rgba" (raw rgba8888,
        base64-encoded either way, under "png_base64"/"rgba_base64" in
        the result). Native pixel data (indexed/15-bit/16-bit/24-bit/
        32-bit) is always unpacked to rgba8888 before encoding, regardless
        of format.

        Meaningful whether the debugger is stopped or running, but a
        fully halted guest is not producing new rendered frames (VGA
        vertical-retrace events are PIC-driven and don't fire while
        Normal_Loop() doesn't have control) -- expect
        DOSBoxExecutionTimeout in that case more often than not; call
        continue_execution() first for reliable captures.

        `max_width`/`max_height` downscale (nearest-neighbor, aspect
        ratio preserved) if the native frame would exceed them; omit for
        native resolution. Raises DOSBoxFrameTooLarge (native
        FRAME_TOO_LARGE) if the encoded frame still exceeds the bridge's
        payload cap -- its message includes a suggested smaller
        max_width/max_height to retry with."""

        params = {"format": format, "include_cursor": False}
        if max_width is not None:
            params["max_width"] = max_width
        if max_height is not None:
            params["max_height"] = max_height
        return self.request("video.frame.capture", params)

    # -- mouse capture status & absolute positioning (Phase 7B) --

    def get_mouse_capture(self) -> dict:
        """Read DOSBox-X's own mouse-capture state (whether Ctrl+F10 is
        currently "on") and absolute-positioning capability, without
        touching the host cursor or window focus. Meaningful whether the
        debugger is stopped or running, unlike move_mouse_absolute()/
        click_at() below.

        Result: {"captured": bool, "autolock": bool,
        "mode": "absolute"|"relative"|"unavailable", "guest_width":
        int|None, "guest_height": int|None, "last_guest_x": int|None,
        "last_guest_y": int|None}. "guest_width"/"guest_height" match
        capture_frame()'s own reported width/height for the current video
        mode (both derive from the same DOSBox-X render state) -- use
        them to convert a pixel picked from a capture_frame() screenshot
        into click_at()'s "guest_pixels" coordinate space directly.

        IMPORTANT: "guest_width"/"guest_height" are the RENDERED
        (screenshot) size, not necessarily the guest video mode's
        nominal/native resolution -- DOSBox-X's own display layer
        pixel-doubles (and/or line-doubles) low-resolution modes for
        on-screen viewing. Mode 13h (INT 10h AH=00h,AL=13h), for
        example, is nominally 320x200 but reports/renders as 640x400
        here. If your own coordinates come from something other than an
        actual capture_frame() screenshot (e.g. reading VRAM directly,
        or matching against native-resolution reference images), scale
        them up to this call's actual guest_width/guest_height first --
        do not assume any fixed resolution, and do not pass
        native-resolution numbers straight through (they will land at
        exactly half the intended position on both axes for a doubled
        mode like this).

        "last_guest_x"/"last_guest_y" are the bridge's last successfully
        dispatched position, not a claim about what the guest program
        actually read."""

        return self.request("input.mouse.capture.get")

    def set_mouse_capture(self, captured: bool) -> dict:
        """Toggle DOSBox-X's own mouse capture, the exact same effect as
        the user pressing Ctrl+F10 -- never moves the host cursor,
        changes window focus, or affects any other program. Meaningful
        whether the debugger is stopped or running. Returns the same
        shape as get_mouse_capture(). Raises DOSBoxCaptureUnavailable
        (native CAPTURE_UNAVAILABLE) if the current video backend has no
        safely controllable capture state."""

        return self.request("input.mouse.capture.set", {"captured": captured})

    def move_mouse_absolute(
        self,
        x: float,
        y: float,
        coordinate_space: str = "guest_pixels",
        clamp: bool = False,
    ) -> dict:
        """Move the guest mouse cursor to an absolute position, through
        the SAME internal DOSBox-X path used for seamless/integrated
        mouse positioning (not a bridge invention) -- unlike
        move_mouse_relative(), this does not require mouse capture to be
        on. Only reaches the guest while it is running (not stopped);
        raises DOSBoxDebuggerStopped otherwise, like every other input.*
        method.

        `coordinate_space` is "guest_pixels" (origin top-left, matching
        capture_frame()'s reported width/height -- see
        get_mouse_capture(), including its important caveat that this is
        screenshot-pixel space, not necessarily the guest video mode's
        nominal resolution) or "normalized" ([0.0, 1.0] x [0.0, 1.0]).
        Out-of-range coordinates raise DOSBoxProtocolError
        (INVALID_PARAMETER) unless `clamp=True`, in which case they are
        clamped to the guest's bounds and the result's "clamped" field is
        true. Raises DOSBoxAbsoluteMouseUnavailable (native
        ABSOLUTE_MOUSE_UNAVAILABLE) if absolute positioning is not
        currently usable in the guest's mode -- check
        get_mouse_capture()'s "mode" field first if unsure.

        Result: {"queued": true, "dispatched": true, "guest_x": number,
        "guest_y": number, "coordinate_space": "guest_pixels",
        "clamped": bool, "input_sequence": int,
        "dispatched_at_emulated_ms": int, "guest_observed":
        "not_supported"} -- guest_x/guest_y are always reported in
        guest_pixels, even for a normalized-space request. See
        get_input_receipt()."""

        return self.request(
            "input.mouse.move_absolute",
            {"x": x, "y": y, "coordinate_space": coordinate_space, "clamp": clamp},
        )

    def click_at(
        self,
        x: float,
        y: float,
        button: int = 0,
        coordinate_space: str = "guest_pixels",
        clamp: bool = False,
    ) -> dict:
        """Move to an absolute position and click, in a single
        emulator-thread dispatch -- nothing else can insert between the
        move and the click. `button` is 0 (left), 1 (right), or 2
        (middle). See move_mouse_absolute() for `coordinate_space`,
        `clamp`, error conditions, and the result shape (this adds
        "clicked": true)."""

        return self.request(
            "input.mouse.click_at",
            {"x": x, "y": y, "button": button, "coordinate_space": coordinate_space, "clamp": clamp},
        )

    # -- input dispatch receipts (Phase 7C) --

    def get_input_receipt(self, input_sequence: int) -> dict:
        """Look up an earlier key/mouse dispatch by the "input_sequence"
        one of the input.* methods above returned, whether the debugger
        is currently stopped or running. Raises DOSBoxInputReceiptExpired
        (native INPUT_RECEIPT_EXPIRED) if that sequence isn't in the
        bridge's ring buffer (at least the most recent 4096 dispatches or
        10 minutes' worth, whichever bound is hit first) -- indistinguishable
        from an input_sequence that was never issued.

        Result: {"queued": true, "dispatched": true,
        "dispatched_at_emulated_ms": int, "input_sequence": int,
        "guest_observed": "not_supported", "device": "keyboard"|"mouse",
        "guest_observation": {"kind": None, "observed_at_emulated_ms":
        None}}. "guest_observed"/"guest_observation" are always
        "not_supported"/null in this implementation -- real DOS/BIOS-side
        observation is reserved schema, not yet implemented."""

        return self.request("input.receipt.get", {"input_sequence": input_sequence})

    # -- bounded execution trace around a breakpoint hit (Phase 7D) --

    def configure_execution_trace(
        self,
        enabled: bool,
        before_instructions: int = 0,
        after_instructions: int = 0,
        registers: Optional[list] = None,
        include_disassembly: bool = True,
        max_trace_bytes: int = 65536,
    ) -> dict:
        """Turn automatic execution tracing on/off. While enabled, every
        time the debugger genuinely stops (a code/memory breakpoint, a
        manual pause_execution()/Ctrl+Pause, or -break-start) a trace is
        captured automatically -- covering the `before_instructions`
        instructions leading up to (and including) the stop, and, if
        `after_instructions` > 0, that many instructions executed
        immediately afterward (the debugger's own visible stop position
        moves to reflect this -- it will be `after_instructions`
        instructions past the original trigger, not at the trigger
        itself). Meaningful whether the debugger is stopped or running.

        `before_instructions`/`after_instructions` are each 0..4096.
        `registers` restricts which of "ax","bx","cx","dx","si","di",
        "bp","sp","cs","ip","flags" each captured instruction reports;
        omit for all of them. `max_trace_bytes` (65536..4194304) bounds
        one trace's total size -- if exceeded, the oldest `before`
        instructions are dropped first (see the result's
        `dropped_instruction_count`), never truncating `after` ahead of
        `before`.

        Turning this OFF (the default) leaves breakpoint stop semantics
        and performance completely unchanged from before this feature
        existed -- this reuses DOSBox-X's own existing heavy-debug
        instruction log (the same state its "LOG HEAVY" debugger-console
        command uses) rather than a separate bridge-only mechanism, so a
        human using that console command at the same time shares the
        same state. Fails with INTERNAL_ERROR on a build without
        C_HEAVY_DEBUG (this project's own default build already has it
        on).

        Result: {"enabled": bool, "configuration": {...}} (echoes back
        the resolved configuration)."""

        params = {
            "enabled": enabled,
            "before_instructions": before_instructions,
            "after_instructions": after_instructions,
            "include_disassembly": include_disassembly,
            "max_trace_bytes": max_trace_bytes,
        }
        if registers is not None:
            params["registers"] = registers
        return self.request("trace.execution.configure", params)

    def list_execution_traces(self, limit: int = 100, after_trace_id: Optional[int] = None) -> dict:
        """List captured traces (newest-eligible-first up to `limit`,
        1..100), each summarized (not the full before/after instruction
        arrays -- call get_execution_trace() for those). `after_trace_id`
        restricts to traces newer than a given id, for incremental
        polling. Meaningful whether the debugger is stopped or running.

        Result: {"traces": [{"trace_id", "trigger", "before_count",
        "after_count", "complete_after"}, ...], "dropped_traces": int}
        -- the bridge retains at most the 100 most recent traces,
        evicting the oldest; `dropped_traces` counts how many have been
        evicted in total."""

        params = {"limit": limit}
        if after_trace_id is not None:
            params["after_trace_id"] = after_trace_id
        return self.request("trace.execution.list", params)

    def get_execution_trace(self, trace_id: int) -> dict:
        """Fetch one trace's full detail by id (from
        list_execution_traces() or a trace captured while you were
        watching). Raises DOSBoxTraceNotFound (native TRACE_NOT_FOUND) if
        that id isn't currently retained -- indistinguishable from one
        that was never issued.

        Result: {"trace_id", "trigger": {"kind":
        "code_breakpoint"|"memory_breakpoint"|"manual_pause",
        "breakpoint_id", "location", "emulated_ms"}, "before": [...],
        "after": [...], "complete_after": bool,
        "dropped_instruction_count": int}. Each before/after entry is
        {"ordinal", "location", "bytes_hex", "disassembly",
        "registers"}. `before`'s last entry is the trigger instruction
        itself for a code_breakpoint/memory_breakpoint trigger (DOSBox-X's
        heavy-debug log records an instruction immediately before
        checking whether it's a breakpoint) -- for a manual_pause
        trigger, the pause interrupts between the heavy-debug log's own
        per-instruction checks, so `before`'s last entry is one
        instruction short of the trigger location instead. `after`'s
        entries are the instructions that ran after the trigger, in
        execution order; `complete_after=false` if stepping through them
        was cut short by hitting another breakpoint."""

        return self.request("trace.execution.get", {"trace_id": trace_id})

    # -- DOS file I/O event log (Phase 7E) --

    def configure_dos_io_log(
        self,
        enabled: bool,
        operations: Optional[list] = None,
        path_globs: Optional[list] = None,
        include_failed: bool = True,
        max_events: int = 10000,
    ) -> dict:
        """Turn DOS file I/O event logging on/off. While enabled, every
        completed `INT 21h` `open`(3Dh)/`close`(3Eh)/`read`(3Fh)/
        `write`(40h)/`seek`(42h) call is recorded with its real result
        (actual bytes transferred, AX, carry) -- never merely the
        request. Meaningful whether the debugger is stopped or running.

        `operations` restricts which of "open"/"close"/"read"/"write"/
        "seek" are logged (omit for all five). `path_globs` (e.g.
        `["*.GFF", "SAVE-*"]`, case-insensitive, `*`/`?` wildcards)
        restricts to matching DOS paths -- events for non-matching paths
        are never recorded, not merely hidden. `include_failed` (default
        True) also logs failed calls (e.g. opening a nonexistent file).
        `max_events` (100..100000, default 10000) bounds the ring
        buffer -- oldest events are evicted first once full (see
        list_dos_io_events()'s `dropped_events`).

        Result: {"enabled": bool, "max_events": int}."""

        params = {
            "enabled": enabled,
            "include_failed": include_failed,
            "max_events": max_events,
        }
        if operations is not None:
            params["operations"] = operations
        if path_globs is not None:
            params["path_globs"] = path_globs
        return self.request("dos.io.configure", params)

    def list_dos_io_events(
        self,
        limit: int = 1000,
        after_event_id: Optional[int] = None,
        operation: Optional[str] = None,
        path_glob: Optional[str] = None,
    ) -> dict:
        """List recorded DOS file I/O events (oldest-eligible-first up
        to `limit`, 1..1000). `after_event_id` restricts to events newer
        than a given id, for incremental polling; `operation`/
        `path_glob` filter the already-recorded events further (on top
        of whatever configure_dos_io_log() itself was already
        restricted to). Meaningful whether the debugger is stopped or
        running.

        Result: {"events": [DosIoEvent, ...], "dropped_events": int}.
        Each event: {"event_id", "emulated_ms", "operation",
        "phase": "completed", "cs_ip", "process": {"psp_segment"},
        "handle", "path_dos", "path_host", "file_offset_before",
        "requested_bytes", "transferred_bytes", "buffer": {"segment",
        "offset", "linear"}, "result": {"carry", "ax", "dos_error"}}.
        `path_host` is only populated for a real mounted host directory
        (a plain `MOUNT C C:\\some\\folder`-style drive) -- null for
        image-mounted/ISO/network drives. `buffer.linear` lets you
        correlate a read with a later memory watchpoint on that same
        address (see docs/case-study-dark-sun-gpli-debugging.md for a
        worked example of exactly this)."""

        params = {"limit": limit}
        if after_event_id is not None:
            params["after_event_id"] = after_event_id
        if operation is not None:
            params["operation"] = operation
        if path_glob is not None:
            params["path_glob"] = path_glob
        return self.request("dos.io.list", params)

    def clear_dos_io_log(self) -> dict:
        """Discard every currently recorded DOS file I/O event (does not
        change the current configure_dos_io_log() configuration, and
        does not stop logging). Result: {"cleared": true}."""

        return self.request("dos.io.clear")
