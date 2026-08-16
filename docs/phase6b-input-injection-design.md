# Phase 6B: guest keyboard/mouse input injection

## Goal

Let an AI agent send keyboard and mouse input to the guest DOS
program/game running inside DOSBox-X, through the native AI bridge
(`dosbox-src/src/debug/debug_ai.cpp`), so a debugging session can look
like:

1. Set a write watchpoint on a target buffer (`breakpoint.memory.real.set`
   / `breakpoint.memory.set`, Phase 6A).
2. `execution.continue`.
3. Send a key (`input.key.tap("enter")`).
4. The guest program reacts (e.g. a text-adventure/dialogue engine prints
   the next line).
5. The watchpoint fires.
6. The agent reads `CS:EIP`, registers, and the source buffer, and walks
   callers.
7. Send the next key to trigger the next step.

All of this without ever switching windows, physically pressing a key, or
handing control back to a human in between.

## Non-goals / explicit exclusions

Per direct instruction, this deliberately does **not** use:

- Windows `SendKeys` or any other OS-level keystroke injection API.
- Window focus manipulation or window handles.
- Simulated mouse clicks on DOSBox-X's own GUI/menu.
- Win32 GUI automation of any kind.

Input reaches the guest exclusively through DOSBox-X's own internal
keyboard/mouse emulation entry points -- the same ones its real SDL event
handlers call when a physical key or mouse event arrives. From the
guest's perspective, there is no difference between a real keypress and
one injected this way.

## Architecture

```
Agent -> MCP input tool -> DOSBoxClient (ai/dosbox_client.py)
      -> native AI bridge (debug_ai.cpp)
      -> KEYBOARD_AddKey() / Mouse_CursorMoved() / Mouse_ButtonPressed() / Mouse_ButtonReleased()
      -> guest game
```

`KEYBOARD_AddKey(KBD_KEYS, bool pressed)` (`include/keyboard.h`) and the
`Mouse_*` functions (`include/mouse.h`) are exactly what
`src/gui/sdlmain.cpp`'s real keyboard/mouse SDL event handlers call.
`SendKey()` (sdlmain.cpp, used by DOSBox-X's own "Send Key" menu, e.g.
Ctrl+Alt+Del) is existing precedent for calling `KEYBOARD_AddKey()`
directly outside the SDL event path, confirming it's a safe, intended
entry point for synthetic key events.

### Why input requires the debugger to be running, not stopped

`KEYBOARD_AddKey()`/`Mouse_*()` are only safe to call from the emulator
thread. The existing AI bridge request queue (`g_requestQueue`, drained by
`DEBUG_AI_Poll()`) only runs while `DEBUG_Loop()` is the active main-loop
handler -- i.e. only while the debugger is genuinely *stopped*. That is
the opposite of when input injection is useful (steps 3 and 7 above
happen while the guest is running, right after `execution.continue`).

Phase 4C solved exactly this class of problem for `pause_execution()`
(which is also only meaningful while running): a small thread-safe
pending list, drained by a new hook in `Normal_Loop()`'s existing
per-iteration `DEBUG_ExitLoop()` check (`dosbox.cpp`). Phase 6B reuses the
identical pattern:

- `g_pendingInputs` (`debug_ai.cpp`) -- a queue of `PendingInputRequest`,
  fed by socket threads via `DEBUG_AI_RequestInput()`.
- `DEBUG_AI_CheckPendingInput()` (declared in `include/debug.h` and
  `debug_ai.h`, defined in `debug_ai.cpp`) -- drains the queue and calls
  `KEYBOARD_AddKey()`/`Mouse_*()`. Called from `Normal_Loop()`
  (`dosbox.cpp`), on the emulator thread, right next to the existing
  `DEBUG_AI_CheckPauseRequest()` call.
- The socket thread blocks on the same per-connection
  `responseReady`/condition-variable pattern every other bridge method
  uses (`REQUEST_TIMEOUT_SECONDS`), and `DEBUG_AI_CancelInput()` mirrors
  `DEBUG_AI_CancelPause()` to avoid a late completion writing into a
  response slot a *later* request on the same (reused) connection is
  waiting on.

If a client calls an `input.*` method while the debugger is stopped, the
bridge returns `DEBUGGER_STOPPED` immediately (no queueing, no timeout
wait) -- the mirror image of `execution.pause`'s `ALREADY_STOPPED` guard.

## API (v1)

All methods are newline-delimited JSON-RPC over the existing
`127.0.0.1:9876` bridge, following the same `{"id", "method", "params"}` /
`{"id", "ok", "result"|"error"}` shape as every other method.

| Method | Params | Result |
|---|---|---|
| `input.key.down` | `{"key": "<name>"}` | `{"pressed": true}` |
| `input.key.up` | `{"key": "<name>"}` | `{"pressed": false}` |
| `input.key.tap` | `{"key": "<name>"}` | `{"tapped": true}` |
| `input.mouse.move_relative` | `{"dx": <num>, "dy": <num>}` | `{"moved": true}` |
| `input.mouse.button.set` | `{"button": 0\|1\|2, "pressed": bool}` | `{"pressed": bool}` |
| `input.mouse.button.click` | `{"button": 0\|1\|2}` | `{"clicked": true}` |
| `input.release_all` | (none) | `{"released": true}` |

Python wrapper: `DOSBoxClient.key_down/key_up/key_tap/move_mouse_relative/
set_mouse_button/click_mouse/release_all_input` (`ai/dosbox_client.py`).

### Keyboard: named keys only, not scan codes or free text

`key` is validated against a fixed whitelist (`ParseKeyName()`,
`debug_ai.cpp`) mapping name strings directly to `KBD_KEYS` enum values
(`include/keyboard.h`) -- e.g. `"a"`, `"1"`, `"f1"`, `"enter"`,
`"leftshift"`, `"kp5"`. An unrecognized name fails closed
(`INVALID_PARAMETER`); there is no free-text/DBCS/scan-code path in v1.

v1 covers the standard US 104-key layout (letters, digits, F1-F12,
modifiers, standard punctuation, navigation cluster, arrows, numeric
keypad). Windows keys, F13-F24, and the Japanese/Korean-specific
`KBD_KEYS` entries are intentionally not mapped yet -- not needed by any
currently supported guest workflow, and better added deliberately, with
real test coverage, than guessed at during this pass.

`type_text` (arbitrary string -> key events) is deliberately deferred:
it depends on keyboard layout, Shift state, the guest's DOS code page,
whether the guest program reads scan codes directly vs. the BIOS keyboard
buffer, and whether CJK/DBCS text can even be expressed as key events at
all. None of that is resolved by this design.

### Mouse

`button` is `0` (left), `1` (right), `2` (middle) -- matching
`Mouse_ButtonPressed()`'s own convention, confirmed against
`sdlmain.cpp`'s real SDL mouse-button handler.

`move_mouse_relative(dx, dy)` calls `Mouse_CursorMoved(dx, dy, 0, 0,
/*emulate=*/true)`. **Known limitation**: relative motion only reaches
the guest while DOSBox-X's mouse is captured/locked (`Ctrl+F10`) *and*
the guest is running a driver that reads relative motion --
`Mouse_CursorMoved()` itself is a no-op while the debugger is active
(`IsDebuggerActive()` guard, `mouse.cpp`), which is consistent with input
injection only working while running (see above), but capture state is
independent of anything this bridge controls. This is a guest/DOS-side
precondition to document for agents, not a reason to omit the method --
absolute-position/mouse-integration-driver support, and possibly a
capture-toggle method, are left for a follow-up once real usage shows
whether it's needed.

Button press/release/click never depend on capture state --
`Mouse_ButtonPressed()`/`Mouse_ButtonReleased()` update `mouse.buttons`
unconditionally.

## Stuck-input cleanup

The most important safety property for input injection: a key or mouse
button must never stay stuck "down" in the guest because the AI
harness's session ended (timeout, crash, or just forgetting to release)
before sending the matching release event.

- `g_heldKeys` / `g_heldButtons` (`debug_ai.cpp`) track, per connection,
  every key/button a `key_down`/`mouse.button.set(pressed=true)` left
  held. Both are touched only from the emulator thread, inside
  `DEBUG_AI_CheckPendingInput()`.
- **Disconnect**: `ConnectionThreadFunc`'s existing disconnect path (same
  place that already logs "client disconnected" and removes the
  connection from `g_connections`) now also enqueues a `ReleaseAll`
  request for that connection, with `expectsResponse=false` since nobody
  is waiting on a response by then. This covers session timeout and
  client crash -- the two cases called out as most important -- without
  the harness needing to do anything.
- **Explicit cleanup**: `input.release_all` exposes the identical
  mechanism directly, for a well-behaved agent/harness to call
  proactively at the end of a session.
- Verified live: a smoke test held a key down (`key_down("a")`) and then
  closed the socket without ever calling `key_up`/`release_all_input` --
  the bridge and a subsequent reconnect both stayed healthy (see
  "Verification" below).

### Deferred: pause/reset/shutdown hooks

The request explicitly asked for cleanup on "pause/reset/shutdown" as
well as disconnect. This pass wires disconnect (the primary risk: an
external harness losing its session) and the explicit `input.release_all`
call. Hooking guest system reset and full DOSBox-X process shutdown too
is left for a follow-up:

- Guest reset re-initializes the emulated keyboard controller itself, so
  a stale `g_heldKeys` entry after reset is at worst a harmless no-op
  `KEYBOARD_AddKey(key, false)` call whenever it's eventually released,
  not a real stuck-key bug -- lower priority than disconnect.
- Full process shutdown (`DEBUG_AI_ShutDown()`) ends the entire emulated
  machine along with any "stuck" state, so there is nothing left to clean
  up by the time it would run.

## Verification

Not run through the automated `tests/` suite yet (tracked as follow-up
work, same as the Phase 6A real-mode memory watchpoints). Verified live
against a fresh build (`dosbox-x.exe -defaultdir -break-start
drive_c\STEP.COM`) via `ai/dosbox_client.py`:

- `input.key.tap` while the debugger is stopped raises
  `DOSBoxDebuggerStopped` (`DEBUGGER_STOPPED`), no timeout wait.
- After `execution.continue`: `key_tap`, `key_down`/`key_up`,
  `move_mouse_relative`, `set_mouse_button`, `click_mouse`, and
  `release_all_input` all succeed and return the documented result shape.
- `execution.pause` immediately after an input "storm" still returns a
  real, healthy `debug.status` snapshot -- the emulator thread was never
  destabilized by the new code path.
- A connection that calls `key_down("a")` and then disconnects *without*
  releasing it does not crash the bridge or the emulator; a fresh
  connection immediately afterward still gets healthy `debug.status`/
  `pause_execution` responses.
