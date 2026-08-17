# Phase 7B: mouse capture status & absolute mouse control (Epic B)

> Scope: Epic B of
> `docs/phase7-observability-and-autonomous-control-requirements.md`
> (`input.mouse.capture.get`/`.set`, `input.mouse.move_absolute`,
> `input.mouse.click_at`).
> Status: design, grounded in source investigation. Not yet implemented.

## Goal

Let an agent read DOSBox-X's own mouse-capture state (equivalent to
whether Ctrl+F10 is currently "on"), toggle it the same way Ctrl+F10
does, and click/move to a specific point in the guest's own coordinate
space -- the same `guest_pixels` space `video.frame.capture` (Phase 7A)
already reports -- without ever touching the host cursor, host window
focus, or any Win32 input-injection API. This closes the last gap for
UI-driven guest programs: Phase 6B's `move_relative` can nudge the
cursor, but an agent that has just taken a screenshot has no way to
say "click at pixel (340, 210) in that image" without first walking
the cursor there blind, relative step by relative step.

## Architecture: two independent problems, two different thread routes

Epic A (frame capture) and Phase 6B (key/mouse injection) each needed
exactly one thread-safety answer, because each API is meaningful in
only one debugger state (frame capture: guest must be rendering, so
"running"; key/mouse injection: guest must be running to receive it).
Epic B is different: the requirements draft (section 2) explicitly
allows capture status/toggle to work "either stopped or running" --
unlike `move_absolute`/`click_at`, which the draft's section 4.3.4
requires to fail with `DEBUGGER_STOPPED` like every other guest-input
method. So this design splits into two different mechanisms:

### `capture.get` / `capture.set`: dual-route through the EXISTING queues

`GFX_CaptureMouse(bool)` (`src/gui/sdlmain.cpp:2668`) is what Ctrl+F10
already calls -- it sets `sdl.mouse.locked`, calls
`SDL_SetRelativeMouseMode()`/`SDL_WM_GrabInput()`, and touches the
window title and menu-check state. All of that is main-thread-only
(SDL calls are not documented thread-safe in this codebase, and
`mouselocked`/`sdl.mouse.locked` are plain, non-atomic globals mutated
only from that thread -- see `video.h:99`,
`sdlmain.cpp:976,2688,3786`). Reading `mouse.max_x`/`CurMode`/
`AllowINT33RMAccess()` for the `mode`/`guest_width`/`guest_height`
fields (see below) needs the same thread for the same reason
`cpu.get`/`code.current` already do (Gate A analysis, section 5.9).

Rather than inventing a THIRD drain site (a new hook inside
`DEBUG_Loop()`, `src/debug/debug.cpp`, mirroring the existing
`DEBUG_AI_Poll()` call there), this reuses the two hooks that already
exist and already run unconditionally on the main thread in their
respective states:

- **Stopped** (`g_debuggerActive == true`): route through the SAME
  `g_requestQueue`/`DEBUG_AI_Poll()` mechanism `debug.status`/`cpu.get`/
  etc. already use (`dosbox.cpp:5088`, called from `DEBUG_Loop()`) --
  two new `AIMethod` values, `MouseCaptureGet`/`MouseCaptureSet`.
- **Running** (`g_debuggerActive == false`): route through the SAME
  `g_pendingInputs`/`DEBUG_AI_CheckPendingInput()` mechanism Phase 6B's
  key/mouse injection already uses (`dosbox.cpp:542`, called from
  `Normal_Loop()`) -- two new `AIInputOp` values,
  `MouseCaptureGet`/`MouseCaptureSet`.

`HandleLine()` picks the route the same way it already picks between
`debug.status`'s two paths: check `g_debuggerActive.load()` once on the
socket thread (an existing atomic, no new one needed) and enqueue into
whichever queue is currently being drained. Both routes call the SAME
shared helper (`BuildMouseCaptureStatus()`/`ApplyMouseCaptureSet()`) so
the two code paths can't drift. No changes to `dosbox.cpp` or
`debug.cpp` are needed -- both hook call sites already run every
iteration of their respective loops.

### `move_absolute` / `click_at`: existing running-only queue only

These two dispatch real guest input (`Mouse_CursorMoved()`/
`Mouse_ButtonPressed()`/`Mouse_ButtonReleased()`), so they follow
Phase 6B's existing rule exactly: two more `AIInputOp` values
(`MouseMoveAbsolute`, `MouseClickAt`) added to the SAME
`g_pendingInputs` queue, gated by the SAME `DEBUGGER_STOPPED` check
`HandleLine()` already applies to `input.key.*`/`input.mouse.move_relative`
etc. `click_at` performs move + button-down + button-up inside one
`AIInputOp::MouseClickAt` case in
`DEBUG_AI_CheckPendingInput()`'s per-item loop -- since nothing else
runs on the emulator thread between two loop iterations, this
satisfies the requirement draft's "same emulator-thread dispatch,
nothing else can insert between them" (section 4.1) for free, without
a new lock.

## Reusing DOSBox-X's own absolute-positioning path

`Mouse_CursorMoved(xrel, yrel, x, y, emulate)` (`src/ints/mouse.cpp:867`)
already has a second, non-relative mode used when `emulate=false`:

```cpp
} else if (AllowINT33RMAccess() && CurMode != NULL) {
    if (CurMode->type == M_TEXT) {
        mouse.x = x*real_readw(BIOSMEM_SEG,BIOSMEM_NB_COLS)*8;
        mouse.y = y*(IS_EGAVGA_ARCH?(real_readb(BIOSMEM_SEG,BIOSMEM_NB_ROWS)+1):25)*8;
    } else {
        if ((mouse.max_x > 0) && (mouse.max_y > 0)) {
            mouse.x = x*mouse.max_x;
            mouse.y = y*mouse.max_y;
        } else {
            mouse.x += xrel;
            mouse.y += yrel;
        }
    }
}
```

`x`/`y` here are normalized `[0.0, 1.0]` -- this is DOSBox-X's own
seamless/integrated mouse positioning path (the same mechanism used
when the guest's mouse cursor tracks the host cursor 1:1 without
capture), not a bridge invention. `move_absolute`/`click_at` call
`Mouse_CursorMoved(0.0f, 0.0f, normX, normY, /*emulate=*/false)`
directly -- the SAME internal entry point Phase 6B's relative move
already uses, just the other branch of it.

**Consequence**: if `AllowINT33RMAccess()` returns false (protected
mode without virtual-8086, or DOS kernel shut down -- booted a guest
OS), or `CurMode` is null, or (for graphics modes) `mouse.max_x`/
`mouse.max_y` are still `0` (no video mode has set a mouse range yet),
the `else` branch silently does `mouse.x += xrel` with `xrel=0` -- a
no-op, NOT an error. Calling `Mouse_CursorMoved` blind in that state
would look like success while doing nothing, exactly the "must not
claim `game_accepted`/fake success" failure mode the requirements
draft's section 2.1 warns about generally. So this needs an explicit
availability check performed BEFORE calling it, not inferred from its
return value (it has none).

### New: `Mouse_AbsolutePositioningAvailable()` (`src/ints/mouse.cpp`)

`AllowINT33RMAccess()`, `CurMode`, and `mouse.max_x`/`max_y` are all
file-local to `mouse.cpp` -- not reachable from `debug_ai.cpp` (unlike
`Mouse_CursorMoved`/`Mouse_ButtonPressed`/`Mouse_ButtonReleased`, which
are already `mouse.h` public API). Add one new thin public function,
mirroring the existing `Mouse_IsLocked()` precedent
(`mouse.h:47`/`mouse.cpp`) of exposing exactly one boolean rather than
the underlying state:

```cpp
// mouse.h
bool Mouse_AbsolutePositioningAvailable(void);

// mouse.cpp
bool Mouse_AbsolutePositioningAvailable(void) {
    if (!AllowINT33RMAccess() || CurMode == NULL) return false;
    if (CurMode->type == M_TEXT) return true;
    return mouse.max_x > 0 && mouse.max_y > 0;
}
```

This is exactly the condition `Mouse_CursorMoved`'s `emulate=false`
branch already uses to decide whether it will actually move the
cursor vs. silently no-op -- duplicated as a read-only query, not a
new/parallel decision. `debug_ai.cpp` calls this (from the emulator
thread, inside `DEBUG_AI_CheckPendingInput()`) to decide
`ABSOLUTE_MOUSE_UNAVAILABLE` vs. proceeding, and reuses it again for
`capture.get`'s `mode` field (see below) so the two never disagree.

## Coordinate spaces

### `guest_pixels`: reuse Phase 7A's own width/height computation

The requirements draft ties `move_absolute`/`click_at`'s `guest_pixels`
space to "framebuffer left corner as origin" -- i.e. it must match
what `video.frame.capture` reports, so an agent can take a screenshot,
pick a pixel in it, and click exactly there. Phase 7A's width/height
(`UnpackFrameToRGBA8888()`, `debug_ai.cpp:903`) is derived from
`render.src.width/height` doubled by `render.src.dblw/dblh`
(`render.h:64-73`, `extern Render_t render;`, globally readable). Epic
B reuses the SAME formula directly against the live `render` global
(no dependency on a frame having just been captured):

```cpp
Bitu w = render.src.width  * (render.src.dblw ? 2 : 1);
Bitu h = render.src.height * (render.src.dblh ? 2 : 1);
```

read on the main thread (both `capture.get`'s and `move_absolute`'s
handlers already run there per the routing above), so this is safe for
the same reason reading `render.src` from `RENDER_EndUpdate()` already
is.

**Guest-pixels -> normalized conversion**: `normX = x / (w > 1 ? w - 1
: 1)`, same for Y -- chosen (over dividing by `w`) so that the exact
bottom-right pixel (`x = w-1`) maps to exactly `1.0`, letting
`click_at` reach every corner of the screen exactly, which the
requirements draft's acceptance criterion 4.3.2 (nine-grid click test)
needs. `clamp=false` + out-of-range (`x < 0 || x >= w`) ->
`INVALID_PARAMETER`; `clamp=true` -> clamp to `[0, w-1]`/`[0, h-1]` and
set `clamped=true`, per the draft's section 4.2.

**Normalized -> guest_pixels for the response**: the draft requires
the result's `coordinate_space` to always read `"guest_pixels"`
(section 4.1) regardless of which space the request used, so a
`normalized`-space request still gets back the resolved
`guest_x`/`guest_y` in pixels: `guest_x = round(normX * (w - 1))`.

### `mode` field (`capture.get`)

`"absolute"` when `Mouse_AbsolutePositioningAvailable()` is true at
the moment of the call, else `"relative"` (relative movement via
`move_relative` is unconditionally available whenever the guest is
running, per Phase 6B). `"unavailable"` is reserved by the schema but
not produced by this implementation -- there is no known build
configuration in this fork where neither path works while the guest is
running, and inventing a synthetic case would be worse than leaving it
unreachable. `guest_width`/`guest_height` use the `render.src`
computation above; `null` only if `render.src.width/height` are
themselves `0` (no video mode set yet, i.e. very early boot).

## `last_guest_x`/`last_guest_y`

Tracked as two plain (non-atomic) `double`s local to `debug_ai.cpp`,
written ONLY by `DEBUG_AI_CheckPendingInput()` immediately after a
successful `MouseMoveAbsolute`/`MouseClickAt` dispatch, and read ONLY
by `BuildMouseCaptureStatus()` -- both exclusively on the main thread
(via the dual-route mechanism above), so no lock is needed, mirroring
`g_heldKeys`/`g_heldButtons`'s existing "touched only from the
emulator thread" comment (`debug_ai.cpp:639`). Per the draft's section
4.2, these represent the bridge's last successful dispatch, never a
claim about what the guest program actually read.

## API (from the Phase 7 draft, section 4.1, unchanged)

See `docs/phase7-observability-and-autonomous-control-requirements.md`
section 4 for the full request/response shapes
(`input.mouse.capture.get`/`.set`, `input.mouse.move_absolute`,
`input.mouse.click_at`) and error codes (`CAPTURE_UNAVAILABLE`,
`ABSOLUTE_MOUSE_UNAVAILABLE`, `INVALID_PARAMETER`, `DEBUGGER_STOPPED`).
This design doc does not change that surface.

`CAPTURE_UNAVAILABLE`: per the draft, returned when "目前 video
backend／平台沒有可安全控制的 capture state." `GFX_CaptureMouse(bool)`
is unconditional in this codebase (no backend guard around it) --
investigation found no currently-known configuration in this fork
where it is unsafe to call, so `capture.set` does not produce this
code in the initial implementation. Documented as reserved, matching
`mode`'s `"unavailable"` above, rather than removed from the schema.

## Implementation touches (four files)

1. `dosbox-src/src/ints/mouse.cpp` + `include/mouse.h`: add
   `Mouse_AbsolutePositioningAvailable()`.
2. `dosbox-src/src/debug/debug_ai.cpp`: `AIMethod::MouseCaptureGet/Set`
   (stopped route) + `AIInputOp::MouseCaptureGet/Set/MouseMoveAbsolute/
   MouseClickAt` (running route + the two guest-input-only ops), the
   shared `BuildMouseCaptureStatus()`/coordinate-conversion helpers,
   `#include "video.h"` for `GFX_CaptureMouse`/`mouselocked`.
3. `ai/dosbox_client.py`: `get_mouse_capture()`, `set_mouse_capture()`,
   `move_mouse_absolute()`, `click_at()`.
4. `ai/server.py`: four corresponding MCP tools;
   `AGENT_GUIDE.md`/`.zh-TW.md`, `README.md`/`.zh-TW.md` tool-count and
   reference updates; `CHANGELOG.md` entry.

## Verification plan

Mirrors Phase 7A/6B's live-instance verification (no automated
`pytest` suite yet, tracked as the same follow-up already noted for
Phase 6A/6B/7A):

1. `capture.set(true)`/`capture.set(false)` while running, then while
   stopped (`-break-start`) -- `capture.get` reflects each
   immediately in both states.
2. Nine-grid `click_at` against a mouse-test guest program (matching
   the draft's 4.3.2), including the four exact corners (`(0,0)`,
   `(w-1,0)`, `(0,h-1)`, `(w-1,h-1)`) to confirm the `w-1`/`h-1`
   normalization above lands exactly on-pixel, not one short.
3. `move_absolute`/`click_at` while stopped -> `DEBUGGER_STOPPED`,
   with no residual button state (mirroring Phase 6B's existing
   stuck-input verification).
4. A protected-mode or booted-guest-OS scenario (`AllowINT33RMAccess()`
   false) -> `ABSOLUTE_MOUSE_UNAVAILABLE`, not a silent no-op success.
5. `capture.get`'s `guest_width`/`guest_height` cross-checked against
   the SAME session's `video.frame.capture` result for the same video
   mode -- must match exactly, since both derive from `render.src`.

## Implementation status: done, verified live (both routes)

Implemented as designed, in the four files listed above (plus
`include/mouse.h`/`include/video.h` for the two new thin accessors).
Built clean (0 errors, 0 new warnings) against both the `Release SDL2`
and `Release` (SDL1, this project's documented health-check
configuration) `x64` configurations.

Verified live via `DOSBoxClient`, the actual MCP tool functions
(`ai/server.py`), and raw protocol calls against a running
`dosbox-x.exe`, all on the **running** route (the dual-route path used
whenever the debugger is not stopped -- the common case for an agent
driving a game or program):

1. `capture.get`/`capture.set(true/false)` toggle and reflect instantly.
2. `move_absolute(0.5, 0.5, normalized)` on a 720x400 frame landed at
   exactly `(360, 200)` -- the frame's true center, confirming the
   normalized<->guest_pixels conversion.
3. `click_at` at all four exact corners (`(0,0)`, `(719,0)`, `(0,399)`,
   `(719,399)`) of a 720x400 frame landed exactly on-pixel -- confirms
   the `w-1`/`h-1` normalization decision above lands on the true edge,
   not one pixel short, matching acceptance criterion 4.3.2's nine-grid
   test intent.
4. Out-of-range coordinates without `clamp` -> `INVALID_PARAMETER`;
   with `clamp=true` -> clamped to the frame's bounds, `clamped: true`.
5. `capture.get`'s `guest_width`/`guest_height` matched
   `video.frame.capture`'s own reported width/height for the same video
   mode (both `720`/`400` in every run), confirming the shared
   `render.src` formula.
6. `input_sequence` increments monotonically across calls on one
   connection, as intended.

**Stopped route, verified in a follow-up session after root-causing why
it couldn't be reached initially**: the original blocker was never a
Phase 7B code defect -- it was `dosbox-x.exe`'s debugger console setup
(`WIN32_Console()`/`ResizeConsole()`, `src/debug/debug_win32.cpp`)
crashing whenever the process's own stdout was piped/redirected rather
than inheriting a genuine console, which is exactly how this session's
automated launches worked. See the "Bridge fix -- debugger console
crash on piped/redirected stdio" `CHANGELOG.md` entry and
`AGENT_GUIDE.md`'s launch section for the full root cause and fix.
Once launched with a genuine inherited console (`pause_execution()` no
longer crashes it), the stopped route was exercised directly:

7. `capture.get`/`capture.set(true/false)` while genuinely stopped
   (`execution.pause` then `debug.status` confirmed `stopped: true`)
   toggled and reflected instantly, via the `g_requestQueue`/
   `DEBUG_AI_Poll()` route -- matching the running route's behavior
   exactly, as the shared-helper design predicted.
8. `move_absolute`, `click_at`, and `key_tap` (Phase 6B) each correctly
   rejected with `DEBUGGER_STOPPED` while stopped, with the exact same
   error message existing input methods already use.
