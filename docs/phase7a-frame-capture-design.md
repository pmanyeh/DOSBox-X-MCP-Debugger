# Phase 7A: guest framebuffer capture (`video.frame.capture`)

> Scope: Epic A of `docs/phase7-observability-and-autonomous-control-requirements.md`.
> Status: design, grounded in source investigation. Not yet implemented.

## Goal

Let an AI agent see exactly what the guest DOS program is currently
displaying -- as a PNG or raw RGBA image -- on demand, without depending
on the host desktop, without reading host windows, and without stopping
guest execution. This closes the biggest observability gap remaining
after Phase 6A (memory watchpoints) and Phase 6B (input injection): an
agent can already read/write memory and inject input, but has had no way
to see the resulting picture except a human describing it, which is
exactly the kind of host-dependency this project has consistently avoided
for input (see `docs/phase6b-input-injection-design.md`'s "Non-goals").

## Non-goals (from the Phase 7 draft, section 3/9, restated for this doc)

- Not a screenshot of the DOSBox-X window, the SDL/GL surface as
  presented, or the host desktop -- if another window is on top of
  DOSBox-X, the captured image must be unaffected.
- No OCR, image understanding, or object recognition -- pixels only.
- No video stream -- one frame per request, on demand.
- Does not stop or pause the guest to take the picture.

## Architecture: reuse DOSBox-X's own screenshot mechanism

DOSBox-X already has a working, backend-agnostic frame-capture path used
by its screenshot (Host+P) and AVI-recording features. Phase 7A reuses
its *hook point*, not its file-writing behavior.

### The existing path

- `CAPTURE_ScreenShotEvent()` (`src/hardware/hardware.cpp:1610`), bound to
  Host+P via `MAPPER_AddHandler(..., "scrshot", ...)`
  (`hardware.cpp:2261`), sets `CaptureState |= CAPTURE_IMAGE`. The actual
  PNG write is lazy -- it happens on the *next* rendered frame, not
  synchronously.
- `RENDER_EndUpdate(bool abort)` (`src/gui/render.cpp:475`) is where every
  rendered frame's data becomes available, immediately before it's handed
  to whichever output backend is active. When
  `CaptureState & (CAPTURE_IMAGE|CAPTURE_VIDEO)` is set
  (`render.cpp:491`), it calls (`render.cpp:506-507`):

  ```cpp
  CAPTURE_AddImage(render.src.width, render.src.height, render.src.bpp,
      pitch, flags, fps, (uint8_t*)scalerSourceCacheBuffer,
      (uint8_t*)&render.pal.rgb);
  ```

- `scalerSourceCacheBuffer` (`render.cpp:58`) is the pre-scaler source
  frame cache -- one full frame at the guest's *native* resolution and
  color depth, filled by the VGA draw handlers during
  `RENDER_StartUpdate()`/line drawing, before any backend-specific
  upscale, filter, or GPU upload happens.
- `CAPTURE_AddImage()` (`src/hardware/hardware.cpp:809`, gated by
  `#if C_SSHOT` -- confirmed `1` in this fork's `vs/config.h:172`) does
  the actual PNG encode via libpng (already linked into `dosbox-x.exe`;
  headers included at `hardware.cpp:43-44`) and, for `CAPTURE_IMAGE`,
  writes it to a numbered file in the configured capture directory via
  `OpenCaptureFile()` (`hardware.cpp:574`).

### Why this is backend-agnostic

`RENDER_EndUpdate()`'s `CAPTURE_AddImage()` call happens *before* any
output backend touches the frame -- `GFX_EndUpdate()`
(`render.cpp:510`), which is what actually pushes pixels to
`SCREEN_SURFACE`/`SCREEN_OPENGL`/`SCREEN_DIRECT3D`/`SCREEN_TTF`, runs
*after* it. `RENDER_EndUpdate()` itself is called uniformly from the VGA
draw routines (`src/hardware/vga_draw.cpp`, multiple call sites) and from
the Direct3D11/Voodoo 3D passthrough paths (`src/output/output_direct3d11.cpp:884`,
`src/hardware/voodoo_interface.cpp:147,201`) -- every path converges on
the same `CAPTURE_AddImage()` call site, so a hook there needs no
per-backend logic.

### Thread

`RENDER_EndUpdate()` runs inside VGA vertical-retrace-driven draw
processing, scheduled via `PIC_AddEvent()` -- i.e. on the same single
emulator thread that runs `cpudecoder()`/`Normal_Loop()`. This is exactly
the thread Phase 6B's `KEYBOARD_AddKey()`/`Mouse_*()` calls are already
safe on, so a capture request can reuse the same
"pending-request-queue-drained-on-the-emulator-thread" pattern
(`g_pendingPauses`/`g_pendingInputs` in `debug_ai.cpp`) -- just with a
*different* drain site: not `Normal_Loop()`'s `DEBUG_ExitLoop()` hook
(Phase 4C/6B's site), but a new one-shot check added right where
`CaptureState` is already checked in `RENDER_EndUpdate()`, since that is
the only place `scalerSourceCacheBuffer` is valid and not yet overwritten
by the next frame.

**Important consequence**: unlike pause/input requests, which the emulator
thread can service on essentially every loop iteration, a capture request
can only be serviced when a frame is *actually rendered* --
`RENDER_StartUpdate()` has its own frameskip/inactive guards
(`render.cpp:401-413`). A request should tolerate roughly one frame of
latency, the same as the existing Host+P screenshot already does, and
needs a timeout/error path (mirroring `EXECUTION_TIMEOUT`'s precedent) for
the case where no frame renders in time (e.g. guest stopped, or between
video mode changes).

## Design decision: never write to disk

The existing `CAPTURE_IMAGE` path always writes a numbered PNG file into
the user's configured capture directory via `OpenCaptureFile()`. That is
the wrong default for an AI-triggered capture -- an agent calling this
tool repeatedly must not silently accumulate files in the user's own
screenshot folder. The new capture path must call libpng directly with
`png_set_write_fn()` (a standard libpng entry point) writing into an
in-memory buffer, instead of `png_init_io(png_ptr, fp)` -- bypassing
`OpenCaptureFile()` entirely. `CAPTURE_AddImage()`'s own structure already
separates "open the destination" from "encode," so this is a
straightforward substitution, not a rewrite of the encode logic.

## Pixel format handling

`render.src.bpp` (set at `render.cpp:1208`) is one of `8/15/16/24/32` --
the guest's *native* color depth, never pre-converted to RGBA anywhere in
this path. `CAPTURE_AddImage()`'s existing per-bpp handling
(`hardware.cpp:855-935`) is the exact reference for what conversion each
depth needs, and can be adapted (not merely consulted) for the new
`"format":"rgba"` output:

| `render.src.bpp` | Existing PNG handling | What `rgba8888` needs |
|---|---|---|
| `8` (VGA 256-color, indexed) | `png_set_PLTE()` with `render.pal.rgb` (`hardware.cpp:860-869`), no per-pixel conversion -- PNG stores the index + palette directly | Per-pixel palette lookup: `rgba[i] = {pal[idx*4+0], pal[idx*4+1], pal[idx*4+2], 255}` |
| `15` (5-5-5) | Unpacked per-pixel via bit masks into 8-bit channels (`hardware.cpp:906-918`): `(pixel & 0x001f) * 0x21 >> 2`, `(pixel & 0x03e0) * 0x21 >> 7`, `(pixel & 0x7c00) * 0x21 >> 12` | Same three shifts, written directly as R,G,B (see ordering note below), plus `A=255` |
| `16` (5-6-5) | Same pattern, different masks/shifts (`hardware.cpp:924-931`): `0x001f`/`0x07e0`/`0xf800` | Same shifts, `A=255` |
| `24`/`32` | `png_set_bgr(png_ptr)` (`hardware.cpp:871`) -- source bytes are consumed as BGR(A) order, libpng swaps on write | Read as B,G,R(,A) and reorder into R,G,B,A directly |

**Byte-order note**: the existing code's `doubleRow` scratch buffer is
filled in B,G,R order for the 15/16bpp cases too (the low bits of a
555/565 pixel are conventionally blue) and then handed to libpng *with*
`png_set_bgr()` active, which is what makes the final PNG file come out
correctly as RGB. A from-scratch `rgba8888` packer must **not** copy that
BGR byte order verbatim -- it should write straight into R,G,B(,A) order,
since there is no libpng swap step in that path. This is the one place a
naive "copy the existing loop" port would silently produce a
blue/red-swapped image; call it out explicitly in the implementation.

**Row stride**: use `render.scale.cachePitch` (`render.cpp:499`, passed
into `CAPTURE_AddImage` as `pitch`) as the row stride, not an assumed
`width * bpp/8` -- rows are not guaranteed tightly packed.

**Double-width/double-height**: `CAPTURE_FLAG_DBLW`/`CAPTURE_FLAG_DBLH`
(`render.cpp:495-496`, derived from `render.src.dblw`/`dblh`) mean some
video modes (e.g. certain 320-column text modes) are captured at double
their nominal `render.src.width`/`height`. The reported `width`/`height`
in `video.frame.capture`'s result must reflect the *actual* output
dimensions (after doubling), matching what `CAPTURE_AddImage` already
computes at `hardware.cpp:817-819`, not the raw `render.src` values.

## API (from the Phase 7 draft, section 3.1, unchanged except as noted)

```text
video.frame.capture
params:
{
  "format": "png" | "rgba",
  "include_cursor": boolean,        // default false
  "max_width": integer | null,      // default null, keep native size
  "max_height": integer | null      // default null, keep native size
}

result (format=png):
{
  "frame_id": uint64,
  "width": uint32,
  "height": uint32,
  "pixel_format": "rgba8888",
  "cursor_included": boolean,
  "captured_at_emulated_ms": uint64,
  "png_base64": string
}

result (format=rgba): same shape with "rgba_base64" instead of "png_base64"
```

No protocol change is needed for the payload itself: this session's
Phase 6 work already established that `SendLine()` (`debug_ai.cpp:1162`)
has no outbound size cap -- only *incoming* request lines are capped at
`MAX_LINE_LENGTH` (8192 bytes, `debug_ai.cpp:90`), checked in
`HandleLine()`. An 8 MiB PNG payload (the draft's proposed cap) works over
the existing newline-delimited-JSON transport as-is; enforce the cap at
the application level (return `FRAME_TOO_LARGE` with a suggested
`max_width`/`max_height`) rather than inventing a chunked/streaming
alternative.

## Open questions (not resolved by this research pass)

1. **Guest cursor compositing** (`include_cursor=true`): not yet located.
   `scalerSourceCacheBuffer` is filled by VGA draw handlers -- whether a
   software-rendered mouse cursor (DOS mouse driver's own drawn cursor,
   if the guest program draws one itself) is already part of that data,
   or whether DOSBox-X composites a cursor overlay at a *later* stage
   (closer to `GFX_EndUpdate`, i.e. after this hook point), needs a
   follow-up investigation before `include_cursor=true` can be
   implemented. Until then, `include_cursor` should default to `false`
   and `true` should be rejected or documented as not-yet-supported
   rather than silently ignored.
2. **Capture latency budget**: how long a request might realistically
   wait for the next `RENDER_EndUpdate()` call (frame rate dependent,
   affected by frameskip settings) has not been measured. Needed to pick
   a sensible timeout distinct from `REQUEST_TIMEOUT_SECONDS`.
3. **Voodoo/Direct3D11 passthrough**: confirmed by source that
   `voodoo_interface.cpp` and `output_direct3d11.cpp` also reach the same
   `CAPTURE_AddImage()` call site, but this hasn't been exercised by an
   actual build+capture test under either of those configurations.

## Verification plan (not yet executed)

1. Capture a frame from a 320x200 VGA (bpp=8) test program and a 640x480
   SVGA (bpp=16 or 32) test program; decode both PNGs and confirm correct
   dimensions and, for at least one known-color test pattern, correct
   pixel values (catches the BGR/RGB ordering bug called out above).
2. Fully cover the DOSBox-X window with another host window; confirm the
   capture is unaffected (expected to pass trivially, since the source is
   `scalerSourceCacheBuffer`, never host/window pixels -- but should still
   be verified once built, the same way Phase 6B's design was verified
   live rather than assumed correct from source reading alone).
3. Issue 100 consecutive captures; confirm no guest stall, no unbounded
   memory growth, and no torn/inconsistent frames.
4. Compare `format=png` and `format=rgba` output for the same frame
   (decode the PNG, compare pixel-for-pixel against the RGBA buffer) to
   cross-check the from-scratch RGBA packer against the proven PNG path.
