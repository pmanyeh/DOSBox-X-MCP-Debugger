# Phase 8A: side-effect-free VGA VRAM snapshot (`vga.snapshot`)

> Scope: Priority 1 of client feedback on the Mode X "bottom 30 lines get
> cleared, owned path doesn't repaint" investigation (see
> `docs/case-study-dark-sun-gpli-debugging.md` for the class of problem this
> generalizes). Status: design, grounded in source investigation. Not yet
> implemented.
>
> Priority 2 of the same feedback (`vga.watch_writes`, a real VRAM
> write-tracking breakpoint keyed on plane+offset) is deliberately deferred
> -- the client's own acceptance note says Priority 1 alone is enough to
> substantially unblock the current diagnosis, and does not require
> Priority 2 first. Tracked as future work in "Non-goals" below.

## Goal

Let an agent read raw VGA VRAM -- several planes, several byte ranges, plus
the VGA latch and the Sequencer/Graphics Controller/CRTC register files --
in one atomic snapshot, through a path that:

1. Never goes through the CPU's `A000:xxxx` read path (`mem_readb_checked`
   or any `PageHandler`), because that path has a genuine hardware side
   effect: any GC read-mode-0 byte read latches all four planes into
   `vga.latch` (`VGA_Generic_Read_Handler`,
   `dosbox-src/src/hardware/vga_memory.cpp:313`) as an unavoidable
   consequence of real VGA hardware behavior. A diagnostic read must not be
   able to silently corrupt the latch state a `write_mode 1` operation
   would depend on if the guest resumes afterward -- exactly the
   "diagnosis changes the state you're diagnosing" failure this tool
   exists to rule out.
2. Never requires switching the GC's Read Map Select register (`write_io_port`
   to `3CE`/`3CF`) to see a different plane, because that write is itself a
   guest-visible state change (and, per the client's report, one more thing
   that could race with -- or be mistaken for -- the actual bug).
3. Reads every requested plane/region, the latch, and all three register
   files from one consistent instant, since the whole point is comparing
   "what four planes independently contain right now" without the guest
   getting to run (and repaint, or clear something else) between reads of
   plane 0 and plane 3.

## Why this is possible at all: standard VGA planar VRAM is plane-interleaved by hardware, at a fixed layout independent of mode

`dosbox-src/include/vga.h:713-739` (`VGA_Type_t`) stores actual VRAM in
`vga.mem.linear` (a flat `uint8_t*` of `vga.mem.memsize` bytes). For any
EGA/VGA-family machine, four separate plane chips are wired behind one
32-bit-wide memory bus -- DOSBox-X models this by interleaving the four
planes as bytes of a `uint32_t`, confirmed at the two actual read/write
call sites for planar VGA memory
(`dosbox-src/src/hardware/vga_memory.cpp:313,383`):

```cpp
vga.latch.d = ((uint32_t*)vga.mem.linear)[planeaddr];   // read (VGA_Generic_Read_Handler)
((uint32_t*)vga.mem.linear)[planeaddr] = pixels.d;       // write (VGA_Generic_Write_Handler)
```

i.e. for plane `p` (0-3) and a *per-plane* byte offset `o`, the byte lives
at native index `o*4 + p` of `vga.mem.linear`. This layout is a physical
memory-bus property, not a mode setting -- it is exactly as true for text
mode (plane 0 = character codes, plane 1 = attributes, plane 2 = font data)
as it is for 16-color EGA/VGA graphics and for chain-4-disabled 256-color
modes like Mode X (which is exactly why Mode X's "read plane"/"write
plane" tricks exist: chain-4 is off, so the CPU-visible byte at a given
`A000:xxxx` address is genuinely ambiguous between four independent plane
bytes, resolved only by the currently selected read/write plane). This is
also why `vga.snapshot` needs no per-mode special-casing: `o*4+p` addresses
the same physical byte regardless of what mode the VGA happens to be in,
so a snapshot taken while stopped inside a Mode X program reads exactly
the same way a snapshot taken in text mode would.

`vga.latch` (`VGA_Latch`, `include/vga.h:608-614`) is a plain `union { uint32_t
d; uint8_t b[4]; }` -- one byte per plane, the value every plane's read/write
handler already uses as scratch space for GC read-mode-1/write-mode-1
operations. Reading `vga.latch.d`/`.b[]` directly is a plain field read: it
has no side effect on its own (only the *CPU-visible* `A000:xxxx` read path
mutates it, per point 1 above).

`vga.seq`/`vga.gfx`/`vga.crtc` (`VGA_Seq`/`VGA_Gfx`/`VGA_Crtc`,
`include/vga.h:497-552`) each already store every register DOSBox-X models
for that controller, including its own currently-selected `index` field
(the value last written to its address port -- `3C4`/`3CE`/`3D4`
respectively). No new state or computation is needed for any of this --
it's a direct field dump.

## Why this must run only while genuinely stopped

`vga.snapshot` reuses the exact `g_requestQueue`/`DEBUG_AI_Poll()` mechanism
`memory.read`/`memory.write`/`register.write`/`io.write` already use
(`dosbox-src/src/debug/debug_ai.cpp:373-390,2371-2401`): `HandleLine()`
(socket thread) validates params and pushes an `AIRequestItem`, then blocks
on that connection's response slot; `g_requestQueue` is drained only by
`DEBUG_AI_Poll()`, called from inside the debugger's own loop, which by
construction only runs while the CPU is genuinely paused
(`debug_ai.cpp:3460-3492`: if the debugger never reaches a stopped state
within `REQUEST_TIMEOUT_SECONDS`, the request times out as
`DEBUGGER_NOT_STOPPED` rather than ever executing). This is what makes "one
snapshot, one consistent instant" automatic rather than something the new
code has to re-implement: the guest CPU cannot run between reading plane 0
and reading plane 3, or between reading the latch and reading the register
files, because nothing drains the queue except a debugger loop iteration
that only happens while stopped.

The exec function itself (`ExecVgaSnapshot()`, by analogy with
`ExecMemoryRead()`/`ExecIoWrite()`, `debug_ai.cpp:1635,1711`) only reads:
`vga.mem.linear[...]`, `vga.latch.d`, and the three register structs' plain
fields. It never calls `IO_WriteB`/`IO_WriteW`, never writes `vga.latch`,
never writes any register field, never touches `cpu_regs`/`Segs`/`reg_eip`,
and never calls a stepping or continue function -- so by construction it
cannot change latch, registers, CPU state, memory, or execution position,
and cannot itself resume or step the guest.

## Supported machines: EGA/VGA family only, explicit error otherwise

`vga.snapshot` requires `IS_EGAVGA_ARCH` (`include/dosbox.h:216`, i.e.
`machine == MCH_EGA || machine == MCH_VGA`) -- the plane-interleaved
`o*4+p` layout above is specific to how DOSBox-X models EGA/VGA VRAM. CGA,
Hercules, Tandy/PCjr, and PC-98 graphics use entirely different `vga.mem.linear`
layouts (see e.g. the PC-98 GDC framebuffer handling elsewhere in
`vga_memory.cpp`), so a snapshot taken against one of those would either
silently return meaningless bytes or need per-machine layout logic this
phase does not add. `machine` is not one of `MCH_EGA`/`MCH_VGA` is rejected
up front with a dedicated `VGA_SNAPSHOT_UNSUPPORTED` error (mirroring how
`io.write`/`register.write` reject out-of-scope input with their own
dedicated codes rather than a generic failure) -- never a guess at what the
bytes might mean.

## Request/response shape

```jsonc
// request
{"id": 1, "method": "vga.snapshot", "params": {
  "regions": [
    {"plane": 0, "offset": "3520", "length": 2400},
    {"plane": 1, "offset": "3520", "length": 2400},
    {"plane": 2, "offset": "3520", "length": 2400},
    {"plane": 3, "offset": "3520", "length": 2400}
  ]
}}
```

`plane`: integer 0-3. `offset`: a per-plane byte offset, as a hex string
(no `0x` prefix, matching `memory.read`'s `address`/`io.write`'s `port`
convention elsewhere in this protocol) -- e.g. `"3520"`, `"7520"`, `"0"`,
`"4000"`, matching the client's own four required regions (bottom 30 lines
of page 1/page 2 at `0x3520`/`0x7520` for 2,400 bytes each; full page 1/page
2 at `0x0000`/`0x4000` for 16,000 bytes each -- all four planes, per plane,
in one call). `length`: a plain integer, byte count within that plane,
reusing `MAX_READ_LENGTH` (65536) as the per-region cap and a new
`MAX_VGA_SNAPSHOT_REGIONS` (64) as the array-size cap -- generous enough for
every region in the client's own request, nowhere near the cost of a real
abuse case since this is a local, single-connection debug bridge to begin
with.

```jsonc
// response
{"id": 1, "ok": true, "result": {
  "layout": "planar_interleaved_dword",
  "layout_note": "4-plane EGA/VGA VRAM as physically wired: for plane p (0-3) and a byte offset o within that plane, the byte lives at native VRAM index o*4+p. offset/length here are already per-plane byte units.",
  "plane_count": 4,
  "plane_size_bytes": 65536,
  "latch": {"bytes_hex": "AABBCCDD", "planes": [170, 187, 204, 221]},
  "registers": {
    "sequencer": {"index": 2, "reset": 3, "clocking_mode": 1, "map_mask": 15, "character_map_select": 0, "memory_mode": 6},
    "graphics_controller": {"index": 8, "set_reset": 0, "enable_set_reset": 0, "color_compare": 0, "data_rotate": 0, "read_map_select": 0, "mode": 0, "miscellaneous": 5, "color_dont_care": 15, "bit_mask": 255},
    "crtc": {"index": 24, "horizontal_total": 95, "...": "...every VGA_Crtc field, dumped verbatim"}
  },
  "regions": [
    {"plane": 0, "offset": "3520", "requested_length": 2400, "returned_length": 2400, "bytes_base64": "..."},
    {"plane": 1, "offset": "3520", "requested_length": 2400, "returned_length": 2400, "bytes_base64": "..."},
    {"plane": 2, "offset": "3520", "requested_length": 2400, "returned_length": 2400, "bytes_base64": "..."},
    {"plane": 3, "offset": "3520", "requested_length": 2400, "returned_length": 2400, "bytes_base64": "..."}
  ]
}}
```

`returned_length` can be less than `requested_length` (never more) when
`offset+length` runs past `plane_size_bytes` -- clamped rather than
rejected, since `plane_size_bytes` is reported in the same response and an
agent asking for a round region size (like the client's own 16,000-byte
full-page reads) should not have to already know the exact plane size to
avoid an error. `bytes_base64` reuses the existing `Base64Encode()` helper
(`debug_ai.cpp:1240`, already used by `video.frame.capture`).

## Errors

| Code | When |
|---|---|
| `INVALID_PARAMETER` | missing/malformed `params.regions`, empty array, more than `MAX_VGA_SNAPSHOT_REGIONS` entries, `plane` not an integer 0-3, `offset` not a hex string, `length` not a positive integer within `MAX_READ_LENGTH` |
| `VGA_SNAPSHOT_UNSUPPORTED` | `!IS_EGAVGA_ARCH` (machine is CGA/Hercules/Tandy/PCjr/PC-98) |
| `DEBUGGER_NOT_STOPPED` | automatic, from the existing `g_requestQueue` timeout path -- the debugger never reached a stopped state within `REQUEST_TIMEOUT_SECONDS` |

## Non-goals

- No write path of any kind -- `vga.snapshot` is read-only by construction
  (see "Why this must run only while genuinely stopped" above).
- No Attribute Controller register dump -- the client's request named only
  Sequencer/Graphics Controller/CRTC; the Attribute Controller's index also
  carries an internal flip-flop bit DOSBox-X doesn't expose as a plain
  field the same way, so it's left out rather than guessed at. Trivial to
  add later if a future case needs it.
- **`vga.watch_writes`** (Priority 2 of the client's feedback: a real
  VRAM-write breakpoint keyed on plane+offset range, distinguishing the
  writing instruction's `CS:IP` from the stop location, with first-hit or
  bounded-capacity event recording) is not designed or implemented in this
  phase. The client's own acceptance note is explicit that Priority 1 alone
  is sufic to substantially unblock the current diagnosis without needing Priority 2 first, so this
  phase implements Priority 1 only; tracked as a follow-up phase (8B) if/when the
  plane+offset write-tracking question comes up again.

## Implementation touches (four files, mirroring Phase 7E's shape)

1. `dosbox-src/src/debug/debug_ai.cpp`: `#include "vga.h"`; `AIMethod::VgaSnapshot`;
   a `VgaSnapshotRegion {uint8_t plane; uint32_t offset; uint32_t length;}`
   struct and `std::vector<VgaSnapshotRegion> vgaRegions` field on
   `AIRequestItem`; parsing/validation in `HandleLine()`; `ExecVgaSnapshot()`
   next to `ExecMemoryRead()`/`ExecIoWrite()`; a case in `ExecuteRequest()`'s
   switch; `MAX_VGA_SNAPSHOT_REGIONS`.
2. `ai/dosbox_client.py`: `DOSBoxVgaSnapshotUnsupported` (native
   `VGA_SNAPSHOT_UNSUPPORTED`) and `snapshot_vga(regions)`.
3. `ai/server.py`: the `vga_snapshot` MCP tool.
4. `AGENT_GUIDE.md`/`.zh-TW.md`, `README.md`/`.zh-TW.md` (tool count),
   `CHANGELOG.md`.

## Verification plan

Mirrors this project's live-instance verification pattern (a real running
`dosbox-x.exe`, stopped at a breakpoint, driven through the actual MCP tool
-- not a protocol-level echo test).

1. The client's own four required regions in one call (bottom 30 lines of
   page 1/page 2 at plane offsets `0x3520`/`0x7520`, 2,400 bytes each, all
   four planes) -- confirms multi-region, multi-plane reads in a single
   round trip.
2. The two full-page reads (`0x0000`/`0x4000`, 16,000 bytes each, all four
   planes) in the same call as (1) -- eight regions total, confirms the
   region-array cap and per-region length cap are both comfortably above
   what a real diagnostic call needs.
3. **The acceptance criterion that matters most**: call `vga.snapshot`
   twice in a row with the debugger stopped, and diff the two responses'
   `latch`/`registers` -- they must be bit-for-bit identical. Then
   `execution.continue` and confirm the on-screen picture is unaffected
   (i.e. behaves identically to a debugging session that never called
   `vga.snapshot` at all).
4. A non-EGA/VGA machine type (or a forced-unsupported path, if no such
   machine is easy to boot in this environment) produces
   `VGA_SNAPSHOT_UNSUPPORTED`, not fabricated/zeroed data.
5. `returned_length < requested_length` when a region's `offset+length`
   deliberately overruns `plane_size_bytes`, with the correct clamped byte
   count.

## Implementation status: done, verified live for (1)-(3)/(5); (4) reasoned from source, not exercised; the real-game repaint comparison still outstanding

Implemented as designed, in `dosbox-src/src/debug/debug_ai.cpp`
(`AIMethod::VgaSnapshot`, `VgaSnapshotRegion`, the `vga.snapshot` parsing
branch, `ExecVgaSnapshot()`), `ai/dosbox_client.py`
(`DOSBoxVgaSnapshotUnsupported`, `snapshot_vga()`), and `ai/server.py`
(`vga_snapshot`). Built clean (0 errors) against `Release`/`x64`.

Verified live against a real, running `dosbox-x.exe`
(`-break-start drive_c\STEP.COM`, this project's own minimal test binary,
stopped at its entry point in default text mode) via `ai/dosbox_client.py`
directly (not through the MCP tool layer -- the MCP host's already-running
`ai/server.py` process predates this session's edits to that file and
would need restarting to pick up `vga_snapshot`, exactly the kind of
stale-process gap `docs/deferred-tools-snapshot-per-conversation` class of
issue describes):

1. The client's own 16-region request (both required region shapes, all
   four planes, one call) -- every region's `returned_length` matched its
   `requested_length` (2,400/2,400/16,000/16,000 bytes), and
   `plane_size_bytes` (524,288 -- this build's default S3 SVGA VRAM size)
   was reported correctly.
2. Called twice in a row while stopped: `latch` and all three register
   groups came back bit-for-bit identical both times, and so did every
   region's bytes.
3. `continue_execution()` immediately afterward returned the normal
   `{"stopped": false, "running": true}`, and `get_debug_status()`'s
   `location` was identical before and after the pair of snapshot calls --
   no evidence of any execution-position side effect.
5. A deliberately overrunning region (`offset = plane_size_bytes - 100`,
   `length = 500`) correctly clamped to `returned_length = 100`, not an
   error.

Not independently exercised live this session: (4) a non-EGA/VGA machine
producing `VGA_SNAPSHOT_UNSUPPORTED` (reasoned correct from the
`IS_EGAVGA_ARCH` gate in the source, not run against an actual CGA/
Hercules/PC-98 session), and the actual "on-screen picture identical
around a real Mode X repaint" comparison this tool exists to enable --
`STEP.COM` is a synthetic stepping test binary with no real graphics
output, not the client's own Mode X game, so that comparison still needs
to be run directly against that game as a follow-up.
